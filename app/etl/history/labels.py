"""Polity label anchors per slice/variant, each side's colour hue + the road line used for flow.

Hue: neighbouring sides (leading on either side of a cell edge in any slice) get hues far apart,
so two empires sharing a border are never one red (side_hues; the app's hand-picked colours for
the great powers still take precedence).

Anchor = the cell deepest inside the side's leading region (max of a cheap
inward-erosion depth), so labels sit in the body of a territory, not on a
border. Road: Grand Trunk Road course from pipeline/influence.py (GT_ROAD).
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
from PIL import Image

from etl import polity_qids
from etl.common import CFG, LAT1, LON0, OUT, ROOT, SCACHE, SCENE, write_json

sys.path.insert(0, str(ROOT))
from pipeline import influence as INF  # noqa: E402


def load_top(meta: dict, variant: str, year) -> tuple[np.ndarray, np.ndarray]:
    """(leading side index per cell, its strength) for one slice; index -1 = nobody."""
    nx, ny, T = meta["width"], meta["height"], meta["tiles"]
    fn = OUT / "fields" / f"{variant}_{year}.png"
    if not fn.exists() and float(year).is_integer():
        fn = OUT / "fields" / f"{variant}_{int(year)}.png"
    raw = np.asarray(Image.open(fn))
    if meta.get("format") == "topk":
        hi = raw[:, 2 * nx:, 2].astype(np.int32) >> 4
        ids = raw[:, :nx, 0].astype(np.int32) + 256 * hi
        return ids - 1, raw[:, nx:2 * nx, 0].astype(np.float32) / 255
    cols = meta.get("cols", T + 1)
    a = raw.astype(np.float32) / 255
    K = len(meta["sides"])
    S = np.zeros((K, ny, nx), np.float32)
    for k in range(K):
        t, ch = divmod(k, 4)
        r0, c0 = divmod(t, cols)
        S[k] = a[r0 * ny:(r0 + 1) * ny, c0 * nx:(c0 + 1) * nx, ch]
    return S.argmax(0), S.max(0)


# a polity's name in a given year where it changed inside the scene window (manifest etl.era_names:
# side -> [[until_year, name], ...])
ERA_NAMES = CFG.get("era_names", {})


def source_names() -> dict[str, list[tuple[float, float, str]]]:
    """Cliopatria's own name for each side's rows (side -> [(from, to, name)]): a side is one power
    across its names ("Habsburg Monarchy" and "Austria-Hungary" are both austria-hungary), so a
    label in 1630 should use the name its row has then, not the side's latest name."""
    if not any((b if isinstance(b, str) else b["source"]) == "cliopatria" for b in CFG.get("borders", [])):
        return {}
    p = SCACHE / "geo" / "cliopatria.geojson"
    if not p.exists():
        return {}
    from etl.history.border_sides import BY_CLIO, SIDES, slug
    out: dict[str, list[tuple[float, float, str]]] = {}
    for f in json.loads(p.read_text())["features"]:
        pr = f["properties"]
        top = pr["member_of"] or pr["name"]
        sid = BY_CLIO.get(top) or BY_CLIO.get(pr["name"]) or slug(top)
        if sid in SIDES and SIDES[sid]["name"] != top:
            out.setdefault(sid, []).append((float(pr["from"]), float(pr["to"]) + 1, top))
    return out


SOURCE_NAMES = source_names()


def era_name(side: str, y: float) -> str | None:
    for until, name in ERA_NAMES.get(side, []):
        if y < until:
            return name
    rows = [n for y0, y1, n in SOURCE_NAMES.get(side, []) if y0 <= y < y1]
    return max(set(rows), key=rows.count) if rows else None


def border_source(meta: dict, side: str, y: float) -> str | None:
    """Where a side's borders on the map come from in year y: the source row drawing it then
    (fields.json "ohm", the firmly held rows), else the period's one observed source."""
    rows = [o.get("source", "ohm") for o in meta.get("ohm", []) if o["side"] == side and o["y0"] <= y < o["y1"]]
    if rows:
        return max(set(rows), key=rows.count)
    obs = meta.get("provenance", {}).get("observed") or []
    obs = [obs] if isinstance(obs, str) else obs
    if "cliopatria" in obs and (len(obs) == 1 or set(obs) <= {"cliopatria", "cshapes2"}):
        return "cliopatria"
    return obs[0] if len(obs) == 1 else None


def depth(mask: np.ndarray) -> np.ndarray:
    d = np.zeros(mask.shape, np.int32)
    cur = mask.copy()
    i = 0
    while cur.any() and i < 60:
        d += cur
        n = cur.copy()
        n[1:, :] &= cur[:-1, :]
        n[:-1, :] &= cur[1:, :]
        n[:, 1:] &= cur[:, :-1]
        n[:, :-1] &= cur[:, 1:]
        cur = n
        i += 1
    return d


def hash_hue(side: str) -> int:
    """The hue the app falls back to (src/lib/themes.ts sideColor): FNV-1a of the id, skipping the
    terrain's own yellows and yellow-greens (35-95)."""
    h = 2166136261
    for ch in side:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    raw = h % 300
    return raw if raw < 35 else raw + 60


def hand_hues() -> dict[str, int]:
    """The great powers' hand-picked colours (Living Relief's, src/lib/themes.ts), as hues: they
    win over any chosen here, so the others keep clear of them."""
    import colorsys
    import re
    src = (ROOT / "app" / "src" / "lib" / "themes.ts")
    if not src.exists():
        src = ROOT / "src" / "lib" / "themes.ts"
    m = re.search(r"^\s*living: \{([^}]*spain[^}]*)\}", src.read_text(), re.M) if src.exists() else None
    out = {}
    for sid, hx in re.findall(r"'?([\w-]+)'?: '#([0-9a-f]{6})'", m.group(1) if m else ""):
        r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4))
        out[sid] = round(colorsys.rgb_to_hls(r, g, b)[0] * 360) % 360
    return out


def side_hues(sides: list[dict], touch: dict[tuple[int, int], int], area: dict[int, int]) -> dict[str, int]:
    """A hue for each side: its familiar hashed one, unless a neighbour it shares real border with
    (two empires side by side) is within 25 degrees of it, when it takes the nearest hue at least
    40 degrees from all its neighbours' (or, if none is, the one farthest from them). Sides with
    the most border are settled first."""
    hues = [h for h in range(0, 360, 5) if not 35 <= h < 95]
    circ = lambda a, b: min(abs(a - b), 360 - abs(a - b))   # noqa: E731
    total: dict[int, int] = {}
    for (a, b), n in touch.items():
        total[a] = total.get(a, 0) + n
        total[b] = total.get(b, 0) + n
    nb: dict[int, dict[int, float]] = {}
    for (a, b), n in touch.items():
        # real border: a few percent of either side's border over the period, not a stray cell
        if n >= 0.03 * min(total[a], total[b]) and n >= 20:
            nb.setdefault(a, {})[b] = nb.setdefault(b, {})[a] = n ** 0.5
    by_ix = {s["index"]: s["id"] for s in sides}
    hand = hand_hues()
    got: dict[int, int] = {k: hand[sid] for k, sid in by_ix.items() if sid in hand}
    order = sorted((k for k in by_ix if k not in got), key=lambda k: -(total.get(k, 0) + area.get(k, 0) / 100))
    for k in order:
        own = hash_hue(by_ix[k])
        near = {j: w for j, w in nb.get(k, {}).items() if j in got}
        if all(circ(own, got[j]) >= 25 for j in near):
            got[k] = own
            continue
        clear = [h for h in hues if all(circ(h, got[j]) >= 40 for j in near)]
        got[k] = (min(clear, key=lambda h: circ(h, own)) if clear else
                  max(hues, key=lambda h: min(circ(h, got[j]) for j in near)))
    return {by_ix[k]: h for k, h in got.items()}


def main() -> None:
    meta = json.loads((OUT / "fields.json").read_text())
    touch: dict[tuple[int, int], int] = {}      # leading sides on either side of a cell edge, every slice
    area: dict[int, int] = {}
    step = meta["step"]
    labels: dict = {}
    variants = meta.get("variants", ["base", "air", "obs"])
    # observed first: in the research variant, mapped sides keep their observed anchors
    # (research nations can split a state's region and push its deepest point somewhere odd)
    variants = sorted(variants, key=lambda v: 0 if v == "obs" else 1)
    research_only = {s["id"] for s in meta["sides"] if s.get("research")}
    # the Wikidata item each name stands for at its date (etl/polity_qids.py); a label without one stays unclickable
    qids = polity_qids.load()
    side_name = {s["id"]: s["name"] for s in meta["sides"]}
    for variant in variants:
        labels[variant] = {}
        for y in meta["slices"]:
            top, s1 = load_top(meta, variant, y)
            present = set(np.unique(top[s1 > 0.4]).tolist())
            t = np.where(s1 > 0.4, top, -1)
            for a, b in ((t[:, :-1], t[:, 1:]), (t[:-1, :], t[1:, :])):
                m = (a != b) & (a >= 0) & (b >= 0)
                pairs, n = np.unique(np.stack([np.minimum(a[m], b[m]), np.maximum(a[m], b[m])], 1), axis=0, return_counts=True)
                for (i, j), c in zip(pairs.tolist(), n.tolist()):
                    touch[(i, j)] = touch.get((i, j), 0) + c
            for k, c in zip(*np.unique(t[t >= 0], return_counts=True)):
                area[int(k)] = area.get(int(k), 0) + int(c)
            out = []
            for side in meta["sides"]:
                k = side["index"]
                if k not in present:
                    continue
                m = (top == k) & (s1 > 0.4)
                n = int(m.sum())
                if n < CFG.get("label_min_cells", 12):
                    continue
                d = depth(m)
                iy, ix = np.unravel_index(int(d.argmax()), d.shape)
                nm = era_name(side["id"], y)
                q = polity_qids.lookup(qids, side["id"], nm or side_name[side["id"]], float(y))
                src = None if side["id"] in research_only else border_source(meta, side["id"], float(y))
                out.append({"side": side["id"], **({"name": nm} if nm else {}), "lon": round(LON0 + (ix + 0.5) * step, 3),
                            "lat": round(LAT1 - (iy + 0.5) * step, 3), "cells": n,
                            "depth": int(d.max()), **({"qid": q} if q else {}), **({"src": src} if src else {})})
            key = str(int(y)) if float(y).is_integer() else repr(float(y))  # JS String(year)
            if variant == "air" and "obs" in labels and key in labels["obs"]:
                obs_anchor = {a["side"]: a for a in labels["obs"][key]}
                out = [obs_anchor.get(a["side"], a) if a["side"] not in research_only else a for a in out]
            labels[variant][key] = out
    meta["labels"] = labels
    hues = side_hues(meta["sides"], touch, area)
    for s in meta["sides"]:
        s["hue"] = hues[s["id"]]
    write_json(OUT / "fields.json", meta)
    if SCENE != "south-asia":
        print({v: sum(len(x) for x in labels[v].values()) for v in labels})
        return
    write_json(OUT / "lines.json", {"roads": [{
        "name": "Grand Trunk Road (Delhi–Peshawar)", "coords": [list(p) for p in INF.GT_ROAD],
        "source": "pipeline/influence.py GT_ROAD (modern course, coarse)"}]})
    print({v: sum(len(x) for x in labels[v].values()) for v in labels})


if __name__ == "__main__":
    main()
