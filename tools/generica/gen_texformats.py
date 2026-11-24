#!/usr/bin/env python3
"""Genera la lista de formatos de textura para la APK genérica de Akane: para cada textura del proyecto,
el formato que tiene en la versión de PC (dentro de Akane_Data/data.unity3d). Las DXT pasan a RGBA32
(la APK genérica las descomprime de la copia del usuario).
Uso: gen_texformats.py UnityProject/Assets  CARPETA_Akane_Data  salida.tsv"""
import os
import re
import sys
from collections import defaultdict

import UnityPy
from UnityPy.enums import TextureFormat

assets, data, out = sys.argv[1:4]
MAP = {"DXT1": "RGBA32", "DXT5": "RGBA32", "RGBA32": "RGBA32", "ARGB32": "ARGB32", "RGB24": "RGB24",
       "Alpha8": "Alpha8", "ARGB4444": "ARGB16", "RGBA4444": "RGBA16"}
env = UnityPy.load(os.path.join(data, "data.unity3d"))
pc = defaultdict(list)
for o in env.objects:
    if o.type.name != "Texture2D":
        continue
    t = o.read()
    if t.m_Width == 0:
        continue
    mips = getattr(t, "m_MipCount", 1) or 1
    pc[t.m_Name].append((TextureFormat(t.m_TextureFormat).name, mips > 1, t.m_Width, t.m_Height))
rows, missing = [], []
for root, _, files in os.walk(assets):
    if "/Resources/AkaneTouch" in root or "/PortAndroid" in root or "/Editor" in root:
        continue
    for f in files:
        if not f.lower().endswith((".png", ".tga", ".exr", ".jpg")):
            continue
        stem = os.path.splitext(f)[0]
        cands = pc.get(stem) or pc.get(re.sub(r"_\d+$", "", stem))
        rel = os.path.relpath(os.path.join(root, f), os.path.dirname(assets))
        if not cands:
            missing.append(rel)
            continue
        fmt, mip, _, _ = cands[0]
        if fmt not in MAP:
            missing.append(rel + " (" + fmt + ")")
            continue
        rows.append("%s\t%s\t%d" % (rel, MAP[fmt], 1 if mip else 0))
rows.sort()
with open(out, "w") as fh:
    fh.write("# ruta\tformato en Android\tmipmaps  (generado por tools/generica/gen_texformats.py)\n" + "\n".join(rows) + "\n")
print("texturas:", len(rows), "sin pareja:", len(missing))
for m in missing:
    print("  ", m)
