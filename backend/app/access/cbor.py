"""A small CBOR decoder: only what WebAuthn needs (ints, byte/text strings, arrays, maps, bool/null, floats)."""
from __future__ import annotations

import struct
from typing import Any


class CborError(ValueError):
    pass


def decode(data: bytes) -> Any:
    value, end = _item(data, 0, 0)
    if end != len(data):
        raise CborError("trailing bytes")
    return value


def decode_prefix(data: bytes) -> tuple[Any, int]:
    """Decode one item from the start of `data` and return it with the number of bytes used (authenticator data embeds CBOR)."""
    return _item(data, 0, 0)


def _arg(data: bytes, i: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, i
    size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
    if size is None or i + size > len(data):
        raise CborError("bad length")
    return int.from_bytes(data[i:i + size], "big"), i + size


def _item(data: bytes, i: int, depth: int) -> tuple[Any, int]:
    if depth > 16 or i >= len(data):
        raise CborError("too deep or truncated")
    major, info = data[i] >> 5, data[i] & 31
    i += 1
    if major == 7:
        if info == 20: return False, i
        if info == 21: return True, i
        if info in (22, 23): return None, i
        if info == 26: return struct.unpack(">f", data[i:i + 4])[0], i + 4
        if info == 27: return struct.unpack(">d", data[i:i + 8])[0], i + 8
        raise CborError("unsupported simple value")
    n, i = _arg(data, i, info)
    if major == 0: return n, i
    if major == 1: return -1 - n, i
    if major in (2, 3):
        if i + n > len(data): raise CborError("truncated string")
        raw = data[i:i + n]
        return (bytes(raw) if major == 2 else raw.decode()), i + n
    if major == 4:
        if n > 1024: raise CborError("array too large")
        out = []
        for _ in range(n):
            v, i = _item(data, i, depth + 1)
            out.append(v)
        return out, i
    if major == 5:
        if n > 1024: raise CborError("map too large")
        m: dict[Any, Any] = {}
        for _ in range(n):
            k, i = _item(data, i, depth + 1)
            v, i = _item(data, i, depth + 1)
            m[k] = v
        return m, i
    if major == 6:
        return _item(data, i, depth + 1)   # a tag: ignore it, keep the value
    raise CborError("bad major type")
