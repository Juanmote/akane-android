package com.juanmote.akane;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;

// Descomprime un AssetBundle UnityFS (LZ4) de la copia del usuario a un archivo temporal.
// La APK genérica saca de ahí las texturas y las fuentes de data.unity3d (igual que tools/generica/unity_bundle.py).
public class AkaneBundle {
    // nodo -> {posición, tamaño} dentro de los datos descomprimidos
    public final HashMap<String, long[]> nodes = new HashMap<String, long[]>();

    static long readFully(FileChannel ch, long pos, byte[] b, int len) throws IOException {
        ByteBuffer bb = ByteBuffer.wrap(b, 0, len);
        long p = pos;
        while (bb.hasRemaining()) {
            int n = ch.read(bb, p);
            if (n < 0) throw new IOException("Bundle corto");
            p += n;
        }
        return p;
    }

    static int be32(byte[] b, int o) {
        return ((b[o] & 255) << 24) | ((b[o + 1] & 255) << 16) | ((b[o + 2] & 255) << 8) | (b[o + 3] & 255);
    }

    static long be64(byte[] b, int o) {
        return ((long) be32(b, o) << 32) | (be32(b, o + 4) & 0xFFFFFFFFL);
    }

    static int be16(byte[] b, int o) {
        return ((b[o] & 255) << 8) | (b[o + 1] & 255);
    }

    static int cstrEnd(byte[] b, int p) {
        while (b[p] != 0) p++;
        return p;
    }

    // Descompresión LZ4 de un bloque (formato "block", sin cabecera de marco)
    static void lz4(byte[] src, int sLen, byte[] dst, int dLen) throws IOException {
        int s = 0, d = 0;
        while (s < sLen) {
            int token = src[s++] & 255;
            int lit = token >>> 4;
            if (lit == 15) {
                int v;
                do { v = src[s++] & 255; lit += v; } while (v == 255);
            }
            System.arraycopy(src, s, dst, d, lit);
            s += lit;
            d += lit;
            if (s >= sLen) break;
            int off = (src[s] & 255) | ((src[s + 1] & 255) << 8);
            s += 2;
            int ml = token & 15;
            if (ml == 15) {
                int v;
                do { v = src[s++] & 255; ml += v; } while (v == 255);
            }
            ml += 4;
            int from = d - off;
            if (off <= 0 || from < 0) throw new IOException("LZ4 corrupto");
            for (int i = 0; i < ml; i++) dst[d++] = dst[from++];
        }
        if (d != dLen) throw new IOException("LZ4: tamaño " + d + " / " + dLen);
    }

    static byte[] decomp(byte[] src, int sLen, int uLen, int comp) throws IOException {
        if (comp == 0) {
            if (sLen == src.length) return src;
            byte[] o = new byte[sLen];
            System.arraycopy(src, 0, o, 0, sLen);
            return o;
        }
        if (comp == 2 || comp == 3) {
            byte[] o = new byte[uLen];
            lz4(src, sLen, o, uLen);
            return o;
        }
        throw new IOException("Compresión de bundle no soportada: " + comp);
    }

    // Lee el bundle y escribe sus datos descomprimidos en 'out'
    public void unpack(FileChannel ch, File out) throws IOException {
        long fileSize = ch.size();
        byte[] head = new byte[(int) Math.min(4096, fileSize)];
        readFully(ch, 0, head, head.length);
        int p = cstrEnd(head, 0);
        if (!"UnityFS".equals(new String(head, 0, p, StandardCharsets.US_ASCII))) throw new IOException("No es un bundle UnityFS");
        p++;
        int ver = be32(head, p); p += 4;
        p = cstrEnd(head, p) + 1;
        p = cstrEnd(head, p) + 1;
        long size = be64(head, p); p += 8;
        int csize = be32(head, p); p += 4;
        int usize = be32(head, p); p += 4;
        int flags = be32(head, p); p += 4;
        long pos = p;
        if (ver >= 7) pos = (pos + 15) & ~15L;
        byte[] infoRaw = new byte[csize];
        if ((flags & 0x80) != 0) {
            readFully(ch, Math.min(size, fileSize) - csize, infoRaw, csize);
        } else {
            readFully(ch, pos, infoRaw, csize);
            pos += csize;
            if ((flags & 0x200) != 0) pos = (pos + 15) & ~15L;
        }
        byte[] info = decomp(infoRaw, csize, usize, flags & 0x3F);
        int q = 16;
        int nb = be32(info, q); q += 4;
        int[] bu = new int[nb], bc = new int[nb], bf = new int[nb];
        int maxC = 0, maxU = 0;
        for (int i = 0; i < nb; i++) {
            bu[i] = be32(info, q); bc[i] = be32(info, q + 4); bf[i] = be16(info, q + 8);
            q += 10;
            maxC = Math.max(maxC, bc[i]); maxU = Math.max(maxU, bu[i]);
        }
        int nn = be32(info, q); q += 4;
        for (int i = 0; i < nn; i++) {
            long off = be64(info, q), sz = be64(info, q + 8);
            q += 20;
            int e = cstrEnd(info, q);
            nodes.put(new String(info, q, e - q, StandardCharsets.UTF_8), new long[]{off, sz});
            q = e + 1;
        }
        byte[] cbuf = new byte[maxC];
        BufferedOutputStream os = new BufferedOutputStream(new FileOutputStream(out), 1 << 20);
        try {
            for (int i = 0; i < nb; i++) {
                pos = readFully(ch, pos, cbuf, bc[i]);
                os.write(decomp(cbuf, bc[i], bu[i], bf[i] & 0x3F), 0, bu[i]);
            }
        } finally {
            os.close();
        }
    }
}
