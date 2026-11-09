"""A small QR code encoder (byte mode, error correction M, versions 1-10), so the authenticator setup shows a scannable code
without any third-party package. `svg(text)` returns an SVG string. Verified in the tests by decoding the output with OpenCV."""
from __future__ import annotations

# (total codewords, ec codewords per block, [(blocks, data codewords per block), ...]) for level M
_EC_M = {
    1: (26, 10, [(1, 16)]), 2: (44, 16, [(1, 28)]), 3: (70, 26, [(1, 44)]), 4: (100, 18, [(2, 32)]), 5: (134, 24, [(2, 43)]),
    6: (172, 16, [(4, 27)]), 7: (196, 18, [(4, 31)]), 8: (242, 22, [(2, 38), (2, 39)]), 9: (292, 22, [(3, 36), (2, 37)]),
    10: (346, 26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n: int) -> list[int]:
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        g = nxt
    return g


def _rs_remainder(data: list[int], n: int) -> list[int]:
    gen, rem = _rs_generator(n), [0] * n
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _mul(gen[i + 1], factor)
    return rem


def _capacity(v: int) -> int:
    return sum(b * d for b, d in _EC_M[v][2])


def _codewords(data: bytes, version: int) -> list[int]:
    bits = "0100" + format(len(data), "08b" if version < 10 else "016b") + "".join(format(b, "08b") for b in data)
    cap = _capacity(version) * 8
    bits += "0" * min(4, cap - len(bits))
    bits += "0" * (-len(bits) % 8)
    words = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(words) < _capacity(version):
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    total, ec_n, groups = _EC_M[version]
    blocks, i = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(words[i:i + size])
            i += size
    ecs = [_rs_remainder(b, ec_n) for b in blocks]
    out = []
    for k in range(max(len(b) for b in blocks)):
        out += [b[k] for b in blocks if k < len(b)]
    for k in range(ec_n):
        out += [e[k] for e in ecs]
    assert len(out) == total
    return out


def _matrix(version: int, words: list[int], mask: int) -> list[list[int]]:
    n = 17 + 4 * version
    m = [[0] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def put(r: int, c: int, v: int, reserve: bool = True) -> None:
        if 0 <= r < n and 0 <= c < n:
            m[r][c] = v
            if reserve:
                fn[r][c] = True

    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):               # finder patterns with separators
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                on = 0 <= dr <= 6 and 0 <= dc <= 6 and (dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4))
                put(r0 + dr, c0 + dc, int(on))
    pos = _ALIGN[version]
    for r in pos:
        for c in pos:
            if fn[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, int(max(abs(dr), abs(dc)) != 1))
    for i in range(8, n - 8):
        put(6, i, int(i % 2 == 0)); put(i, 6, int(i % 2 == 0))
    put(n - 8, 8, 1)                                               # dark module
    for i in range(9):                                             # reserve format areas
        fn[8][i] = fn[i][8] = True
    for i in range(8):
        fn[8][n - 1 - i] = fn[n - 1 - i][8] = True
    if version >= 7:                                               # version information
        v = version
        rem = v
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (v << 12) | rem
        for i in range(18):
            bit = (bits >> i) & 1
            put(i // 3, n - 11 + i % 3, bit); put(n - 11 + i % 3, i // 3, bit)
    bits = [(w >> (7 - k)) & 1 for w in words for k in range(8)]
    idx, up = 0, True
    c = n - 1
    while c > 0:
        if c == 6:
            c -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for r in rows:
            for cc in (c, c - 1):
                if not fn[r][cc]:
                    bit = bits[idx] if idx < len(bits) else 0
                    idx += 1
                    m[r][cc] = bit ^ int(_mask(mask, r, cc))
        up = not up
        c -= 2
    fmt = _format_bits(mask)                                       # format information (level M = 00)
    for i in range(15):
        bit = (fmt >> i) & 1
        if i < 6: m[i][8] = bit
        elif i == 6: m[7][8] = bit
        elif i == 7: m[8][8] = bit
        elif i == 8: m[8][7] = bit
        else: m[8][14 - i] = bit
        if i < 8: m[8][n - 1 - i] = bit
        else: m[n - 15 + i][8] = bit
    return m


def _mask(k: int, r: int, c: int) -> bool:
    return [(r + c) % 2 == 0, r % 2 == 0, c % 3 == 0, (r + c) % 3 == 0, (r // 2 + c // 3) % 2 == 0,
            (r * c) % 2 + (r * c) % 3 == 0, ((r * c) % 2 + (r * c) % 3) % 2 == 0, ((r + c) % 2 + (r * c) % 3) % 2 == 0][k]


def _format_bits(mask: int) -> int:
    data = (0b00 << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _penalty(m: list[list[int]]) -> int:
    n, score = len(m), 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for row in grid:
            run = 1
            for i in range(1, n):
                run = run + 1 if row[i] == row[i - 1] else 1
                if run == 5: score += 3
                elif run > 5: score += 1
            s = "".join(map(str, row))
            score += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(map(sum, m))
    score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return score


def encode(text: str) -> list[list[int]]:
    data = text.encode()
    version = next((v for v in range(1, 11) if len(data) + 2 + (v >= 10) <= _capacity(v)), 0)
    if not version:
        raise ValueError("That text is too long for the built-in QR code.")
    words = _codewords(data, version)
    return min((_matrix(version, words, k) for k in range(8)), key=_penalty)


def svg(text: str, border: int = 4) -> str:
    m = encode(text)
    n = len(m)
    path = "".join(f"M{c + border},{r + border}h1v1h-1z" for r in range(n) for c in range(n) if m[r][c])
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" aria-label="QR code">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
