#!/usr/bin/env python3
"""
Backpack RFID Checker — make sure you never forget anything.

Usage:
    python checker.py scan              Scan and show all tags in range
    python checker.py add <name>        Scan a single tag and register it as an item
    python checker.py remove <name>     Remove a registered item
    python checker.py list              Show all registered items
    python checker.py check             Scan and report missing items
    python checker.py check --loop      Continuously check (useful mounted by the door)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from reader import J4210Reader

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "port": "/dev/ttyUSB0",
    "baudrate": 57600,
    "power_dbm": 20,
    "scan_duration": 2.0,
    "items": {}
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_reader(config: dict) -> J4210Reader:
    return J4210Reader(
        port=config["port"],
        baudrate=config["baudrate"],
    )


def cmd_scan(args, config):
    """Scan and display all tags found."""
    with get_reader(config) as reader:
        print(f"Scanning for {config['scan_duration']}s at {config['power_dbm']} dBm...")
        tags = reader.scan(
            duration_sec=config["scan_duration"],
            power_dbm=config["power_dbm"],
        )

    if not tags:
        print("No tags found.")
        return

    # Check which tags are registered
    known = {v: k for k, v in config["items"].items()}

    print(f"\nFound {len(tags)} tag(s):\n")
    print(f"  {'EPC':<30} {'RSSI':>5}  {'Reads':>5}  {'Item'}")
    print(f"  {'-'*30} {'-'*5}  {'-'*5}  {'-'*15}")
    for tag in tags:
        name = known.get(tag.epc, "—")
        print(f"  {tag.epc:<30} {tag.rssi:>5}  {tag.count:>5}  {name}")


def cmd_add(args, config):
    """Register a new item by scanning its tag."""
    name = args.name
    if name in config["items"]:
        print(f"Item '{name}' already registered (EPC: {config['items'][name]}).")
        print("Remove it first if you want to re-register.")
        return

    print(f"Place the tag for '{name}' near the reader and press Enter...")
    input()

    with get_reader(config) as reader:
        print("Scanning...")
        tags = reader.scan(
            duration_sec=config["scan_duration"],
            power_dbm=config["power_dbm"],
        )

    if not tags:
        print("No tags detected. Make sure the tag is close to the antenna.")
        return

    if len(tags) > 1:
        print(f"Multiple tags detected ({len(tags)}). Isolate the one you want:")
        for i, tag in enumerate(tags):
            print(f"  [{i+1}] {tag.epc}  (RSSI: {tag.rssi})")
        choice = input(f"Pick 1-{len(tags)} (or 0 to cancel): ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tags):
            print("Cancelled.")
            return
        selected = tags[int(choice) - 1]
    else:
        selected = tags[0]

    # Check if this EPC is already registered under another name
    for existing_name, existing_epc in config["items"].items():
        if existing_epc == selected.epc:
            print(f"This tag is already registered as '{existing_name}'.")
            return

    config["items"][name] = selected.epc
    save_config(config)
    print(f"Registered '{name}' with EPC: {selected.epc}")


def cmd_remove(args, config):
    """Remove a registered item."""
    name = args.name
    if name not in config["items"]:
        print(f"No item named '{name}' found.")
        return
    epc = config["items"].pop(name)
    save_config(config)
    print(f"Removed '{name}' (was EPC: {epc}).")


def cmd_list(args, config):
    """List all registered items."""
    items = config["items"]
    if not items:
        print("No items registered yet. Use 'add <name>' to register one.")
        return

    print(f"\nRegistered items ({len(items)}):\n")
    print(f"  {'Name':<20} {'EPC'}")
    print(f"  {'-'*20} {'-'*30}")
    for name, epc in items.items():
        print(f"  {name:<20} {epc}")


def cmd_check(args, config):
    """Scan and check for missing items."""
    items = config["items"]
    if not items:
        print("No items registered. Use 'add <name>' to register items first.")
        return

    loop = getattr(args, "loop", False)

    while True:
        with get_reader(config) as reader:
            tags = reader.scan(
                duration_sec=config["scan_duration"],
                power_dbm=config["power_dbm"],
            )

        found_epcs = {tag.epc for tag in tags}
        present = []
        missing = []

        for name, epc in items.items():
            if epc in found_epcs:
                present.append(name)
            else:
                missing.append(name)

        # Clear screen for loop mode
        if loop:
            print("\033[2J\033[H", end="")

        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] Backpack check: {len(present)}/{len(items)} items found\n")

        if missing:
            print("  MISSING:")
            for name in missing:
                print(f"    ✗ {name}")
            print()

        if present:
            print("  FOUND:")
            for name in present:
                print(f"    ✓ {name}")
            print()

        if not missing:
            print("  All items accounted for. You're good to go!")

        if not loop:
            break

        # In loop mode, wait before next scan
        try:
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


def cmd_setup(args, config):
    """Interactive first-time setup."""
    print("=== Backpack RFID Checker Setup ===\n")

    port = input(f"Serial port [{config['port']}]: ").strip()
    if port:
        config["port"] = port

    power = input(f"RF power in dBm [{config['power_dbm']}]: ").strip()
    if power.isdigit():
        config["power_dbm"] = int(power)

    duration = input(f"Scan duration in seconds [{config['scan_duration']}]: ").strip()
    if duration:
        try:
            config["scan_duration"] = float(duration)
        except ValueError:
            pass

    save_config(config)
    print(f"\nConfig saved to {CONFIG_FILE}")

    # Test connection
    print("\nTesting reader connection...")
    try:
        with get_reader(config) as reader:
            info = reader.get_settings()
            print(f"  Connected! Firmware: v{info.version_major}.{info.version_minor}")
            print(f"  Power: {info.power} dBm, Antenna: {info.antenna}")
    except Exception as e:
        print(f"  Could not connect: {e}")
        print("  Check your wiring and port settings.")


def main():
    parser = argparse.ArgumentParser(
        description="Backpack RFID Checker — never forget your stuff."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="Scan and show all nearby tags")

    p_add = sub.add_parser("add", help="Register a new item")
    p_add.add_argument("name", help="Name for this item (e.g. 'math-textbook')")

    p_rm = sub.add_parser("remove", help="Remove a registered item")
    p_rm.add_argument("name", help="Item name to remove")

    sub.add_parser("list", help="List all registered items")

    p_check = sub.add_parser("check", help="Scan and report missing items")
    p_check.add_argument("--loop", action="store_true",
                         help="Continuously check (Ctrl+C to stop)")

    sub.add_parser("setup", help="First-time setup wizard")

    args = parser.parse_args()
    config = load_config()

    commands = {
        "scan": cmd_scan,
        "add": cmd_add,
        "remove": cmd_remove,
        "list": cmd_list,
        "check": cmd_check,
        "setup": cmd_setup,
    }

    if args.command in commands:
        commands[args.command](args, config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
