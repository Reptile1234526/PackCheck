# PackCheck

RFID backpack checker — scans the UHF RFID tags on books/items in your backpack and tells you what's missing before you leave home.

## Hardware
- Raspberry Pi 3 Model B
- JENCE J4210u UHF RFID reader (USB serial)

## Files
- `app.py` — main app
- `reader.py` — J4210u reader interface
- `checker.py` — compares scanned tags to the expected item list
- `config.json` — serial port, baud rate, power, scan duration, items
- `case/` — 3D-printable enclosure (STEP / 3MF files)

## Setup
```bash
pip install -r requirements.txt
python app.py
```
