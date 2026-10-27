"""Minimal ESRI shapefile + dBASE reader (polygons, polylines, attributes).

Enough for Natural Earth: shape types 3 (PolyLine) and 5 (Polygon), no Z/M.
"""
from __future__ import annotations

import struct
from pathlib import Path


def read_shp(path: Path) -> list[list[list[tuple[float, float]]]]:
    """Return one entry per record: a list of parts, each a list of (x, y)."""
    data = path.read_bytes()
    pos = 100
    out = []
    while pos < len(data):
        _num, length = struct.unpack(">ii", data[pos:pos + 8])
        rec = data[pos + 8: pos + 8 + length * 2]
        pos += 8 + length * 2
        stype = struct.unpack("<i", rec[:4])[0]
        if stype == 0:
            out.append([])
            continue
        if stype not in (3, 5):
            raise ValueError(f"unsupported shape type {stype}")
        nparts, npts = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts]))
        p0 = 44 + 4 * nparts
        pts = [struct.unpack("<dd", rec[p0 + 16 * i: p0 + 16 * i + 16]) for i in range(npts)]
        parts.append(npts)
        out.append([pts[parts[i]:parts[i + 1]] for i in range(nparts)])
    return out


def read_dbf(path: Path) -> list[dict]:
    data = path.read_bytes()
    nrec, hlen, rlen = struct.unpack("<IHH", data[4:12])
    fields = []
    p = 32
    while data[p] != 0x0D:
        name = data[p:p + 11].split(b"\0")[0].decode("ascii")
        ftype = chr(data[p + 11])
        flen = data[p + 16]
        fields.append((name, ftype, flen))
        p += 32
    rows = []
    for i in range(nrec):
        r = data[hlen + i * rlen: hlen + (i + 1) * rlen]
        off = 1
        row = {}
        for name, ftype, flen in fields:
            raw = r[off:off + flen].decode("utf-8", "replace").replace("\x00", "").strip()
            off += flen
            if ftype in ("N", "F"):
                try:
                    row[name] = float(raw) if raw else None
                except ValueError:
                    row[name] = None
            else:
                row[name] = raw
        rows.append(row)
    return rows
