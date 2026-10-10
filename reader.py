"""
J4210u UHF RFID Reader — Pure Python serial driver.

Protocol: CRC-16 framed commands over 57600 baud 8N1.
Frame format: [Length] [Address] [Command] [Params...] [CRC_LSB] [CRC_MSB]
"""

import serial
import time
from dataclasses import dataclass


# --- CRC-16 (preset 0xFFFF, polynomial 0x8408) ---

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


# --- Data classes ---

@dataclass
class TagRead:
    epc: str        # hex string, e.g. "E200001234567890ABCDEF00"
    rssi: int       # signal strength (signed)
    count: int      # number of times read in this scan
    antenna: int    # antenna number


@dataclass
class ReaderInfo:
    version_major: int
    version_minor: int
    reader_type: int
    protocol: int
    power: int          # dBm
    scan_time: int      # units of 100ms
    antenna: int
    beep_on: bool


# --- Commands ---

CMD_GET_SETTINGS   = 0x21
CMD_SET_REGION     = 0x22
CMD_SET_SCAN_TIME  = 0x25
CMD_SET_BAUD       = 0x28
CMD_SET_POWER      = 0x2F
CMD_SET_BEEP       = 0x40
CMD_GET_SERIAL     = 0x4C
CMD_INVENTORY      = 0x18
CMD_GET_BUFFER     = 0x72
CMD_CLEAR_BUFFER   = 0x73
CMD_GET_TAG_COUNT  = 0x74


class J4210Reader:
    """Driver for the JENCE J4210u UHF RFID reader module."""

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 57600,
                 address: int = 0x00, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.ser = None

    def open(self):
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        time.sleep(0.1)  # let the module boot

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    # --- Low-level protocol ---

    def _build_frame(self, command: int, params: bytes = b"") -> bytes:
        """Build a protocol frame with length, address, command, params, and CRC."""
        # Length = number of bytes after the length byte (addr + cmd + params + 2 CRC)
        length = 1 + 1 + len(params) + 2
        frame_no_crc = bytes([length, self.address, command]) + params
        crc = crc16(frame_no_crc)
        return frame_no_crc + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def _send(self, command: int, params: bytes = b"", timeout: float = None) -> bytes:
        """Send a command and return the raw response bytes."""
        frame = self._build_frame(command, params)
        old_timeout = self.ser.timeout
        if timeout is not None:
            self.ser.timeout = timeout
        try:
            self.ser.reset_input_buffer()
            self.ser.write(frame)
            self.ser.flush()
            # Read response: first byte is length
            header = self.ser.read(1)
            if not header:
                raise TimeoutError("No response from reader")
            resp_len = header[0]
            rest = self.ser.read(resp_len)
            if len(rest) < resp_len:
                raise TimeoutError(f"Incomplete response: expected {resp_len} bytes, got {len(rest)}")
            response = header + rest
        finally:
            self.ser.timeout = old_timeout
        # Validate CRC
        payload = response[:-2]
        expected_crc = response[-2] | (response[-1] << 8)
        actual_crc = crc16(payload)
        if expected_crc != actual_crc:
            raise ValueError(f"CRC mismatch: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}")
        return response

    # --- High-level commands ---

    def get_settings(self) -> ReaderInfo:
        """Read current reader configuration."""
        resp = self._send(CMD_GET_SETTINGS)
        if resp[3] != 0x00:
            raise RuntimeError(f"GetSettings failed with status 0x{resp[3]:02X}")
        return ReaderInfo(
            version_major=resp[4],
            version_minor=resp[5],
            reader_type=resp[6],
            protocol=resp[7],
            power=resp[10],
            scan_time=resp[11],
            antenna=resp[12],
            beep_on=bool(resp[13]),
        )

    def set_beep(self, on: bool):
        """Enable or disable the reader's buzzer."""
        resp = self._send(CMD_SET_BEEP, bytes([0x01 if on else 0x00]))
        if resp[3] != 0x00:
            raise RuntimeError(f"SetBeep failed with status 0x{resp[3]:02X}")

    def set_power(self, power_dbm: int):
        """Set RF transmit power in dBm (typically 0-30)."""
        resp = self._send(CMD_SET_POWER, bytes([power_dbm]))
        if resp[3] != 0x00:
            raise RuntimeError(f"SetPower failed with status 0x{resp[3]:02X}")

    def set_scan_time(self, time_100ms: int):
        """Set inventory scan time in units of 100ms."""
        resp = self._send(CMD_SET_SCAN_TIME, bytes([time_100ms]))
        if resp[3] != 0x00:
            raise RuntimeError(f"SetScanTime failed with status 0x{resp[3]:02X}")

    def clear_buffer(self):
        """Clear the tag inventory buffer."""
        resp = self._send(CMD_CLEAR_BUFFER)
        if resp[3] != 0x00:
            raise RuntimeError(f"ClearBuffer failed with status 0x{resp[3]:02X}")

    def get_tag_count(self) -> int:
        """Get the number of tags currently in the inventory buffer."""
        resp = self._send(CMD_GET_TAG_COUNT)
        if resp[3] != 0x00:
            raise RuntimeError(f"GetTagCount failed with status 0x{resp[3]:02X}")
        return resp[4]

    def inventory(self, q: int = 4, session: int = 0, scan_time_100ms: int = 10) -> list[TagRead]:
        """
        Run an inventory scan and return all tags found.

        Args:
            q: Anti-collision Q value (0-15). Higher = more tags expected.
            session: Session number (0-3).
            scan_time_100ms: How long to scan, in units of 100ms (default 1 second).
        """
        self.clear_buffer()

        # Build inventory command params: Q, session, no filter, scan time
        params = bytes([q, session, 0x00, scan_time_100ms])
        # Inventory takes scan_time to complete, so extend the serial timeout
        resp_timeout = scan_time_100ms * 0.1 + 3.0
        self._send(CMD_INVENTORY, params, timeout=resp_timeout)

        # Read results from buffer
        return self._read_buffer()

    def _read_buffer(self) -> list[TagRead]:
        """Read all tags from the inventory buffer."""
        tags = []
        while True:
            resp = self._send(CMD_GET_BUFFER)
            status = resp[3]
            # Status 0x00 = more data follows, 0x01 = last chunk (still has data)
            if status not in (0x00, 0x01):
                raise RuntimeError(f"GetBuffer failed with status 0x{status:02X}")

            tag_count = resp[4]
            offset = 5
            for _ in range(tag_count):
                if offset >= len(resp) - 2:
                    break
                antenna = resp[offset]
                offset += 1
                epc_len = resp[offset]
                offset += 1
                epc_bytes = resp[offset:offset + epc_len]
                epc = epc_bytes.hex().upper()
                offset += epc_len
                rssi = resp[offset]
                if rssi > 127:
                    rssi -= 256  # signed
                offset += 1
                count = resp[offset]
                offset += 1
                tags.append(TagRead(epc=epc, rssi=rssi, count=count, antenna=antenna))

            if status == 0x01:
                # Last chunk — we're done
                break

        return tags

    def scan(self, duration_sec: float = 1.0, power_dbm: int = None) -> list[TagRead]:
        """
        Convenience method: optionally set power, then run inventory.

        Args:
            duration_sec: How long to scan in seconds.
            power_dbm: If set, adjust RF power before scanning.
        """
        self.set_beep(False)
        if power_dbm is not None:
            self.set_power(power_dbm)
        scan_units = max(1, int(duration_sec * 10))
        return self.inventory(scan_time_100ms=scan_units)
