// PackCheck demo controls: the "demo mode" banner and the virtual backpack drawer.
(function () {
  const demo = window.packcheckDemo;
  const isQuickcheck = document.body.dataset.demoPage === 'quickcheck';
  const REPO = 'https://github.com/Reptile1234526/PackCheck';

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  const banner = document.createElement('div');
  banner.className = 'demo-banner';
  banner.innerHTML = `
    <div class="demo-banner-text">
      <span class="demo-tag">DEMO</span>
      No Raspberry Pi or RFID reader here. Scans are simulated in your browser.
    </div>
    <div class="demo-banner-actions">
      ${isQuickcheck
        ? '<a class="demo-btn" href="./">&larr; Full app</a>'
        : '<button class="demo-btn demo-btn-main" type="button" id="demoBagBtn">Backpack</button>'}
      <button class="demo-btn" type="button" id="demoResetBtn">Reset</button>
      <a class="demo-btn" href="${REPO}" target="_blank" rel="noopener">Code</a>
    </div>`;
  document.body.prepend(banner);
  document.getElementById('demoResetBtn').addEventListener('click', () => {
    if (confirm('Reset the demo to its sample items, profiles and history?')) demo.reset();
  });

  if (isQuickcheck) return;

  const sheet = document.createElement('div');
  sheet.className = 'demo-sheet-overlay';
  sheet.innerHTML = `
    <div class="demo-sheet" role="dialog" aria-label="Virtual backpack">
      <div class="demo-sheet-head">
        <div>
          <div class="demo-sheet-title">Virtual backpack</div>
          <div class="demo-sheet-sub">Stands in for the real bag. Take items out or put them back,
            then press SCAN BAG to see what the reader would report.</div>
        </div>
        <button class="demo-close" type="button" aria-label="Close">&times;</button>
      </div>
      <div id="demoBagList"></div>
      <button class="demo-done" type="button">DONE</button>
    </div>`;
  document.body.appendChild(sheet);

  const open = () => { render(); sheet.classList.add('active'); };
  const close = () => sheet.classList.remove('active');
  document.getElementById('demoBagBtn').addEventListener('click', open);
  sheet.querySelector('.demo-close').addEventListener('click', close);
  sheet.querySelector('.demo-done').addEventListener('click', close);
  sheet.addEventListener('click', e => { if (e.target === sheet) close(); });

  function render() {
    const s = demo.getState();
    const names = {};
    Object.entries(s.config.items).forEach(([n, epc]) => { names[epc] = n; });
    const inBag = s.tags.filter(epc => s.bag[epc]).length;
    document.getElementById('demoBagBtn').textContent = `Backpack (${inBag})`;
    document.getElementById('demoBagList').innerHTML = s.tags.map(epc => {
      const on = !!s.bag[epc];
      const name = names[epc];
      return `
      <label class="demo-bag-row ${on ? 'in' : 'out'}">
        <input type="checkbox" data-epc="${epc}" ${on ? 'checked' : ''}>
        <span class="demo-switch"></span>
        <span class="demo-bag-info">
          <span class="demo-bag-name">${name ? esc(name) : 'Unregistered tag'}</span>
          <span class="demo-bag-epc">${epc}${name ? '' : ' &middot; try + ADD ITEM'}</span>
        </span>
        <span class="demo-bag-state">${on ? 'IN BAG' : 'OUT'}</span>
      </label>`;
    }).join('');
    document.querySelectorAll('#demoBagList input').forEach(cb => {
      cb.addEventListener('change', () => demo.setInBag(cb.dataset.epc, cb.checked));
    });
  }

  window.addEventListener('packcheck-demo-change', render);
  render();
})();
