# PackCheck

RFID backpack checker — scans the UHF RFID tags on books/items in your backpack and tells you what's missing before you leave home.

## Hardware
- Raspberry Pi 3 Model B
- JENCE J4210u UHF RFID reader (USB serial)

## Tech
- **Python** — reader communication, tag checking, and a Flask web server
- **HTML / CSS / JavaScript** — the web interface (embedded in `app.py`)
- **CadQuery & Fusion 360 (Python)** — scripts used to design the 3D-printed case

## Files
- `app.py` — Flask web app (serves the UI and API)
- `reader.py` — J4210u reader interface
- `checker.py` — compares scanned tags to the expected item list
- `config.json` — serial port, baud rate, power, scan duration, items
- `case/` — 3D-printable enclosure (STEP / 3MF files) and the scripts that generate it

## Setup
```bash
pip install -r requirements.txt
python app.py
```
Then open `http://<pi-ip>:5000` in a browser.
