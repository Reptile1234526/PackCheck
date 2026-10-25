# PackCheck Setup Guide

This walks through everything from a blank SD card to a working PackCheck: flashing the Raspberry Pi, connecting the JENCE J4210u reader, installing the app, registering your items, and making it start on boot.

## 1. What you need

| Part | Notes |
|------|-------|
| Raspberry Pi 3 Model B | Any Pi with USB and Wi-Fi works (3B+, 4, 5, Zero 2 W with an OTG adapter) |
| microSD card, 8 GB+ | Class 10 or better |
| 5 V / 2.5 A micro-USB power supply | The reader is powered from the Pi's USB, so a weak supply causes dropouts |
| JENCE J4210u UHF RFID reader | Connects over USB and shows up as a serial port |
| UHF RFID tags (EPC Gen2, 860–960 MHz) | Sticker or card tags, one per item you want to track |
| Another computer | To flash the SD card and open the web UI |
| 3D-printed case (optional) | Print files are in `case/` (see section 11) |

## 2. Flash Raspberry Pi OS

1. Install **Raspberry Pi Imager** from <https://www.raspberrypi.com/software/> on your computer.
2. Choose:
   - **Device:** Raspberry Pi 3
   - **OS:** Raspberry Pi OS Lite (64-bit). The desktop version works too, but you don't need it.
   - **Storage:** your microSD card
3. Click **Next → Edit settings** and set:
   - **Hostname:** `packcheck` (you'll reach it at `packcheck.local`)
   - **Username / password:** e.g. `pi` / something you'll remember
   - **Wireless LAN:** your Wi-Fi name, password and country
   - **Locale:** your time zone (this matters: auto-scan times and day schedules use the Pi's clock)
   - **Services tab:** enable **SSH** with password authentication
4. Write the card, put it in the Pi, and power it on. The first boot takes a couple of minutes.

## 3. Connect to the Pi

From your computer:

```bash
ssh pi@packcheck.local
```

If `packcheck.local` doesn't resolve, find the Pi's IP address in your router's device list and use `ssh pi@<pi-ip>` instead.

Update the system and install the tools PackCheck needs:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-pip
```

## 4. Connect the JENCE J4210u reader

1. Plug the J4210u into one of the Pi's USB ports (and attach its antenna, if yours has a separate one; never power a UHF reader without its antenna).
2. Check that Linux sees it:

   ```bash
   ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
   dmesg | tail -n 20
   ```

   You should see something like `/dev/ttyUSB0` and a line in `dmesg` saying a USB-serial converter was attached. Note which device it is; PackCheck defaults to `/dev/ttyUSB0`.

3. Give your user permission to use serial ports, then log out and back in so it takes effect:

   ```bash
   sudo usermod -aG dialout $USER
   exit
   ssh pi@packcheck.local
   ```

   Confirm with `groups`; the list should include `dialout`.

4. **(Optional) Give the reader a stable name.** If you ever plug in another USB-serial device, the reader might move to `/dev/ttyUSB1`. A udev rule pins it to `/dev/packcheck-reader`:

   ```bash
   udevadm info -a -n /dev/ttyUSB0 | grep -m2 -E 'idVendor|idProduct'
   ```

   Use the two values it prints in this rule (replace `xxxx`/`yyyy`):

   ```bash
   echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="xxxx", ATTRS{idProduct}=="yyyy", SYMLINK+="packcheck-reader", MODE="0660", GROUP="dialout"' \
     | sudo tee /etc/udev/rules.d/99-packcheck.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ls -l /dev/packcheck-reader
   ```

   Then set `"port": "/dev/packcheck-reader"` in `config.json` (step 6).

The reader talks at **57600 baud, 8N1**, which is its factory default and what `config.json` uses. You don't need to install any JENCE software; `reader.py` speaks the reader's serial protocol directly.

## 5. Install PackCheck

```bash
cd ~
git clone https://github.com/Reptile1234526/PackCheck.git
cd PackCheck
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A virtual environment is required on current Raspberry Pi OS, which blocks `pip install` into the system Python. Run `source ~/PackCheck/.venv/bin/activate` again whenever you open a new SSH session to use the commands below.

## 6. Configure and test the reader

Run the setup wizard. It asks for the serial port, RF power and scan duration, saves them to `config.json`, and then talks to the reader:

```bash
python checker.py setup
```

A good result looks like:

```
Testing reader connection...
  Connected! Firmware: vX.Y
  Power: 20 dBm, Antenna: ...
```

Then put a tag near the antenna and scan:

```bash
python checker.py scan
```

You should see the tag's EPC (a long hex string) with its RSSI (signal strength). If you don't, see **Troubleshooting** below.

### Settings in `config.json`

| Key | Default | What it does |
|-----|---------|--------------|
| `port` | `/dev/ttyUSB0` | Serial device of the reader |
| `baudrate` | `57600` | Reader baud rate; leave as is |
| `power_dbm` | `20` | RF power. Higher reads farther (up to about 30) but may pick up tags outside the bag |
| `scan_duration` | `2.0` | Seconds per scan. Longer is more reliable with many tags |
| `items` | `{}` | Registered items, `name → EPC` (filled in by the app) |

The web app adds more keys itself (`profiles`, `active_profile`, `ntfy_topic`, `auto_scan_times`, `day_schedule`, `theme`); set those from the Settings screen rather than by hand.

**Tuning tip:** start at 20 dBm with the reader where it will live (e.g. by the door). Put the full backpack in its usual spot and raise `power_dbm` or `scan_duration` until every item reads consistently, then check that items lying elsewhere in the room *don't* read.

## 7. Register your items

Stick one tag on each item (inside a book cover, on a laptop sleeve, on a pencil case). Then either:

- **Command line:** for each item, run `python checker.py add math-textbook`, hold only that item's tag near the reader, and press Enter. If several tags are seen, it lets you pick one.
- **Web UI:** start the app (next step), use the scan/add screen to scan a single tag, and give it a name.

Check what's registered with `python checker.py list`, and do a test run with `python checker.py check`.

## 8. Run the web app

```bash
python app.py
```

Open `http://packcheck.local:5000` (or `http://<pi-ip>:5000`) on your phone or computer. From there you can run checks, manage items and profiles (e.g. different item lists per day), see scan history, and change settings.

Useful extras:

- **Add to home screen:** the app is a PWA, so on your phone use the browser's "Add to Home Screen" for an app-like icon.
- **Quick check page:** `http://packcheck.local:5000/quickcheck` scans as soon as it opens.
- **iOS Shortcuts / scripts:** `http://packcheck.local:5000/api/quickcheck` returns plain text like `MISSING: calculator (4/5 found)`.
- **Phone notifications:** in Settings, set an **ntfy topic** (pick something unique and hard to guess), install the ntfy app (<https://ntfy.sh>) on your phone, and subscribe to the same topic. Then add **auto-scan times** (e.g. `07:30`) and PackCheck will scan at those times and notify you what's missing.

Stop the app with `Ctrl+C`.

## 9. Start automatically on boot

Create a systemd service so PackCheck runs whenever the Pi is powered on. Replace `pi` with your username if it's different:

```bash
sudo tee /etc/systemd/system/packcheck.service > /dev/null <<'EOF'
[Unit]
Description=PackCheck RFID backpack checker
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/PackCheck
ExecStart=/home/pi/PackCheck/.venv/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now packcheck
```

Check it with:

```bash
systemctl status packcheck
journalctl -u packcheck -f      # live logs, Ctrl+C to exit
```

Only one program can use the reader at a time, so stop the service (`sudo systemctl stop packcheck`) before using `checker.py`, and start it again afterwards.

## 10. Updating

```bash
cd ~/PackCheck
sudo systemctl stop packcheck
git stash          # keeps your registered items in config.json safe
git pull
git stash pop
source .venv/bin/activate && pip install -r requirements.txt
sudo systemctl start packcheck
```

`config.json` holds your items and settings, and `history.json` holds scan history. Back them up if you reinstall.

## 11. The case (optional)

The `case/` folder has the enclosure, designed in Fusion 360:

- `case/PackCheck/PackCheck (Printable V1).step` and `PackCheck.3mf`: the printable model
- `case/PackCheck/PackChecktop.step` / `PackCheckbottom.step`: top and bottom halves
- `case/generate_case.py`, `case/CaseDesign/`: scripts that generate the design

Open the `.3mf` or `.step` in your slicer (PrusaSlicer, Cura, Bambu Studio). PLA or PETG is fine. Avoid metal-filled filaments and don't mount the reader against metal, since both block UHF signals.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Permission denied: '/dev/ttyUSB0'` | You're not in `dialout` yet. Run step 4.3 and log out and back in. |
| `could not open port /dev/ttyUSB0: No such file` | The reader is on a different port. Run `ls /dev/ttyUSB* /dev/ttyACM*` and update `port` in `config.json`, or use the udev rule in step 4.4. |
| `No response from reader` / `TimeoutError` | Check the USB cable and power supply, and that `baudrate` is `57600`. Unplug and replug the reader. Make sure the service isn't already using the port. |
| `Device or resource busy` | Another program has the port open, usually the `packcheck` service. Stop it first. |
| `CRC mismatch` | Electrical noise or a bad cable. Try another USB cable or port, or a stronger power supply. |
| Tags not found, or only some | Raise `power_dbm` and/or `scan_duration`. Keep tags off metal and away from water bottles, which absorb UHF. Check the tags are UHF (860–960 MHz), not 13.56 MHz NFC. |
| Items outside the bag show as found | Lower `power_dbm` or move the reader so it only "sees" the bag's spot. |
| Can't open `packcheck.local:5000` | Use the Pi's IP instead. Make sure your phone is on the same Wi-Fi and the app is running (`systemctl status packcheck`). |
| Auto-scans happen at the wrong time | Set the Pi's time zone: `sudo raspi-config` → Localisation Options → Timezone. |
| `pip install` says "externally-managed-environment" | You're outside the virtual environment. Run `source ~/PackCheck/.venv/bin/activate`. |
