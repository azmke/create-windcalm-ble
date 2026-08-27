"""WindCalm BLE device client.

This module implements the Tuya BLE V2/V3 protocol handshake and the
datapoint (DP) read/write operations needed to control the fan. It is a
standalone implementation inspired by the ``ha_tuya_ble`` integration but
does not depend on Home Assistant.

Protocol overview
-----------------
The fan exposes a vendor-specific GATT service (``1910``) with a write
characteristic (``2B11``) and a notify characteristic (``2B10``). Application
frames are encrypted with AES-128-CBC and transported in one or more GATT
writes.

The handshake is::

    connect -> subscribe to 2B10
    -> send device-info request (0x0000)
    -> receive device-info reply (contains ``srand``)
    -> derive session key = MD5(login_key || srand)
    -> send pair request (0x0001)
    -> receive pair result
    -> send status request (0x0003) to read current datapoints
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import struct
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from bleak import BleakClient
from bleak.exc import BleakError

from .config import Config
from .crypto import (
    SECURITY_FLAG_LOGIN,
    SECURITY_FLAG_SESSION,
    crc16,
    decrypt_cbc,
    derive_login_key,
    derive_session_key,
    encrypt_cbc,
)
from .models import (
    DataPoint,
    DataPointType,
    DeviceInfo,
    FanDirection,
    FanStatus,
    WorkMode,
)

_LOGGER = logging.getLogger(__name__)

# GATT UUIDs for the Tuya BLE V1 service.
CHARACTERISTIC_WRITE = "00002b11-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_NOTIFY = "00002b10-0000-1000-8000-00805f9b34fb"

# Maximum payload per GATT write (Tuya BLE data MTU).
GATT_MTU = 20

# Command codes (Tuya BLE V2/V3).
CMD_DEVICE_INFO = 0x0000
CMD_PAIR = 0x0001
CMD_SEND_DPS = 0x0002
CMD_DEVICE_STATUS = 0x0003
CMD_DP_REPORT = 0x8001
CMD_TIME1_REQ = 0x8011
CMD_TIME2_REQ = 0x8012

# Datapoint IDs for the WindCalm fan (from device-info.json).
DP_FAN_SWITCH = 60
DP_FAN_SPEED = 62
DP_FAN_DIRECTION = 63
DP_COUNTDOWN = 64
DP_LIGHT_SWITCH = 20
DP_WORK_MODE = 21
DP_LIGHT_TEMPERATURE = 23
# Backwards-compatible name used by versions before 0.2.0.
DP_TEMPERATURE = DP_LIGHT_TEMPERATURE

# Response timeout for a single command.
RESPONSE_TIMEOUT = 10.0


def _pack_varint(value: int) -> bytes:
    """Encode an integer as a little-endian base-128 varint.

    Used for the subpacket number and total frame length in the outer
    Tuya subpacket framing.
    """
    result = bytearray()
    while True:
        curr = value & 0x7F
        value >>= 7
        if value != 0:
            curr |= 0x80
        result.append(curr)
        if value == 0:
            break
    return bytes(result)


def _unpack_varint(data: bytes, start: int) -> tuple:
    """Decode a little-endian base-128 varint from ``data`` at ``start``.

    Returns
    -------
    tuple
        ``(value, next_position)``.
    """
    result = 0
    offset = 0
    while offset < 5:
        pos = start + offset
        if pos >= len(data):
            raise WindCalmProtocolError("Truncated varint")
        curr = data[pos]
        result |= (curr & 0x7F) << (offset * 7)
        offset += 1
        if (curr & 0x80) == 0:
            break
    if offset > 4:
        raise WindCalmProtocolError("Varint too long")
    return result, start + offset


class WindCalmError(Exception):
    """Base error for WindCalm BLE operations."""


class WindCalmProtocolError(WindCalmError):
    """Raised when the device sends an unexpected or malformed frame."""


class WindCalmAuthenticationError(WindCalmError):
    """Raised when the device rejects the supplied Tuya credentials."""


ClientFactory = Callable[[Any, Callable[[BleakClient], None]], Awaitable[BleakClient]]
StatusCallback = Callable[[FanStatus], None]
DisconnectCallback = Callable[[], None]


async def _default_client_factory(
    address_or_ble_device: Any,
    disconnected_callback: Callable[[BleakClient], None],
) -> BleakClient:
    """Create and connect a normal Bleak client."""
    client = BleakClient(
        address_or_ble_device,
        disconnected_callback=disconnected_callback,
    )
    await client.connect()
    return client


class WindCalmDevice:
    """A client for a single WindCalm ceiling fan over BLE.

    The client is an async context manager. Use it as::

        async with WindCalmDevice(config) as fan:
            await fan.connect()
            status = await fan.get_status()
            await fan.set_power(True)
    """

    def __init__(
        self,
        config: Config,
        ble_device: Any = None,
        client_factory: Optional[ClientFactory] = None,
        status_callback: Optional[StatusCallback] = None,
        disconnect_callback: Optional[DisconnectCallback] = None,
    ) -> None:
        self._config = config
        self._ble_device = ble_device
        self._client_factory = client_factory or _default_client_factory
        self._status_callback = status_callback
        self._disconnect_callback = disconnect_callback
        self._client: Optional[BleakClient] = None
        self._login_key: Optional[bytes] = None
        self._session_key: Optional[bytes] = None
        self._srand: Optional[bytes] = None
        self._tx_counter = 1
        # The capture of the official Tuya app shows the phone always sends
        # with protocol version 2 (0x20) even though the device replies with
        # version 3 (0x30). Match the phone's behaviour.
        self._protocol_version = 2
        self._datapoints: Dict[int, DataPoint] = {}
        self._input_buffer = bytearray()
        self._input_expected_packet_num = 0
        self._input_expected_length = 0
        # Responses are queued with their ACK sequence and command because
        # unsolicited TIME/DP frames may arrive while a command is pending.
        self._notify_queue: asyncio.Queue = asyncio.Queue()
        self._write_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._report_event = asyncio.Event()
        self._report_generation = 0
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Return whether the application session is connected."""
        return self._connected

    def set_ble_device(self, ble_device: Any) -> None:
        """Use a newly resolved BLE device for the next connection."""
        self._ble_device = ble_device

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "WindCalmDevice":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to the device and perform the Tuya BLE handshake."""
        if self._connected:
            return
        self._reset_session()
        try:
            target = self._ble_device or self._config.mac
            self._client = await self._client_factory(target, self._on_disconnect)
            await self._client.start_notify(
                CHARACTERISTIC_NOTIFY, self._on_notification
            )
            self._connected = True
            await self._handshake()
        except (BleakError, OSError, asyncio.TimeoutError, WindCalmError) as exc:
            await self.disconnect()
            if isinstance(exc, WindCalmError):
                raise
            raise WindCalmError(f"Failed to connect to device: {exc}") from exc

    async def disconnect(self) -> None:
        """Disconnect from the device and clean up resources."""
        self._connected = False
        if self._client is not None:
            try:
                await self._client.stop_notify(CHARACTERISTIC_NOTIFY)
            except (BleakError, OSError):
                pass
            try:
                await self._client.disconnect()
            except (BleakError, OSError):
                pass
            self._client = None

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle an unexpected Bleak disconnect."""
        if client is not self._client:
            return
        self._connected = False
        if self._disconnect_callback is not None:
            self._disconnect_callback()

    def _reset_session(self) -> None:
        """Reset all state that belongs to one BLE application session."""
        self._login_key = None
        self._session_key = None
        self._srand = None
        self._tx_counter = 1
        self._notify_queue = asyncio.Queue()
        self._report_event.clear()
        self._report_generation = 0
        self._reset_input()

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------
    async def _handshake(self) -> None:
        """Perform the device-info and pairing exchange."""
        self._login_key = derive_login_key(self._config.local_key)
        info = await self._send_device_info_request()
        self._srand = info.srand
        # Session key is MD5(raw 6-byte local key + srand), NOT the MD5 login key.
        self._session_key = derive_session_key(
            self._config.login_key, self._srand
        )
        result = await self._send_command(CMD_PAIR, self._build_pairing_request())
        if result and result[0] not in (0x00, 0x02):
            raise WindCalmAuthenticationError("Device rejected the credentials")

    def _build_pairing_request(self) -> bytes:
        """Build the pairing request payload.

        The payload is the device UUID, the 6-byte login key, the device ID,
        zero-padded to 44 bytes (matching ``ha_tuya_ble``).
        """
        result = bytearray()
        result += self._config.uuid.encode("ascii")
        result += self._config.login_key
        result += self._config.device_id.encode("ascii")
        for _ in range(44 - len(result)):
            result += b"\x00"
        return bytes(result)

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------
    async def get_status(self) -> FanStatus:
        """Request the current datapoints and return a decoded status."""
        async with self._transaction_lock:
            generation = self._report_generation
            self._report_event.clear()
            await self._send_command_locked(CMD_DEVICE_STATUS, b"")
            if self._report_generation == generation:
                try:
                    await asyncio.wait_for(self._report_event.wait(), timeout=2.0)
                except asyncio.TimeoutError as exc:
                    raise WindCalmError(
                        "Timed out waiting for a fresh status report"
                    ) from exc
        return self._decode_status()

    async def set_power(self, on: bool) -> None:
        """Turn the fan on or off."""
        await self._set_datapoint(DP_FAN_SWITCH, DataPointType.BOOL, bool(on))

    async def set_speed(self, speed: int) -> None:
        """Set the fan speed (1-6)."""
        if not 1 <= speed <= 6:
            raise ValueError("Fan speed must be between 1 and 6")
        await self._set_datapoint(DP_FAN_SPEED, DataPointType.VALUE, int(speed))

    async def set_direction(self, direction: FanDirection) -> None:
        """Set the fan rotation direction."""
        await self._set_datapoint(
            DP_FAN_DIRECTION, DataPointType.ENUM, int(direction)
        )

    async def set_countdown(self, minutes: int) -> None:
        """Set the fan countdown timer in minutes (0-540)."""
        if not 0 <= minutes <= 540:
            raise ValueError("Countdown must be between 0 and 540 minutes")
        await self._set_datapoint(DP_COUNTDOWN, DataPointType.VALUE, int(minutes))

    async def set_light(self, on: bool) -> None:
        """Turn the light on or off."""
        await self._set_datapoint(DP_LIGHT_SWITCH, DataPointType.BOOL, bool(on))

    async def set_work_mode(self, mode: WorkMode) -> None:
        """Set the light work mode."""
        await self._set_datapoint(DP_WORK_MODE, DataPointType.ENUM, int(mode))

    async def set_light_temperature(self, value: int) -> None:
        """Set the raw light-temperature value (0-1000)."""
        if not 0 <= value <= 1000:
            raise ValueError("Light temperature must be between 0 and 1000")
        await self._set_datapoint(
            DP_LIGHT_TEMPERATURE, DataPointType.VALUE, int(value)
        )

    # ------------------------------------------------------------------
    # Datapoint encoding / decoding
    # ------------------------------------------------------------------
    def _encode_datapoint(self, dp: DataPoint) -> bytes:
        """Encode a datapoint into its wire representation."""
        header = struct.pack(">BBB", dp.id, int(dp.type), 0)
        value = self._encode_value(dp.type, dp.value)
        return header[:2] + struct.pack(">B", len(value)) + value

    @staticmethod
    def _encode_value(dp_type: DataPointType, value: Any) -> bytes:
        """Encode a datapoint value according to its type."""
        if dp_type == DataPointType.BOOL:
            return b"\x01" if value else b"\x00"
        if dp_type == DataPointType.VALUE:
            return struct.pack(">i", int(value))
        if dp_type == DataPointType.ENUM:
            return struct.pack(">B", int(value))
        if dp_type == DataPointType.STRING:
            return str(value).encode("utf-8")
        if dp_type in (DataPointType.RAW, DataPointType.BITMAP):
            return bytes(value)
        raise WindCalmProtocolError(f"Unsupported datapoint type: {dp_type}")

    @staticmethod
    def _decode_value(dp_type: DataPointType, raw: bytes) -> Any:
        """Decode a datapoint value from its wire format."""
        if dp_type == DataPointType.BOOL:
            return bool(raw[0]) if raw else False
        if dp_type == DataPointType.VALUE:
            return struct.unpack(">i", raw)[0] if len(raw) >= 4 else 0
        if dp_type == DataPointType.ENUM:
            return int.from_bytes(raw, "big") if raw else 0
        if dp_type == DataPointType.STRING:
            return raw.decode("utf-8", errors="replace")
        if dp_type in (DataPointType.RAW, DataPointType.BITMAP):
            return raw
        raise WindCalmProtocolError(f"Unsupported datapoint type: {dp_type}")

    def _decode_status(self) -> FanStatus:
        """Decode the current datapoints into a :class:`FanStatus`."""
        status = FanStatus()
        for dp in self._datapoints.values():
            status.datapoints[dp.id] = dp
            if dp.id == DP_FAN_SWITCH:
                status.power = bool(dp.value)
            elif dp.id == DP_FAN_SPEED:
                status.speed = int(dp.value)
            elif dp.id == DP_FAN_DIRECTION:
                status.direction = FanDirection(int(dp.value))
            elif dp.id == DP_COUNTDOWN:
                status.countdown = int(dp.value)
            elif dp.id == DP_LIGHT_SWITCH:
                status.light_on = bool(dp.value)
            elif dp.id == DP_WORK_MODE:
                status.work_mode = WorkMode(int(dp.value))
            elif dp.id == DP_LIGHT_TEMPERATURE:
                status.light_temperature = int(dp.value)
        return status

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------
    async def _set_datapoint(
        self, dp_id: int, dp_type: DataPointType, value: Any
    ) -> None:
        """Send a single datapoint update to the device."""
        dp = DataPoint(id=dp_id, type=dp_type, value=value)
        payload = self._encode_datapoint(dp)
        await self._send_command(CMD_SEND_DPS, payload)

    async def _send_command(
        self,
        code: int,
        payload: bytes,
        response_to: int = 0,
        wait_for_response: bool = True,
    ) -> bytes:
        """Send a command and optionally wait for its response.

        Parameters
        ----------
        code:
            Command code to send.
        payload:
            Command payload.
        response_to:
            If > 0, this packet is an acknowledgement of a previously
            received frame with the given sequence number.
        wait_for_response:
            If False, the packet is sent without waiting for a reply
            (used for acknowledgements).

        Returns
        -------
        bytes
            The response payload (empty if ``wait_for_response`` is False).

        Raises
        ------
        WindCalmError
            If the command times out or the device returns an error.
        """
        if not wait_for_response:
            await self._write_command(code, payload, response_to)
            return b""

        async with self._transaction_lock:
            return await self._send_command_locked(code, payload, response_to)

    async def _send_command_locked(
        self, code: int, payload: bytes, response_to: int = 0
    ) -> bytes:
        """Send one command while the caller holds the transaction lock."""
        expected_seq = await self._write_command(code, payload, response_to)

        # Wait for the response acknowledging this exact sequence number.
        deadline = asyncio.get_event_loop().time() + RESPONSE_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise WindCalmError("Timed out waiting for device response")
            try:
                response = await asyncio.wait_for(
                    self._notify_queue.get(), timeout=remaining
                )
            except asyncio.TimeoutError:
                raise WindCalmError("Timed out waiting for device response")
            if response is None:
                continue
            response_ack, response_code, response_payload = response
            if response_ack == expected_seq and response_code == code:
                return response_payload

    async def _write_command(
        self, code: int, payload: bytes, response_to: int = 0
    ) -> int:
        """Write a complete, non-interleaved command and return its sequence."""
        if self._client is None or not self._connected:
            raise WindCalmError("Device is not connected")
        async with self._write_lock:
            expected_seq = self._tx_counter
            packets = self._build_packets(code, payload, response_to)
            for packet in packets:
                await self._client.write_gatt_char(
                    CHARACTERISTIC_WRITE, packet, response=False
                )
        return expected_seq

    async def _send_device_info_request(self) -> DeviceInfo:
        """Send the device-info request and parse the reply.

        The device-info reply is encrypted with the login key (before the
        session key exists), so it is handled separately from other commands.
        """
        if self._client is None or not self._connected:
            raise WindCalmError("Device is not connected")

        expected_seq = await self._write_command(CMD_DEVICE_INFO, b"")

        deadline = asyncio.get_event_loop().time() + RESPONSE_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise WindCalmError("Timed out waiting for device-info reply")
            try:
                payload = await asyncio.wait_for(
                    self._notify_queue.get(), timeout=remaining
                )
            except asyncio.TimeoutError:
                raise WindCalmError("Timed out waiting for device-info reply")
            if payload is None:
                continue
            response_ack, response_code, response_payload = payload
            if response_ack == expected_seq and response_code == CMD_DEVICE_INFO:
                return DeviceInfo.from_bytes(response_payload)

    def _build_packets(
        self, code: int, payload: bytes, response_to: int = 0
    ) -> list:
        """Build the encrypted application frame and split it into subpackets.

        The inner (plaintext) frame is::

            SN (4 bytes, big-endian)
            ACK_SN (4 bytes, big-endian)
            CMD (2 bytes, big-endian)
            LEN (2 bytes, big-endian)
            DATA (LEN bytes)
            CRC16 (2 bytes, big-endian)

        The inner frame is zero-padded to a multiple of 16 bytes, encrypted
        with AES-128-CBC, and prefixed with a security flag and a random IV.

        The encrypted frame is then split into outer Tuya subpackets, each
        limited to ``GATT_MTU`` bytes. The first subpacket carries the total
        frame length and the protocol version.

        The device-info request (``0x0000``) is encrypted with the login key;
        all other commands use the session key.

        Parameters
        ----------
        response_to:
            If > 0, this packet acknowledges a previously received frame
            with the given sequence number.

        Returns
        -------
        list
            A list of subpacket byte strings to write to ``2B11``.
        """
        if code == CMD_DEVICE_INFO:
            key = self._login_key
            security_flag = SECURITY_FLAG_LOGIN
        else:
            key = self._session_key
            security_flag = SECURITY_FLAG_SESSION
        if key is None:
            raise WindCalmError("Device is not paired")

        seq = self._tx_counter
        self._tx_counter += 1

        inner = (
            struct.pack(">IIHH", seq, response_to, code, len(payload))
            + payload
        )
        crc = crc16(inner)
        inner += struct.pack(">H", crc)

        iv = secrets.token_bytes(16)
        ciphertext = encrypt_cbc(key, iv, inner)
        encrypted = bytes([security_flag]) + iv + ciphertext

        packets = []
        packet_num = 0
        pos = 0
        length = len(encrypted)
        while pos < length:
            packet = bytearray()
            packet += _pack_varint(packet_num)
            if packet_num == 0:
                packet += _pack_varint(length)
                packet += bytes([self._protocol_version << 4])
            data_part = encrypted[pos : pos + GATT_MTU - len(packet)]
            packet += data_part
            packets.append(bytes(packet))
            pos += len(data_part)
            packet_num += 1
        return packets

    def _on_notification(self, _sender: int, data: bytearray) -> None:
        """Handle an incoming notification from the notify characteristic.

        Notifications arrive as one or more outer Tuya subpackets. The
        subpackets are reassembled into a complete encrypted frame, which is
        then decrypted and dispatched.
        """
        try:
            frame = self._reassemble(bytes(data))
        except WindCalmProtocolError as exc:
            _LOGGER.warning("Dropping malformed notification: %s", exc)
            self._reset_input()
            return
        if frame is None:
            # More subpackets are expected.
            return
        try:
            self._handle_frame(frame)
        except WindCalmProtocolError as exc:
            _LOGGER.warning("Dropping malformed frame: %s", exc)
            return

    def _handle_frame(self, data: bytes) -> None:
        """Decrypt an incoming frame and dispatch it by command code."""
        if len(data) < 1 + 16 + 16:
            raise WindCalmProtocolError("Notification frame is too short")

        security_flag = data[0]
        iv = data[1:17]
        ciphertext = data[17:]

        if security_flag == SECURITY_FLAG_LOGIN:
            key = self._login_key
        elif security_flag == SECURITY_FLAG_SESSION:
            key = self._session_key
        else:
            raise WindCalmProtocolError(
                f"Unknown security flag: 0x{security_flag:02x}"
            )
        if key is None:
            raise WindCalmProtocolError("Received frame before key was set")

        inner = decrypt_cbc(key, iv, ciphertext)

        if len(inner) < 12:
            raise WindCalmProtocolError("Inner frame is too short")
        seq, ack, code, length = struct.unpack(">IIHH", inner[:12])

        data_end = 12 + length
        if len(inner) < data_end + 2:
            raise WindCalmProtocolError("Inner frame payload is truncated")
        calc_crc = crc16(inner[:data_end])
        (data_crc,) = struct.unpack(">H", inner[data_end : data_end + 2])
        if calc_crc != data_crc:
            raise WindCalmProtocolError("Inner frame CRC mismatch")

        payload = inner[12:data_end]
        _LOGGER.debug(
            "Received frame: seq=%s ack=%s code=0x%04x len=%s",
            seq, ack, code, length,
        )

        # Un-acknowledged report from the device: parse datapoints.
        if code == CMD_DP_REPORT:
            self._parse_datapoints(payload)
            self._report_generation += 1
            self._report_event.set()
            if self._status_callback is not None:
                self._status_callback(self._decode_status())
            # Acknowledge the report with a success byte (matches the
            # official Tuya app capture: payload = 0x00).
            self._create_response_task(
                self._send_command(
                    CMD_DP_REPORT, b"\x00", response_to=seq,
                    wait_for_response=False,
                )
            )
            return

        # The device needs the current time. Answer it, or it will not send
        # further datapoint reports.
        if code == CMD_TIME1_REQ:
            # Tuya expects the current epoch in milliseconds followed by the
            # local timezone offset in quarter-hours.
            timestamp = str(int(time.time() * 1000)).encode("ascii")
            timezone = -int(time.timezone / 36)
            data = timestamp + struct.pack(">h", timezone)
            self._create_response_task(
                self._send_command(
                    code, data, response_to=seq, wait_for_response=False
                )
            )
            return
        if code == CMD_TIME2_REQ:
            t = time.localtime()
            timezone = -int(time.timezone / 36)
            data = struct.pack(
                ">BBBBBBBh",
                t.tm_year % 100, t.tm_mon, t.tm_mday,
                t.tm_hour, t.tm_min, t.tm_sec, t.tm_wday, timezone,
            )
            self._create_response_task(
                self._send_command(
                    code, data, response_to=seq, wait_for_response=False
                )
            )
            return

        # Normal response to a command we sent.
        self._notify_queue.put_nowait((ack, code, payload))

    @staticmethod
    def _create_response_task(coroutine: Awaitable[bytes]) -> None:
        """Send a protocol response without leaking background exceptions."""
        task = asyncio.create_task(coroutine)

        def log_failure(done: asyncio.Task) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except (WindCalmError, BleakError, OSError) as exc:
                _LOGGER.debug("Unable to send protocol response: %s", exc)

        task.add_done_callback(log_failure)

    def _parse_datapoints(self, payload: bytes) -> None:
        """Parse a datapoint report and update the local cache."""
        pos = 0
        while pos + 3 <= len(payload):
            dp_id = payload[pos]
            dp_type = payload[pos + 1]
            dp_len = payload[pos + 2]
            pos += 3
            if pos + dp_len > len(payload):
                raise WindCalmProtocolError("Datapoint payload is truncated")
            raw = payload[pos : pos + dp_len]
            pos += dp_len
            try:
                value = self._decode_value(DataPointType(dp_type), raw)
            except (ValueError, WindCalmProtocolError):
                continue
            self._datapoints[dp_id] = DataPoint(
                id=dp_id, type=DataPointType(dp_type), value=value
            )
        if pos != len(payload):
            raise WindCalmProtocolError("Datapoint payload has a trailing fragment")

    def _reset_input(self) -> None:
        """Reset the subpacket reassembly state."""
        self._input_buffer = bytearray()
        self._input_expected_packet_num = 0
        self._input_expected_length = 0

    def _reassemble(self, data: bytes) -> Optional[bytes]:
        """Reassemble a complete encrypted frame from subpackets.

        Returns
        -------
        Optional[bytes]
            The complete encrypted frame, or ``None`` if more subpackets are
            expected.
        """
        packet_num, pos = _unpack_varint(data, 0)

        if packet_num < self._input_expected_packet_num:
            raise WindCalmProtocolError(
                f"Unexpected subpacket number {packet_num}"
            )
        if packet_num > self._input_expected_packet_num:
            raise WindCalmProtocolError(
                f"Missing subpacket {self._input_expected_packet_num}"
            )

        if packet_num == 0:
            self._input_buffer = bytearray()
            self._input_expected_length, pos = _unpack_varint(data, pos)
            if pos >= len(data):
                raise WindCalmProtocolError("Missing subpacket version")
            pos += 1  # skip the version byte
            self._input_expected_packet_num = 1
        else:
            self._input_expected_packet_num += 1

        self._input_buffer += data[pos:]

        if len(self._input_buffer) > self._input_expected_length:
            raise WindCalmProtocolError("Reassembled frame is too long")
        if len(self._input_buffer) == self._input_expected_length:
            frame = bytes(self._input_buffer)
            self._reset_input()
            return frame
        return None
