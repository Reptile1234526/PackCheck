# PackCheck

RFID backpack checker: scans the UHF RFID tags on books/items in your backpack and tells you what's missing before you leave home.

**[Try the live demo](https://reptile1234526.github.io/PackCheck/)** — the real web interface running in your browser with a simulated reader and sample data. No Raspberry Pi or RFID hardware needed. Open the **Backpack** button to take items out of the virtual bag, then press **SCAN BAG**.

## Hardware
- Raspberry Pi 3 Model B
- JENCE J4210u UHF RFID reader (USB serial)

## Tech
- **Python** — reader communication, tag checking, and a Flask web server
- **HTML / CSS / JavaScript** — the web interface (embedded in `app.py`)
- **Fusion 360** — Used to design the 3D-printed case

## Files
- `app.py` — Flask web app (serves the UI and API)
- `reader.py` — J4210u reader interface
- `checker.py` — compares scanned tags to the expected item list
- `config.json` — serial port, baud rate, power, scan duration, items
- `demo/` — builds the browser-only demo into `docs/` (`python demo/build.py`); `docs/` is what GitHub Pages serves
- `case/` — 3D-printable enclosure (STEP / 3MF files) and the scripts that generate it

## Setup
For the full walkthrough (flashing the Pi, connecting the J4210u, registering items, running on boot, troubleshooting), see **[SETUP.md](SETUP.md)**.

Quick start:
```bash
pip install -r requirements.txt
python app.py
```
Then open `http://<pi-ip>:5000` in a browser.
