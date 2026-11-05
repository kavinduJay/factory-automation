"""ULID: 48-bit millisecond time + 80 random bits, Crockford base32 (26 chars).
Sortable by time, which is what the firmware will use for msg_id."""
import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if ms is None else ms
    n = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(out))
