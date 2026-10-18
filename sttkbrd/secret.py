"""Keeps the API key from lying in config.json as plain text.

The key is encrypted with a key that is built into the program, so this only hides it from a glance (a shared
screen, a pasted config file, a text search). Anyone who has the program can decrypt it: it is obfuscation,
not protection against someone who can read both files.

Standard library only: HMAC-SHA256 as a keystream (counter mode), then an HMAC tag over the result, so a
damaged or edited value is detected instead of decrypted into garbage.
"""
import base64
import hashlib
import hmac
import os

PREFIX = "v1:"
_KEY = hashlib.sha256(b"sttkbrd/api-key/v1/7c1e5d2a9b3f4806a5d1e0c9").digest()
_ENC_KEY = hmac.digest(_KEY, b"encrypt", "sha256")
_MAC_KEY = hmac.digest(_KEY, b"authenticate", "sha256")


def _keystream(nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.digest(_ENC_KEY, nonce + counter.to_bytes(8, "big"), "sha256")
        counter += 1
    return bytes(out[:length])


def encrypt(text):
    """'sk-...' -> 'v1:<base64>'. Different every time (random nonce)."""
    data = text.encode("utf-8")
    nonce = os.urandom(16)
    body = nonce + bytes(a ^ b for a, b in zip(data, _keystream(nonce, len(data))))
    return PREFIX + base64.b64encode(body + hmac.digest(_MAC_KEY, body, "sha256")[:16]).decode("ascii")


def decrypt(value):
    """Inverse of encrypt(). Raises ValueError if the value is not ours or has been changed."""
    if not value.startswith(PREFIX):
        raise ValueError("not an encrypted value")
    try:
        raw = base64.b64decode(value[len(PREFIX):], validate=True)
    except ValueError:
        raise ValueError("not an encrypted value")
    if len(raw) < 32:
        raise ValueError("encrypted value is too short")
    body, tag = raw[:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.digest(_MAC_KEY, body, "sha256")[:16]):
        raise ValueError("encrypted value is damaged")
    nonce, data = body[:16], body[16:]
    return bytes(a ^ b for a, b in zip(data, _keystream(nonce, len(data)))).decode("utf-8")
