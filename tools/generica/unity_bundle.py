#!/usr/bin/env python3
"""Lector mínimo de AssetBundles UnityFS (el mismo que hace AkaneBundle.java en la APK).
unpack(path) -> (datos descomprimidos, {nodo: (posición, tamaño)})"""
import struct

import lz4.block


def _cstr(b, p):
    e = b.index(b"\0", p)
    return b[p:e].decode("utf-8"), e + 1


def _decomp(data, usize, comp):
    if comp == 0:
        return data
    if comp in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=usize)
    raise ValueError("Compresión de bundle no soportada: %d" % comp)


def unpack(path):
    with open(path, "rb") as f:
        b = f.read()
    sig, p = _cstr(b, 0)
    if sig != "UnityFS":
        raise ValueError("No es UnityFS: " + path)
    ver = struct.unpack_from(">i", b, p)[0]
    p += 4
    _, p = _cstr(b, p)
    _, p = _cstr(b, p)
    size, csize, usize, flags = struct.unpack_from(">qIII", b, p)
    p += 20
    if ver >= 7:
        p = (p + 15) & ~15
    if flags & 0x80:
        info_raw = b[size - csize:size] if size <= len(b) else b[len(b) - csize:]
    else:
        info_raw = b[p:p + csize]
        p += csize
    info = _decomp(info_raw, usize, flags & 0x3F)
    if not (flags & 0x80) and (flags & 0x200):
        p = (p + 15) & ~15
    q = 16
    nblocks = struct.unpack_from(">i", info, q)[0]
    q += 4
    blocks = []
    for _ in range(nblocks):
        u, c, fl = struct.unpack_from(">IIH", info, q)
        q += 10
        blocks.append((u, c, fl))
    nnodes = struct.unpack_from(">i", info, q)[0]
    q += 4
    nodes = {}
    for _ in range(nnodes):
        off, sz, fl = struct.unpack_from(">qqI", info, q)
        q += 20
        name, q = _cstr(info, q)
        nodes[name] = (off, sz)
    out = bytearray()
    for u, c, fl in blocks:
        out += _decomp(b[p:p + c], u, fl & 0x3F)
        p += c
    return bytes(out), nodes


if __name__ == "__main__":
    import sys
    d, n = unpack(sys.argv[1])
    print(len(d), n)
