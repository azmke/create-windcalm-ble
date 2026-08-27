# CREATE WIND CALM Tuya BLE Protocol

This document describes the Tuya BLE protocol variant used by a CREATE WIND CALM ceiling fan (`XW-FAN-215-D`). It is intended as an implementation reference for compatible clients and corresponds to the Python implementation in this repository.

The protocol is not the generic Bluetooth meaning of the UUIDs. The fan reuses Tuya's vendor transport on top of GATT.

## 1. GATT transport

The fan exposes:

| Item | UUID | Properties | Role |
|---|---|---|---|
| Service | `00001910-0000-1000-8000-00805f9b34fb` | primary | Tuya BLE service |
| Write characteristic | `00002b11-0000-1000-8000-00805f9b34fb` | write, write without response | Phone/client to fan |
| Notify characteristic | `00002b10-0000-1000-8000-00805f9b34fb` | notify | Fan to phone/client |

The implementation uses a maximum Tuya transport write size of 20 bytes. A single application frame is therefore split into several Tuya subpackets, even when the negotiated ATT MTU is larger.

Before sending application data:

1. Connect to the fan.
2. Enable notifications on `2B10`.
3. Send the encrypted device-info request to `2B11`.

## 2. Outer subpacket framing

Every GATT write or notification carries one subpacket. The subpacket number and, in subpacket zero, the total encrypted-frame length are unsigned little-endian base-128 varints.

### Subpacket zero

```text
varint packet_number       # always 0
varint total_frame_length  # bytes after this outer header
byte   protocol_version    # high nibble is the Tuya protocol version
byte[] frame_data
```

### Following subpackets

```text
varint packet_number       # 1, 2, 3, ...
byte[] frame_data
```

The frame data from all subpackets is concatenated until `total_frame_length` bytes have been received. Subpacket numbers are strictly sequential and a new frame starts with packet number zero.

For this fan, the client sends protocol version `2` (`0x20`) and the fan replies with protocol version `3` (`0x30`). This asymmetry is intentional for compatibility with this device.

## 3. Encrypted frame

After reassembly, the encrypted frame has this layout:

```text
byte   security_flag
byte[] iv             # 16 bytes
byte[] ciphertext     # AES-CBC ciphertext
```

The ciphertext is decrypted with AES-128-CBC. Plaintext is zero-padded to a 16-byte boundary; there is no PKCS#7 padding.

Security flags used by this device:

| Flag | Key |
|---:|---|
| `0x04` | login key; used for `DEVICE_INFO` |
| `0x05` | session key; used after device-info exchange |

The IV is random for each frame and is transmitted in cleartext. The wire protocol provides integrity through the CRC field described below, not through an authenticated encryption tag.

## 4. Inner application frame

The decrypted plaintext starts with:

```text
uint32  sequence_number   # big-endian
uint32  ack_sequence      # big-endian; 0 if not an acknowledgement
uint16  command           # big-endian
uint16  payload_length    # big-endian
byte[]  payload           # payload_length bytes
uint16  crc16             # big-endian
byte[]  zero_padding      # until AES block boundary
```

The CRC is CRC-16/MODBUS over the header and payload, from `sequence_number` through the final payload byte. It uses initial value `0xFFFF` and reflected polynomial `0xA001`.

Sequence numbers are local to a connection and start at `1`. Each transmitted application frame consumes the next sequence number, including acknowledgements and time responses.

## 5. Keys and authentication

The fan is provisioned by the Tuya ecosystem. A compatible client needs the device's local key, device ID, and UUID from a trusted source. They must not be placed in source control or logs.

Let `L` be the ASCII local key and `P = L[:6]` its first six ASCII characters.

```text
login_key   = MD5(P)
session_key = MD5(P || srand)
```

The device-info response supplies `srand`, a six-byte random challenge. The pairing payload also contains the raw six-byte prefix `P`; it does not contain the login key produced by MD5.

This is application-layer session security. It is independent of whether
BlueZ reports the device as paired or bonded; the fan can use this protocol
without a Bluetooth link-layer bond.

## 6. Connection and handshake

The compatible connection sequence is:

```text
client -> fan: DEVICE_INFO (0x0000), security flag 0x04, sequence 1
fan    -> client: DEVICE_INFO (0x0000), ACK 1, security flag 0x04
client -> fan: PAIR (0x0001), security flag 0x05, sequence 2
fan    -> client: TIME1_REQ (0x8011), sequence 2, ACK 0
client -> fan: TIME1_REQ (0x8011), ACK 2, 13-byte time payload
fan    -> client: PAIR (0x0001), ACK 2, one-byte result
client -> fan: DEVICE_STATUS (0x0003), security flag 0x05
fan    -> client: DEVICE_STATUS (0x0003), one-byte result
fan    -> client: DP_REPORT (0x8001), current datapoints
client -> fan: DP_REPORT (0x8001), ACK of the report
```

The pairing result `0x02` means that the fan is already paired. It is not a failure for a previously provisioned device. A result of `0x00` indicates success; other result values should be treated as errors unless defined by the device firmware.

The device-info payload is at least 46 bytes:

```text
offset 0..1    device firmware version
       2..3    protocol version
       4        flags
       5        bound/paired state (non-zero means bound)
       6..11    srand (6 bytes)
      12..13    hardware version
      14..45    auth key (32 bytes)
```

The auth key is returned by the fan but is not required by this implementation's session flow.

The client pairing payload is exactly 44 bytes:

```text
ASCII UUID
ASCII P                 # six raw local-key-prefix bytes
ASCII device ID
zero bytes              # until 44 bytes total
```

## 7. Time synchronization

After pairing, the fan sends `TIME1_REQ` (`0x8011`) with an empty payload. The client must answer it. The accepted payload format is:

```text
ASCII decimal Unix time in milliseconds  # normally 13 digits
int16 timezone offset                   # big-endian, quarter-hour units
```

The implementation also supports `TIME2_REQ` (`0x8012`). Its response is:

```text
uint8 year   # year modulo 100
uint8 month
uint8 day
uint8 hour
uint8 minute
uint8 second
uint8 weekday
int16 timezone offset  # big-endian, quarter-hour units
```

The need for `TIME2_REQ` depends on the device firmware. The command is part of the Tuya command set and is handled defensively.

## 8. Commands and acknowledgements

| Command | Value | Direction/meaning |
|---|---:|---|
| `DEVICE_INFO` | `0x0000` | Request device information; login key encryption |
| `PAIR` | `0x0001` | Establish application session / pairing state |
| `SEND_DPS` | `0x0002` | Write datapoints |
| `DEVICE_STATUS` | `0x0003` | Request current datapoints |
| `DP_REPORT` | `0x8001` | Device datapoint report and its acknowledgement |
| `TIME1_REQ` | `0x8011` | Millisecond timestamp request/response |
| `TIME2_REQ` | `0x8012` | Calendar time request/response |

There are two distinct acknowledgement mechanisms:

1. **Command response correlation:** a response sets `ack_sequence` to the sequence number of the request. The client must match both `ack_sequence` and command before treating it as the requested response.
2. **Explicit report acknowledgement:** an unsolicited `DP_REPORT` from the fan is acknowledged by sending `DP_REPORT` with `ack_sequence` set to the report sequence and payload `00`.

A `SEND_DPS` write is acknowledged by a one-byte response payload, normally `00`. The subsequent state change is reported separately as an unsolicited `DP_REPORT`.

## 9. Datapoint encoding

A datapoint is encoded as:

```text
uint8  id
enum8  type
uint8  value_length
byte[] value
```

Tuya datapoint types used by this device:

| Type | Value |
|---:|---|
| `0` | raw |
| `1` | boolean; one byte `00` or `01` |
| `2` | value; this fan uses a signed big-endian 32-bit integer |
| `3` | UTF-8 string |
| `4` | enum; this fan uses one byte |
| `5` | bitmap/raw bytes |

Fan datapoints:

| DP | Name | Type / values |
|---:|---|---|
| `20` | light switch | bool |
| `21` | light work mode | enum: `0 white`, `1 colour`, `2 scene`, `3 music` |
| `23` | light temperature value | signed value, `0` through `1000`; the device metadata does not specify physical Kelvin values |
| `60` | fan switch | bool |
| `62` | fan speed | value, `1` through `6` |
| `63` | fan direction | enum: `0 forward`, `1 reverse` |
| `64` | fan countdown | value, minutes, `0` through `540` |

## 10. Heartbeat and connection lifetime

No separate heartbeat command is required to complete the handshake or accept controls.

The fan expects application traffic during initialization, especially the `TIME1_REQ` response. A connection that only enables notifications and remains otherwise silent may be terminated by the fan after approximately 30 seconds. This is application/session timeout behavior, not a generic BLE keepalive requirement.

For a long-lived connection, the client should:

- answer any time requests;
- acknowledge every unsolicited datapoint report;
- correlate command responses by sequence and command;
- keep the BLE link within reliable radio range.

A periodic application heartbeat should not be invented without device-specific
protocol evidence.

## 11. Operational limitations

- The implementation targets the CREATE WIND CALM variant and its Tuya BLE V2/V3-compatible framing.
- The transport MTU is deliberately kept at 20 bytes, even if the host reports a larger negotiated ATT MTU.
- The device-info/session values and diagnostic Bluetooth traffic are sensitive. Do not commit `.env`, device metadata, or raw diagnostic traffic.
- A successful CLI command normally disconnects immediately after the operation; this is intentional lifecycle behavior, not a protocol failure.
