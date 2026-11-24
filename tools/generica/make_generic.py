#!/usr/bin/env python3
"""APK genérica de Akane (adaptado del port de A Short Hike).

A partir de la compilación split binary de Unity (APK + OBB) y de una o varias copias del juego
(Steam Windows y Steam Linux; los datos van en Akane_Data/data.unity3d):
  - crea el «molde»: las entradas de la OBB con todo lo que viene del juego (texturas,
    audio y fuentes, también los de los bundles de Addressables) puesto a cero,
  - crea un manifiesto por copia con las órdenes para que la APK rellene el molde con los archivos
    del usuario (AkaneSetupActivity.java), más los bancos de sonido de FMOD que se copian tal cual,
  - comprueba que el resultado de rellenarlo es idéntico a la OBB original y calcula los CRC,
  - mete moldes y manifiestos en la APK (assets/akane/).

Uso: make_generic.py APK OBB SALIDA.apk VARIANTE=CARPETA_Akane_Data [VARIANTE=...]
     (descripciones de las variantes en tools/variants.txt)
"""
import hashlib
import io
import os
import struct
import sys
import tempfile
import zipfile
import zlib
from collections import defaultdict

import numpy as np
import UnityPy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unity_bundle as ash_bundle  # noqa: E402
from UnityPy.enums import TextureFormat

MIN_RUN = 64  # tramos iguales más cortos se quedan en el molde (texturas parcheadas)


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- DXT (idéntico a Java)
def decode_dxt(data, w, h, dxt5):
    bs = 16 if dxt5 else 8
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    b = np.frombuffer(data, np.uint8, bw * bh * bs).reshape(bw * bh, bs).astype(np.int64)
    n = len(b)
    out_a = None
    if dxt5:
        a0, a1 = b[:, 0], b[:, 1]
        tab = np.zeros((n, 8), np.int64)
        tab[:, 0], tab[:, 1] = a0, a1
        big = a0 > a1
        for i in range(1, 7):
            tab[:, i + 1] = np.where(big, ((7 - i) * a0 + i * a1) // 7, 0)
        for i in range(1, 5):
            tab[:, i + 1] = np.where(big, tab[:, i + 1], ((5 - i) * a0 + i * a1) // 5)
        tab[:, 6] = np.where(big, tab[:, 6], 0)
        tab[:, 7] = np.where(big, tab[:, 7], 255)
        bits = np.zeros(n, np.int64)
        for k in range(6):
            bits |= b[:, 2 + k] << (8 * k)
        aidx = (bits[:, None] >> (3 * np.arange(16))) & 7
        out_a = np.take_along_axis(tab, aidx, 1)
        cb = b[:, 8:16]
    else:
        cb = b
    c0 = cb[:, 0] | (cb[:, 1] << 8)
    c1 = cb[:, 2] | (cb[:, 3] << 8)

    def exp(c):
        return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31

    r0, g0, b0 = exp(c0)
    r1, g1, b1 = exp(c1)
    four = (c0 > c1) | dxt5
    pal = np.zeros((n, 4, 4), np.int64)  # bloque, índice, canal RGBA
    pal[:, 0] = np.stack([r0, g0, b0, np.full(n, 255)], 1)
    pal[:, 1] = np.stack([r1, g1, b1, np.full(n, 255)], 1)
    p2_4 = np.stack([(2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, np.full(n, 255)], 1)
    p3_4 = np.stack([(r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, np.full(n, 255)], 1)
    p2_3 = np.stack([(r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, np.full(n, 255)], 1)
    p3_3 = np.zeros((n, 4), np.int64)
    pal[:, 2] = np.where(four[:, None], p2_4, p2_3)
    pal[:, 3] = np.where(four[:, None], p3_4, p3_3)
    idx = cb[:, 4] | (cb[:, 5] << 8) | (cb[:, 6] << 16) | (cb[:, 7] << 24)
    ci = (idx[:, None] >> (2 * np.arange(16))) & 3
    px = np.take_along_axis(pal, ci[:, :, None].repeat(4, 2), 1)  # n,16,4
    if dxt5:
        px[:, :, 3] = out_a
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w].astype(np.uint8).tobytes()


BPP = {"RGBA32": 4, "ARGB32": 4, "BGRA32": 4, "ARGB4444": 2, "RGBA4444": 2, "RGB565": 2,
       "RGB24": 3, "Alpha8": 1, "R8": 1}


def level_size(fmt, w, h):
    if fmt in ("DXT1", "DXT5"):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == "DXT1" else 16)
    return w * h * BPP[fmt]


def levels(fmt, w, h, mips):
    out, off = [], 0
    for i in range(mips):
        lw, lh = max(1, w >> i), max(1, h >> i)
        s = level_size(fmt, lw, lh)
        out.append((off, s, lw, lh))
        off += s
    return out, off


# ---------------------------------------------------------------- lectura de objetos
def tex_info(o):
    t = o.read()
    sd = getattr(t, "m_StreamData", None)
    fmt = TextureFormat(t.m_TextureFormat).name
    mips = getattr(t, "m_MipCount", None) or (1 if not getattr(t, "m_MipMap", False) else None)
    return t, fmt, mips, sd


def find_in_raw(o, blob):
    raw = o.get_raw_data()
    pos = raw.rfind(blob)
    if pos < 0:
        raise RuntimeError("No se encuentran los datos dentro del objeto %s" % o.path_id)
    return o.byte_start + pos


class Loc:
    """Dónde están unos bytes: (archivo, posición, tamaño)."""
    def __init__(self, f, off, size):
        self.f, self.off, self.size = f, off, size


def texture_loc(o, t, sd, prefix=""):
    """prefix: "ruta/del.bundle|" para objetos dentro de un bundle."""
    if sd is not None and sd.size:
        return Loc(prefix + os.path.basename(sd.path), sd.offset, sd.size)
    data = bytes(t.image_data)
    return Loc(prefix + os.path.basename(o.assets_file.name), find_in_raw(o, data), len(data))


def load_dir(d):
    env = UnityPy.load(d)
    return env


# ---------------------------------------------------------------- copia del usuario
class Copy:
    """Una copia del juego (carpeta Akane_Data). Las fuentes "data.unity3d|nodo" son datos de dentro del bundle."""
    def __init__(self, data):
        self.data = data
        self.bundles = {}

    def size(self, name):
        return os.path.getsize(os.path.join(self.data, name.split("|")[0]))

    def unpacked(self, rel):
        if rel not in self.bundles:
            self.bundles[rel] = ash_bundle.unpack(os.path.join(self.data, rel))
        return self.bundles[rel]

    def read(self, name, off, size):
        if "|" in name:
            rel, node = name.split("|", 1)
            data, nodes = self.unpacked(rel)
            base = nodes[node][0]
            return data[base + off: base + off + size]
        with open(os.path.join(self.data, name), "rb") as fh:
            fh.seek(off)
            return fh.read(size)


BUNDLE = "data.unity3d"
BANKS = ["StreamingAssets/Master Bank.bank", "StreamingAssets/Master Bank.strings.bank"]


def index_copy(copy):
    """Texturas y fuentes de la copia del usuario. En Akane todo va en Akane_Data/data.unity3d."""
    data = copy.data
    log("Leyendo la copia:", data)
    tex, aud, fonts = defaultdict(list), defaultdict(list), {}
    prefix = BUNDLE + "|"
    for o in UnityPy.load(os.path.join(data, BUNDLE)).objects:
        if o.assets_file is None:
            continue
        tn = o.type.name
        if tn == "Texture2D":
            t, fmt, mips, sd = tex_info(o)
            if t.m_Width == 0:
                continue
            loc = texture_loc(o, t, sd, prefix)
            mips = mips or 1
            lv, total = levels(fmt, t.m_Width, t.m_Height, mips) if fmt in BPP or fmt in ("DXT1", "DXT5") else ([], -1)
            if total != loc.size:
                log("  aviso: tamaño inesperado en", t.m_Name, fmt, total, loc.size)
            try:
                img = np.array(t.image.convert("RGBA"))
            except Exception:
                img = None
            tex[t.m_Name].append(dict(name=t.m_Name, w=t.m_Width, h=t.m_Height, fmt=fmt, mips=mips, loc=loc, img=img))
        elif tn == "AudioClip":
            a = o.read()
            r = a.m_Resource
            aud[a.m_Name].append(dict(name=a.m_Name, loc=Loc(prefix + os.path.basename(r.m_Source), r.m_Offset, r.m_Size),
                                      fmt=a.m_CompressionFormat, freq=a.m_Frequency, ch=a.m_Channels,
                                      bits=a.m_BitsPerSample, length=a.m_Length))
        elif tn == "Font":
            f = o.read()
            fd = bytes(bytearray(f.m_FontData)) if f.m_FontData else b""
            if len(fd) > 1024:
                fonts[hashlib.sha1(fd).hexdigest()] = Loc(prefix + os.path.basename(o.assets_file.name), find_in_raw(o, fd), len(fd))
    log("  texturas %d, audios %d, fuentes %d" % (sum(map(len, tex.values())), sum(map(len, aud.values())), len(fonts)))
    return tex, aud, fonts


def bank_lines(copy):
    """Bancos de FMOD: la APK los copia tal cual (comprobando tamaño y CRC) a files/fmod/."""
    out = []
    for rel in BANKS:
        p = os.path.join(copy.data, rel)
        with open(p, "rb") as fh:
            d = fh.read()
        out.append("B\t%s\t%d\t%08x" % (rel, len(d), zlib.crc32(d) & 0xFFFFFFFF))
    return out


# ---------------------------------------------------------------- generación
class Gen:
    def __init__(self, obb, copy):
        self.copy = copy
        self.zobb = zipfile.ZipFile(obb)
        self.entries = [i for i in self.zobb.infolist() if not i.is_dir()]
        self.tmp = tempfile.mkdtemp(prefix="obb_")
        self.zobb.extractall(self.tmp)
        # Archivos lógicos: los .splitN de Unity se tratan como un solo archivo
        import re
        self.chunks = defaultdict(list)  # nombre lógico (ruta completa) -> [(n, entrada)]
        for e in self.entries:
            m = re.match(r"(.*)\.split(\d+)$", e.filename)
            if m:
                self.chunks[m.group(1)].append((int(m.group(2)), e.filename))
            else:
                self.chunks[e.filename].append((0, e.filename))
        self.molde = {}
        for lg, lst in self.chunks.items():
            lst.sort()
            self.molde[lg] = bytearray(b"".join(self.zobb.read(n) for _, n in lst))
        self.by_base = {}
        for lg in self.chunks:
            self.by_base.setdefault(os.path.basename(lg), lg)
        self.cmds = defaultdict(list)  # entrada -> [(dst, len, src, srcOff, srcLen, mode, w, h)]
        self.srcs = {}
        self.report = defaultdict(int)
        self.port_items = []

    def src(self, name):
        if name not in self.srcs:
            self.srcs[name] = self.copy.size(name)
        return name

    def entry(self, base):
        e = self.by_base.get(base)
        if e is None:
            raise RuntimeError("No está en la OBB: " + base)
        return e

    def fill(self, entry, dst, length, src, srcoff, srclen, mode, w=0, h=0):
        self.molde[entry][dst:dst + length] = bytes(length)
        self.cmds[entry].append((dst, length, self.src(src), srcoff, srclen, mode, w, h))

    # ----- texturas
    def textures(self, stex):
        data_dir = self.data_dir()
        env = load_dir(data_dir)
        for o in env.objects:
            if o.type.name != "Texture2D" or o.assets_file is None:
                continue
            t, fmt, mips, sd = tex_info(o)
            if t.m_Width == 0:
                continue
            mips = mips or 1
            import re
            names = {t.m_Name, re.sub(r"_\d+$", "", t.m_Name)}  # el ripeo añadió _N a los nombres repetidos
            cands = [s for n in names for s in stex.get(n, []) if s["w"] == t.m_Width and s["h"] == t.m_Height]
            if not cands:
                self.port_items.append("textura %s %dx%d" % (t.m_Name, t.m_Width, t.m_Height))
                continue
            if fmt not in BPP and fmt not in ("DXT1", "DXT5"):
                self.port_items.append("textura %s %dx%d (%s en la OBB)" % (t.m_Name, t.m_Width, t.m_Height, fmt))
                continue
            try:
                img = np.array(t.image.convert("RGBA"))
            except Exception:
                img = None
            best, bestd = None, None
            for s in cands:
                if img is None or s["img"] is None:
                    d = 1e9
                else:
                    # Unity rellena el color de los píxeles transparentes al importar: no cuenta
                    vis = (img[..., 3] > 0) | (s["img"][..., 3] > 0)
                    d = float((np.abs(img.astype(int) - s["img"].astype(int)).max(-1) * vis).mean())
                if bestd is None or d < bestd:
                    best, bestd = s, d
            s = best
            loc = texture_loc(o, t, sd)
            entry = self.entry(loc.f) if sd is not None and sd.size else self.entry_of(o)
            lv_o, tot_o = levels(fmt, t.m_Width, t.m_Height, mips)
            if tot_o != loc.size:
                raise RuntimeError("Tamaño raro en la OBB: %s %s %d/%d" % (t.m_Name, fmt, tot_o, loc.size))
            if s["mips"] != mips:
                log("  aviso: mipmaps distintos en %s (copia %d, OBB %d): se queda en el molde" % (t.m_Name, s["mips"], mips))
                self.port_items.append("textura %s (mipmaps)" % t.m_Name)
                continue
            lv_s, _ = levels(s["fmt"], s["w"], s["h"], s["mips"])
            dxt = s["fmt"] in ("DXT1", "DXT5")
            if dxt:
                if fmt != "RGBA32":
                    log("  aviso: %s DXT en la copia pero %s en la OBB: se queda en el molde" % (t.m_Name, fmt))
                    self.port_items.append("textura %s (DXT/%s)" % (t.m_Name, fmt))
                    continue
                mode = "dxt5" if s["fmt"] == "DXT5" else "dxt1"
                for (oo, osz, lw, lh), (so, ssz, _, _) in zip(lv_o, lv_s):
                    self.fill(entry, loc.off + oo, osz, s["loc"].f, s["loc"].off + so, ssz, mode, lw, lh)
                self.report["texturas DXT"] += 1
                continue
            if s["fmt"] != fmt:
                log("  aviso: %s con formato %s en la copia y %s en la OBB: se queda en el molde" % (t.m_Name, s["fmt"], fmt))
                self.port_items.append("textura %s (%s/%s)" % (t.m_Name, s["fmt"], fmt))
                continue
            exact = bestd == 0
            if exact:
                self.fill(entry, loc.off, loc.size, s["loc"].f, s["loc"].off, loc.size, "copy")
                self.report["texturas idénticas"] += 1
                continue
            # Parcheada (fuentes con acentos): nivel 0 por tramos iguales, mipmaps de Steam
            o0, sz0 = lv_o[0][0], lv_o[0][1]
            ob = np.frombuffer(bytes(self.molde[entry][loc.off + o0: loc.off + o0 + sz0]), np.uint8)
            sb = np.frombuffer(self.read_steam(s["loc"].f, s["loc"].off, sz0), np.uint8)
            eq = ob == sb
            if fmt == "RGBA32":
                # píxel igual si coincide entero o es transparente en los dos
                op, sp = ob.reshape(-1, 4), sb.reshape(-1, 4)
                peq = (op == sp).all(1) | ((op[:, 3] == 0) & (sp[:, 3] == 0))
                eq = np.repeat(peq, 4)
            kept = 0
            i = 0
            n = len(eq)
            # tramos de bytes iguales
            change = np.flatnonzero(np.diff(eq.astype(np.int8))) + 1
            bounds = np.concatenate([[0], change, [n]])
            for a, b in zip(bounds[:-1], bounds[1:]):
                if eq[a] and b - a >= MIN_RUN:
                    self.fill(entry, loc.off + o0 + a, b - a, s["loc"].f, s["loc"].off + a, b - a, "copy")
                else:
                    kept += b - a
            for (oo, osz, _, _), (so, ssz, _, _) in list(zip(lv_o, lv_s))[1:]:
                self.fill(entry, loc.off + oo, osz, s["loc"].f, s["loc"].off + so, osz, "copy")
            log("  parcheada %s %dx%d: %d bytes propios del port en el molde (%.1f %%)"
                % (t.m_Name, t.m_Width, t.m_Height, kept, 100.0 * kept / sz0))
            self.report["texturas parcheadas"] += 1

    def read_steam(self, f, off, size):
        return self.copy.read(f, off, size)

    def data_dir(self):
        # carpeta extraída donde están los archivos serializados de la OBB
        for e in self.entries:
            if os.path.basename(e.filename) == "globalgamemanagers" or e.filename.endswith("/level0") \
                    or "sharedassets" in e.filename:
                return os.path.join(self.tmp, os.path.dirname(e.filename))
        return os.path.join(self.tmp, "assets/bin/Data")

    def entry_of(self, o):
        return self.entry(os.path.basename(o.assets_file.name))

    # ----- audio
    def audio(self, saud):
        env = load_dir(self.data_dir())
        clips = defaultdict(list)  # recurso -> [(offset, size, objeto, clip, steam)]
        for o in env.objects:
            if o.type.name != "AudioClip" or o.assets_file is None:
                continue
            a = o.read()
            r = a.m_Resource
            cands = saud.get(a.m_Name, [])
            s = None
            if cands:
                s = min(cands, key=lambda c: (abs(c["length"] - a.m_Length), c["ch"] != a.m_Channels))
                if abs(s["length"] - a.m_Length) > 0.05:
                    log("  aviso: duración distinta en", a.m_Name, s["length"], a.m_Length)
            if s is None:
                self.port_items.append("audio " + a.m_Name)
            clips[os.path.basename(r.m_Source)].append((r.m_Offset, r.m_Size, o, a, s))
        for res, lst in clips.items():
            entry = self.entry(res)
            old = bytes(self.molde[entry])
            new = bytearray()
            pending = []
            for off, size, o, a, s in sorted(lst, key=lambda x: x[0]):
                while len(new) % 32:
                    new.append(0)
                pos = len(new)
                if s is None:
                    new += old[off:off + size]
                    nsize = size
                else:
                    nsize = s["loc"].size
                    new += bytes(nsize)
                    pending.append((pos, nsize, s))
                    self.report["audios"] += 1
                self.patch_clip(o, a, pos, nsize, s)
            self.molde[entry] = new
            for pos, nsize, s in pending:
                self.cmds[entry].append((pos, nsize, self.src(s["loc"].f), s["loc"].off, nsize, "copy", 0, 0))

    def patch_clip(self, o, a, offset, size, s):
        entry = self.entry_of(o)
        buf = self.molde[entry]
        end = o.byte_start + o.byte_size
        # Últimos 20 bytes: m_Offset u64, m_Size u64, m_CompressionFormat i32
        tail = struct.unpack_from("<QQi", buf, end - 20)
        r = a.m_Resource
        if tail != (r.m_Offset, r.m_Size, a.m_CompressionFormat):
            raise RuntimeError("Estructura de AudioClip inesperada en %s: %r" % (a.m_Name, tail))
        fmt = a.m_CompressionFormat if s is None else s["fmt"]
        struct.pack_into("<QQi", buf, end - 20, offset, size, fmt)
        if s is not None:
            # Tras m_Name: m_LoadType, m_Channels, m_Frequency, m_BitsPerSample (i32), m_Length (f32)
            nlen = struct.unpack_from("<i", buf, o.byte_start)[0]
            p = o.byte_start + 4 + ((nlen + 3) & ~3) + 4
            cur = struct.unpack_from("<iiif", buf, p)
            if cur[0] != a.m_Channels or cur[1] != a.m_Frequency or cur[2] != a.m_BitsPerSample:
                raise RuntimeError("Campos de AudioClip inesperados en %s: %r" % (a.m_Name, cur))
            struct.pack_into("<iiif", buf, p, s["ch"], s["freq"], s["bits"], s["length"])

    # ----- fuentes TTF
    def fonts(self, sfonts):
        env = load_dir(self.data_dir())
        for o in env.objects:
            if o.type.name != "Font" or o.assets_file is None:
                continue
            f = o.read()
            data = bytes(bytearray(f.m_FontData)) if f.m_FontData else b""
            if len(data) <= 1024:
                continue
            s = sfonts.get(hashlib.sha1(data).hexdigest())
            if s is None:
                self.port_items.append("fuente %s (%d bytes)" % (f.m_Name, len(data)))
                continue
            pos = find_in_raw(o, data)
            self.fill(self.entry_of(o), pos, len(data), s.f, s.off, len(data), "copy")
            self.report["fuentes"] += 1

    # ----- reconstrucción (igual que hará la APK) y manifiesto
    def locate(self, entry):
        """Entrada de la OBB -> (archivo lógico, posición, tamaño)."""
        for lg, lst in self.chunks.items():
            pos = 0
            for _, n in lst:
                size = self.zobb.getinfo(n).file_size
                if n == entry:
                    return lg, pos, size
                pos += size
        raise KeyError(entry)

    def rebuild(self, entry):
        out = bytearray(self.molde[entry])
        for dst, ln, src, so, sl, mode, w, h in self.cmds[entry]:
            raw = self.copy.read(src, so, sl)
            if mode == "copy":
                data = raw
            else:
                data = decode_dxt(raw, w, h, mode == "dxt5")
            if len(data) != ln:
                raise RuntimeError("Longitud distinta en %s" % entry)
            out[dst:dst + ln] = data
        return bytes(out)

    def write(self):
        """Devuelve (manifiesto, {nombre_molde: datos}, resumen de entradas)."""
        for lg in self.chunks:
            self.cmds[lg].sort()
            last = 0
            for c in self.cmds[lg]:
                if c[0] < last:
                    raise RuntimeError("Órdenes solapadas en " + lg)
                last = c[0] + c[1]
        body = []
        for name in sorted(self.srcs):
            body.append("S\t%s\t%d" % (name, self.srcs[name]))
        moldes = {}
        entries = []
        total_ok = 0
        rebuilt = {lg: self.rebuild(lg) for lg in self.chunks}
        for e in self.entries:
            lg, start, size = self.locate(e.filename)
            data = rebuilt[lg][start:start + size]
            if len(data) != e.file_size and len(self.chunks[lg]) > 1:
                raise RuntimeError("Trozo con tamaño distinto: " + e.filename)
            if len(self.chunks[lg]) == 1:
                data = rebuilt[lg]
            crc = zlib.crc32(data) & 0xFFFFFFFF
            same = data == self.zobb.read(e)
            total_ok += same  # las de audio cambian a propósito (se usa el audio original del juego)
            mdata = bytes(self.molde[lg][start:start + len(data)])
            mname = hashlib.sha1(mdata).hexdigest()[:16]
            moldes[mname] = mdata
            entries.append((e.filename, len(data), crc))
            body.append("F\t%s\t%d\t%08x\t%s" % (e.filename, len(data), crc, mname))
            for c in self.cmds[lg]:
                a, b = max(c[0], start), min(c[0] + c[1], start + len(data))
                if a >= b:
                    continue
                skip = 0
                if (a, b) != (c[0], c[0] + c[1]):
                    d = a - c[0]
                    if c[5] == "copy":
                        c2 = (a - start, b - a, c[2], c[3] + d, b - a, "copy", 0, 0)
                    else:
                        # textura DXT partida entre dos trozos: se descomprime entera y se escribe solo su parte
                        c2 = (a - start, b - a) + c[2:]
                        skip = d
                else:
                    c2 = (c[0] - start,) + c[1:]
                line = "C\t%d\t%d\t%s\t%d\t%d\t%s\t%d\t%d" % c2
                if skip:
                    line += "\t%d" % skip
                body.append(line)
        log("Entradas idénticas a la compilación original: %d de %d (las demás llevan el audio o las texturas del juego tal cual)"
            % (total_ok, len(self.entries)))
        mid = hashlib.sha1("\n".join(body).encode()).hexdigest()[:12]
        manifest = "# Manifiesto de la APK genérica (generado por tools/make_generic.py)\nV\t%s\n" % mid + "\n".join(body) + "\n"
        log("Manifiesto %s: %d órdenes, %d fuentes" % (mid, sum(len(v) for v in self.cmds.values()), len(self.srcs)))
        return manifest, moldes, entries


def check_apk_clean(apk):
    """La APK (sin la OBB) no debe llevar texturas, audio ni fuentes del juego."""
    d = tempfile.mkdtemp(prefix="apk_")
    with zipfile.ZipFile(apk) as z:
        names = [n for n in z.namelist() if n.startswith("assets/bin/Data/") and "/Managed/" not in n]
        for n in names:
            z.extract(n, d)
    env = UnityPy.load(os.path.join(d, "assets/bin/Data"))
    found = []
    for o in env.objects:
        if o.type.name in ("Texture2D", "AudioClip", "Font"):
            try:
                found.append("%s %s" % (o.type.name, o.read().m_Name))
            except Exception:
                found.append(o.type.name)
    with zipfile.ZipFile(apk) as z:
        found += ["banco " + n for n in z.namelist() if n.lower().endswith(".bank")]
    log("Archivos de datos dentro de la APK:", ", ".join(os.path.basename(n) for n in names))
    log("Texturas/audio/fuentes dentro de la APK:", found or "ninguna")
    return found


def main():
    apk, obb, out = sys.argv[1:4]
    variants = [a.split("=", 1) for a in sys.argv[4:]]
    in_apk = check_apk_clean(apk)
    desc = {}
    vt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "variants.txt")
    for line in open(vt, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            p = line.rstrip("\n").split("\t")
            desc[p[0]] = line.rstrip("\n")
    manifests, moldes, ref_entries, reports = {}, {}, None, []
    for name, data in variants:
        log("=== Variante", name)
        copy = Copy(data)
        stex, saud, sfonts = index_copy(copy)
        g = Gen(obb, copy)
        log("Texturas…")
        g.textures(stex)
        log("Audio…")
        g.audio(saud)
        log("Fuentes…")
        g.fonts(sfonts)
        log("Resumen:", dict(g.report))
        log("Elementos propios del port o que se quedan en el molde:")
        for p in g.port_items:
            log("  ", p)
        man, mol, entries = g.write()
        man += "\n".join(bank_lines(copy)) + "\n"
        if ref_entries is None:
            ref_entries = entries
        elif entries != ref_entries:
            raise RuntimeError("La variante %s produce una OBB distinta" % name)
        manifests[name] = man
        moldes.update(mol)
        reports.append("%s: %r\nPropios/molde:\n%s\n" % (name, dict(g.report), "\n".join(g.port_items)))
    with zipfile.ZipFile(apk) as zi, zipfile.ZipFile(out, "w") as zo:
        for it in zi.infolist():
            if it.filename.startswith("META-INF/"):
                continue  # se vuelve a firmar
            zo.writestr(it, zi.read(it), compress_type=it.compress_type)
        zo.writestr("assets/akane/variants.txt", "\n".join(desc[n] for n, _ in variants) + "\n", compress_type=zipfile.ZIP_DEFLATED)
        for name, man in manifests.items():
            zo.writestr("assets/akane/manifest-%s.txt" % name, man, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in moldes.items():
            zi2 = zipfile.ZipInfo("assets/akane/molde/" + name, (2020, 1, 1, 0, 0, 0))
            zo.writestr(zi2, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    log("APK genérica:", out, "moldes:", len(moldes), "MB molde:", sum(map(len, moldes.values())) >> 20)
    with open(os.path.join(os.path.dirname(os.path.abspath(out)), "informe-generica.txt"), "w") as f:
        f.write("En la APK: %r\n\n%s" % (in_apk, "\n".join(reports)))


if __name__ == "__main__":
    main()
