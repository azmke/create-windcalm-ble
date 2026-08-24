"""Decode a Tuya BLE capture from an Android HCI snoop log.

This script parses a ``btsnoop_hci.log`` (Android Bluetooth HCI snoop log),
extracts the Tuya BLE protocol packets (writes to characteristic 2B11 and
notifications from 2B10), reassembles the outer subpacket framing, decrypts
the AES-128-CBC frames using the device keys, and prints a readable analysis
of every protocol message.

Usage::

    python3 tools/decode_btsnoop.py [path-to-btsnoop.log]

The device keys are read from the ``.env`` file (WIND_LOCAL_KEY,
WIND_DEVICE_ID, WIND_UUID).
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

# Add project root to path so the package can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from create_windcalm_ble.config import load_config  # noqa: E402
from create_windcalm_ble.crypto import (  # noqa: E402
    SECURITY_FLAG_LOGIN,
    SECURITY_FLAG_SESSION,
    crc16,
    decrypt_cbc,
    derive_login_key,
    derive_session_key,
)
from create_windcalm_ble.device import (  # noqa: E402
    CMD_DEVICE_INFO,
    CMD_DEVICE_STATUS,
    CMD_DP_REPORT,
    CMD_PAIR,
    CMD_SEND_DPS,
    CMD_TIME1_REQ,
    CMD_TIME2_REQ,
    _pack_varint,
    _unpack_varint,
)

# ATT opcodes.
ATT_WRITE_CMD = 0x52
ATT_WRITE_REQ = 0x12
ATT_NOTIFY = 0x1B
ATT_INDICATE = 0x1D

# GATT handles observed in the capture (from the service discovery).
HANDLE_WRITE = 0x000E  # characteristic 2B11
HANDLE_NOTIFY = 0x0010  # characteristic 2B10

CMD_NAMES = {
    CMD_DEVICE_INFO: "DEVICE_INFO (0x0000)",
    CMD_PAIR: "PAIR (0x0001)",
    CMD_SEND_DPS: "SEND_DPS (0x0002)",
    CMD_DEVICE_STATUS: "DEVICE_STATUS (0x0003)",
    CMD_DP_REPORT: "DP_REPORT (0x8001)",
    CMD_TIME1_REQ: "TIME1_REQ (0x8011)",
    CMD_TIME2_REQ: "TIME2_REQ (0x8012)",
}

DP_NAMES = {
    20: "switch_led",
    21: "work_mode",
    23: "temp_value",
    25: "scene_data",
    60: "fan_switch",
    62: "fan_speed",
    63: "fan_direction",
    64: "countdown_left_fan",
}


def parse_btsnoop(path: str) -> list:
    """Parse a btsnoop file into a list of (flags, payload) tuples."""
    packets = []
    with open(path, "rb") as f:
        header = f.read(16)
        if header[:8] != b"btsnoop\x00":
            raise ValueError("Not a btsnoop file")
        while True:
            rec = f.read(24)
            if len(rec) < 24:
                break
            orig_len, inc_len, flags, drops, ts = struct.unpack(">IIIIq", rec)
            payload = f.read(inc_len)
            packets.append((flags, payload))
    return packets


def extract_att_pdus(packets: list) -> list:
    """Extract ATT PDUs from HCI ACL packets.

    Returns a list of (direction, handle, att_bytes) tuples where
    direction is 'tx' (phone -> device) or 'rx' (device -> phone).
    """
    pdus = []
    for flags, payload in packets:
        if not payload or payload[0] != 0x02:
            continue
        # HCI ACL header: type(1) + handle(2) + len(2)
        acl_len = struct.unpack("<H", payload[3:5])[0]
        data = payload[5 : 5 + acl_len]
        if len(data) < 4:
            continue
        l2cap_len = struct.unpack("<H", data[0:2])[0]
        cid = struct.unpack("<H", data[2:4])[0]
        if cid != 0x0004:  # ATT channel
            continue
        att = data[4 : 4 + l2cap_len]
        if not att:
            continue
        # btsnoop flags: bit 0 = direction (0 = sent, 1 = received)
        direction = "rx" if (flags & 0x01) else "tx"
        pdus.append((direction, att))
    return pdus


class TuyaDecoder:
    """Decrypt and decode Tuya BLE frames from a capture."""

    def __init__(self, local_key: str) -> None:
        self._login_key = derive_login_key(local_key)
        self._local_key_prefix = local_key[:6].encode("ascii")
        self._session_key = None
        self._srand = None
        self._tx_counter = 0
        self._rx_counter = 0
        self._input_buffer = bytearray()
        self._input_expected_packet_num = 0
        self._input_expected_length = 0

    def _reset_input(self) -> None:
        self._input_buffer = bytearray()
        self._input_expected_packet_num = 0
        self._input_expected_length = 0

    def feed(self, direction: str, data: bytes) -> None:
        """Feed one ATT write/notification payload into the decoder."""
        try:
            packet_num, pos = _unpack_varint(data, 0)
        except Exception:
            print(f"  [{direction}] Cannot parse subpacket: {data.hex()}")
            return

        if packet_num < self._input_expected_packet_num:
            print(f"  [{direction}] Unexpected subpacket {packet_num}")
            self._reset_input()
            return
        if packet_num > self._input_expected_packet_num:
            print(f"  [{direction}] Missing subpacket {self._input_expected_packet_num}")
            self._reset_input()
            return

        if packet_num == 0:
            self._input_buffer = bytearray()
            self._input_expected_length, pos = _unpack_varint(data, pos)
            version_byte = data[pos]
            pos += 1
            self._input_expected_packet_num = 1
            print(
                f"  [{direction}] subpacket 0: total_len={self._input_expected_length} "
                f"version=0x{version_byte:02x}"
            )
        else:
            self._input_expected_packet_num += 1

        self._input_buffer += data[pos:]

        if len(self._input_buffer) > self._input_expected_length:
            print(f"  [{direction}] Frame too long")
            self._reset_input()
            return
        if len(self._input_buffer) == self._input_expected_length:
            frame = bytes(self._input_buffer)
            self._reset_input()
            self._parse_frame(direction, frame)

    def _parse_frame(self, direction: str, frame: bytes) -> None:
        """Decrypt and decode one complete encrypted frame."""
        if len(frame) < 1 + 16 + 16:
            print(f"  [{direction}] Frame too short: {frame.hex()}")
            return

        security_flag = frame[0]
        iv = frame[1:17]
        ciphertext = frame[17:]

        if security_flag == SECURITY_FLAG_LOGIN:
            key = self._login_key
            key_name = "login_key"
        elif security_flag == SECURITY_FLAG_SESSION:
            key = self._session_key
            key_name = "session_key"
        else:
            print(f"  [{direction}] Unknown security flag 0x{security_flag:02x}")
            return

        if key is None:
            print(f"  [{direction}] No {key_name} available yet")
            return

        inner = decrypt_cbc(key, iv, ciphertext)

        if len(inner) < 12:
            print(f"  [{direction}] Inner frame too short")
            return
        seq, ack, code, length = struct.unpack(">IIHH", inner[:12])

        data_end = 12 + length
        if len(inner) < data_end + 2:
            print(f"  [{direction}] Inner frame truncated")
            return
        calc_crc = crc16(inner[:data_end])
        (data_crc,) = struct.unpack(">H", inner[data_end : data_end + 2])
        crc_ok = calc_crc == data_crc

        payload = inner[12:data_end]
        cmd_name = CMD_NAMES.get(code, f"UNKNOWN (0x{code:04x})")

        print(
            f"  [{direction}] seq={seq} ack={ack} cmd={cmd_name} "
            f"len={length} crc={'OK' if crc_ok else 'FAIL'}"
        )

        if code == CMD_DEVICE_INFO:
            self._handle_device_info(payload)
        elif code == CMD_PAIR:
            self._handle_pair(payload)
        elif code == CMD_DP_REPORT:
            if ack != 0:
                # This is an acknowledgement of a DP report we received.
                print(f"    (ACK) payload={payload.hex()}")
            else:
                self._handle_dp_report(payload)
        elif code == CMD_SEND_DPS:
            self._handle_dp_report(payload)
        elif code == CMD_DEVICE_STATUS:
            print(f"    result={payload.hex()}")
        elif code in (CMD_TIME1_REQ, CMD_TIME2_REQ):
            print(f"    payload={payload.hex()}")
            if payload:
                print(f"    payload as int: {int.from_bytes(payload, 'big')}")
                print(f"    payload as str: {payload.decode('utf-8', errors='replace')!r}")
        else:
            print(f"    payload={payload.hex()}")

    def _handle_device_info(self, payload: bytes) -> None:
        if len(payload) < 46:
            print(f"    device-info too short: {payload.hex()}")
            return
        device_version = f"{payload[0]}.{payload[1]}"
        protocol_version = f"{payload[2]}.{payload[3]}"
        flags = payload[4]
        is_bound = payload[5] != 0
        srand = payload[6:12]
        auth_key = payload[14:46]
        print(
            f"    device_version={device_version} protocol={protocol_version} "
            f"flags={flags} bound={is_bound}"
        )
        print(f"    srand={srand.hex()} auth_key={auth_key.hex()}")
        self._srand = srand
        self._session_key = derive_session_key(self._local_key_prefix, srand)
        print(f"    session_key={self._session_key.hex()}")

    def _handle_pair(self, payload: bytes) -> None:
        if len(payload) == 1:
            result = payload[0]
            result_str = {0: "OK", 1: "UUID mismatch", 2: "already paired"}.get(
                result, f"unknown ({result})"
            )
            print(f"    pair result: {result_str}")
        else:
            print(f"    pair payload: {payload.hex()}")

    def _handle_dp_report(self, payload: bytes) -> None:
        pos = 0
        while pos + 3 <= len(payload):
            dp_id = payload[pos]
            dp_type = payload[pos + 1]
            dp_len = payload[pos + 2]
            pos += 3
            raw = payload[pos : pos + dp_len]
            pos += dp_len
            name = DP_NAMES.get(dp_id, f"dp_{dp_id}")
            if dp_type == 1:  # bool
                value = bool(raw[0]) if raw else False
            elif dp_type == 2:  # value
                value = int.from_bytes(raw, "big", signed=True)
            elif dp_type == 4:  # enum
                value = int.from_bytes(raw, "big")
            elif dp_type == 3:  # string
                value = raw.decode("utf-8", errors="replace")
            else:
                value = raw.hex()
            print(f"    DP {dp_id} ({name}) type={dp_type} value={value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="btsnoop_hci.log",
        help="Path to the btsnoop file (default: btsnoop_hci.log)",
    )
    args = parser.parse_args()

    config = load_config()
    print(f"Device: {config.name} ({config.mac})")
    print(f"Device ID: {config.device_id}")
    print(f"UUID: {config.uuid}")
    print()

    packets = parse_btsnoop(args.path)
    print(f"Parsed {len(packets)} HCI packets")
    pdus = extract_att_pdus(packets)
    print(f"Extracted {len(pdus)} ATT PDUs")
    print()

    decoder = TuyaDecoder(config.local_key)

    # Only process writes to 2B11 and notifications from 2B10.
    for direction, att in pdus:
        op = att[0]
        if op == ATT_WRITE_CMD:
            handle = struct.unpack("<H", att[1:3])[0]
            if handle == HANDLE_WRITE:
                print(f"WRITE 2B11 ({direction}):")
                decoder.feed(direction, att[3:])
        elif op == ATT_WRITE_REQ:
            handle = struct.unpack("<H", att[1:3])[0]
            if handle == HANDLE_WRITE:
                print(f"WRITE-REQ 2B11 ({direction}):")
                decoder.feed(direction, att[3:])
        elif op == ATT_NOTIFY:
            handle = struct.unpack("<H", att[1:3])[0]
            if handle == HANDLE_NOTIFY:
                print(f"NOTIFY 2B10 ({direction}):")
                decoder.feed(direction, att[3:])
        elif op == ATT_INDICATE:
            handle = struct.unpack("<H", att[1:3])[0]
            if handle == HANDLE_NOTIFY:
                print(f"INDICATE 2B10 ({direction}):")
                decoder.feed(direction, att[3:])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())