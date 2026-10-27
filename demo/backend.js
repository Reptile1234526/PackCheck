// PackCheck demo backend: answers the web UI's /api/* calls in the browser,
// so the real interface from app.py runs without a Raspberry Pi or RFID reader.
// A "virtual backpack" stands in for the J4210u: tags in the bag are "read" on scan.
(function () {
  const STORE_KEY = 'packcheck-demo-v1';
  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MAX_HISTORY = 100;

  const SAMPLE_ITEMS = {
    'Laptop': 'E2806894000050217A3C0011',
    'Laptop charger': 'E2806894000050217A3C0012',
    'Math textbook': 'E2806894000050217A3C0013',
    'Chemistry binder': 'E2806894000050217A3C0014',
    'Calculator': 'E2806894000050217A3C0015',
    'Pencil case': 'E2806894000050217A3C0016',
    'Planner': 'E2806894000050217A3C0017',
    'Gym shoes': 'E2806894000050217A3C0018',
    'Headphones': 'E2806894000050217A3C0019',
  };
  // Tags that are physically in the bag but not registered yet, so "+ ADD ITEM" has something to find.
  const SPARE_TAGS = ['E2806894000050217A3C0020', 'E2806894000050217A3C0021'];
  const SCHOOL = ['Laptop', 'Laptop charger', 'Math textbook', 'Chemistry binder', 'Calculator', 'Pencil case', 'Planner'];

  function sampleState() {
    const profiles = {
      'School': SCHOOL,
      'Gym day': [...SCHOOL, 'Gym shoes'],
      'Weekend': ['Laptop', 'Laptop charger', 'Headphones'],
    };
    const schedule = {
      Monday: 'School', Tuesday: 'Gym day', Wednesday: 'School', Thursday: 'Gym day',
      Friday: 'School', Saturday: 'Weekend', Sunday: 'Weekend',
    };
    const tags = [...Object.values(SAMPLE_ITEMS), ...SPARE_TAGS];
    const bag = {};
    tags.forEach(epc => { bag[epc] = true; });
    bag[SAMPLE_ITEMS['Calculator']] = false; // the one item left on the desk

    // A week and a half of morning checks, a few with something forgotten.
    const forgot = { 2: ['Calculator'], 5: ['Gym shoes'], 8: ['Chemistry binder', 'Planner'] };
    const scans = [];
    for (let d = 10; d >= 1; d--) {
      const t = new Date();
      t.setDate(t.getDate() - d);
      t.setHours(7, 20 + (d * 7) % 25, (d * 13) % 60, 0);
      const profile = schedule[DAYS[t.getDay()]];
      const missing = forgot[d] || [];
      const items = profiles[profile].map(name => {
        const found = !missing.includes(name);
        return { name, found, rssi: found ? -38 - ((name.length * 7 + d) % 24) : null };
      });
      const found = items.filter(i => i.found).length;
      scans.push({ timestamp: localIso(t), profile, found, total: items.length, items });
    }

    return {
      config: {
        port: '/dev/ttyUSB0', baudrate: 57600, power_dbm: 20, scan_duration: 2.0,
        items: { ...SAMPLE_ITEMS },
        profiles,
        active_profile: 'School',
        day_schedule: schedule,
        auto_scan_times: ['07:15'],
        ntfy_topic: 'packcheck-demo',
        theme: 'dark',
      },
      history: { scans },
      tags,
      bag,
    };
  }

  // Same format as Python's datetime.now().isoformat().
  function localIso(d) {
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  let state;
  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY));
      if (saved && saved.config && saved.history && saved.tags) return saved;
    } catch (e) {}
    return sampleState();
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
    window.dispatchEvent(new Event('packcheck-demo-change'));
  }
  state = load();

  // --- Simulated reader ---
  function rssiFor(epc) {
    // Stable per tag, with a little jitter so repeated scans look live.
    let h = 0;
    for (const c of epc) h = (h * 31 + c.charCodeAt(0)) % 997;
    return -34 - (h % 26) - Math.floor(Math.random() * 4);
  }
  function readTags() {
    return state.tags.filter(epc => state.bag[epc]).map(epc => ({
      epc, rssi: rssiFor(epc), count: 3 + Math.floor(Math.random() * 10),
    }));
  }
  function scanDelay() {
    const s = parseFloat(state.config.scan_duration) || 2.0;
    return new Promise(r => setTimeout(r, Math.min(5, Math.max(0.5, s)) * 1000));
  }

  async function performCheck() {
    const config = state.config;
    // The UI switches to today's scheduled profile on load, so scan whichever chip is selected.
    const profileName = config.active_profile;
    const profileItems = (config.profiles[profileName] || []);
    await scanDelay();
    const byEpc = {};
    readTags().forEach(t => { byEpc[t.epc] = t; });
    const results = profileItems.filter(n => n in config.items).map(name => {
      const epc = config.items[name];
      const tag = byEpc[epc];
      return { name, epc, found: !!tag, rssi: tag ? tag.rssi : null, count: tag ? tag.count : 0 };
    });
    const found = results.filter(r => r.found).length;
    state.history.scans.push({
      timestamp: localIso(new Date()), profile: profileName, found, total: results.length,
      items: results.map(r => ({ name: r.name, found: r.found, rssi: r.rssi })),
    });
    state.history.scans = state.history.scans.slice(-MAX_HISTORY);
    save();
    return { items: results, found, total: results.length, profile: profileName };
  }

  // --- API routes (mirror app.py) ---
  const err = (msg, status) => ({ status: status || 400, body: { error: msg } });
  const ok = { body: { ok: true } };
  const str = v => (v || '').toString().trim();

  const routes = {
    'GET /api/check': async () => ({ body: await performCheck() }),

    'GET /api/scan': async () => {
      await scanDelay();
      const known = {};
      Object.entries(state.config.items).forEach(([n, e]) => { known[e] = n; });
      return { body: { tags: readTags().map(t => ({ ...t, name: known[t.epc] || null })) } };
    },

    'GET /api/items': () => ({ body: state.config.items }),

    'POST /api/items/add': d => {
      const name = str(d.name), epc = str(d.epc).toUpperCase();
      if (!name || !epc) return err('name and epc required');
      const c = state.config;
      if (name in c.items) return err(`'${name}' already exists`);
      c.items[name] = epc;
      const p = c.profiles[c.active_profile];
      if (p && !p.includes(name)) p.push(name);
      if (!state.tags.includes(epc)) { state.tags.push(epc); state.bag[epc] = true; }
      save();
      return ok;
    },

    'POST /api/items/remove': d => {
      const name = str(d.name), c = state.config;
      if (!(name in c.items)) return err(`'${name}' not found`, 404);
      delete c.items[name];
      Object.values(c.profiles).forEach(list => {
        const i = list.indexOf(name);
        if (i >= 0) list.splice(i, 1);
      });
      save();
      return ok;
    },

    'GET /api/profiles': () => {
      const c = state.config;
      return { body: {
        profiles: c.profiles, active: c.active_profile,
        scheduled: (c.day_schedule || {})[DAYS[new Date().getDay()]] || null,
        all_items: Object.keys(c.items),
      } };
    },

    'POST /api/profiles/active': d => {
      const name = str(d.name);
      if (!(name in state.config.profiles)) return err('Profile not found', 404);
      state.config.active_profile = name;
      save();
      return ok;
    },

    'POST /api/profiles/create': d => {
      const name = str(d.name);
      if (!name) return err('name required');
      state.config.profiles[name] = d.items || [];
      save();
      return ok;
    },

    'POST /api/profiles/update': d => {
      const name = str(d.name);
      if (!(name in state.config.profiles)) return err('Profile not found', 404);
      state.config.profiles[name] = d.items || [];
      save();
      return ok;
    },

    'POST /api/profiles/delete': d => {
      const name = str(d.name), c = state.config;
      if (!(name in c.profiles)) return err('Profile not found', 404);
      delete c.profiles[name];
      if (c.active_profile === name) c.active_profile = Object.keys(c.profiles)[0] || 'Everyday';
      save();
      return ok;
    },

    'POST /api/profiles/reorder': d => {
      const old = state.config.profiles, next = {};
      (d.order || []).forEach(n => { if (n in old) next[n] = old[n]; });
      Object.keys(old).forEach(n => { if (!(n in next)) next[n] = old[n]; });
      state.config.profiles = next;
      save();
      return ok;
    },

    'GET /api/profiles/export': (d, q) => {
      const name = q.get('name') || '', c = state.config;
      if (!(name in c.profiles)) return err('Profile not found', 404);
      const items = {};
      c.profiles[name].forEach(n => { if (n in c.items) items[n] = c.items[n]; });
      return { body: { type: 'packcheck_profile', name, items } };
    },

    'POST /api/profiles/import': d => {
      if (d.type !== 'packcheck_profile') return err('Invalid profile data');
      const name = str(d.name), items = d.items || {};
      if (!name) return err('name required');
      const c = state.config;
      Object.entries(items).forEach(([n, epc]) => {
        if (!(n in c.items)) c.items[n] = epc;
        if (!state.tags.includes(epc)) { state.tags.push(epc); state.bag[epc] = false; }
      });
      c.profiles[name] = Object.keys(items);
      save();
      return ok;
    },

    'GET /api/history': () => ({ body: state.history }),

    'GET /api/settings': () => {
      const c = state.config;
      return { body: {
        ntfy_topic: c.ntfy_topic || '', auto_scan_times: c.auto_scan_times || [],
        theme: c.theme || 'dark', power_dbm: c.power_dbm, scan_duration: c.scan_duration,
        day_schedule: c.day_schedule || {},
      } };
    },

    'POST /api/settings': d => {
      ['ntfy_topic', 'auto_scan_times', 'theme', 'power_dbm', 'scan_duration', 'day_schedule']
        .forEach(k => { if (k in d) state.config[k] = d[k]; });
      save();
      return ok;
    },
  };

  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, opts) {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const path = url.pathname.replace(/^.*(\/api\/)/, '/api/');
    if (!path.startsWith('/api/')) return realFetch(input, opts);
    const method = ((opts && opts.method) || 'GET').toUpperCase();
    const handler = routes[`${method} ${path}`];
    let res;
    if (!handler) {
      res = err('Not found', 404);
    } else {
      let data = {};
      try { data = opts && opts.body ? JSON.parse(opts.body) : {}; } catch (e) {}
      res = await handler(data, url.searchParams);
    }
    return new Response(JSON.stringify(res.body), {
      status: res.status || 200, headers: { 'Content-Type': 'application/json' },
    });
  };

  // --- Demo controls: banner + virtual backpack ---
  window.packcheckDemo = {
    getState: () => state,
    setInBag(epc, inBag) { state.bag[epc] = inBag; save(); },
    reset() {
      try { localStorage.removeItem(STORE_KEY); localStorage.removeItem('theme'); } catch (e) {}
      location.reload();
    },
  };
})();
