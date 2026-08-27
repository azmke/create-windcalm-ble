"""Cryptographic primitives for the Tuya BLE V2/V3 protocol.

The fan (protocol version 3.4) uses AES-128-CBC with a random 16-byte IV.
The on-wire layout of an encrypted frame is::

    security_flag (1 byte)  4 = login key, 5 = session key
    IV (16 bytes)
    AES-CBC ciphertext

The plaintext is zero-padded to a multiple of 16 bytes (not PKCS#7).

Key derivation::

    login_key   = MD5(local_key[:6])
    session_key = MD5(login_key || srand)

where ``srand`` is a 6-byte random value returned by the device in the
device-info reply.
"""

from __future__ import annotations

import hashlib

from Crypto.Cipher import AES

# Security flags used in the on-wire frame header.
SECURITY_FLAG_LOGIN = 0x04
SECURITY_FLAG_SESSION = 0x05


def derive_login_key(local_key: str) -> bytes:
    """Derive the 16-byte login key from the local key.

    The login key is ``MD5(local_key[:6])``.
    """
    return hashlib.md5(local_key[:6].encode("ascii")).digest()


def derive_session_key(local_key_prefix: bytes, srand: bytes) -> bytes:
    """Derive the 16-byte session key.

    The session key is ``MD5(local_key_prefix + srand)``, where
    ``local_key_prefix`` is the raw first six bytes of the local key.
    """
    return hashlib.md5(local_key_prefix + srand).digest()


def crc16(data: bytes) -> int:
    """Compute the CRC-16/MODBUS checksum used by the protocol.

    Initial value ``0xFFFF``, reflected polynomial ``0xA001``.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _pad16(data: bytes) -> bytes:
    """Zero-pad ``data`` to a multiple of 16 bytes."""
    remainder = len(data) % 16
    if remainder == 0:
        return data
    return data + b"\x00" * (16 - remainder)


def encrypt_cbc(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """Encrypt ``plaintext`` with AES-128-CBC using the given IV."""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(_pad16(plaintext))


def decrypt_cbc(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """Decrypt ``ciphertext`` with AES-128-CBC using the given IV."""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.decrypt(ciphertext)
