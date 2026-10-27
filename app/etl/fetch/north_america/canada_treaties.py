"""Build geo/canada_treaties.geojson from
  (a) CIRNAC/ISC 'Historic treaties' SHP (open.canada.ca f281b150-...), lon/lat NAD83(CSRS) taken as WGS84
  (b) Ontario 'Ontario First Nations treaty areas' / LIO TreatiesMorrisMap1943 SHP (EPSG:3857)
Dates: LIO DATE_E, Morris label dates, and signing/adhesion dates transcribed from the CIRNAC Treaty Texts pages
(hand-curated in sources/north-america/canada_treaties.json, together with signatories, extra notes, the
federal/Ontario dedupe decisions and the Manitoulin merge). No geometry is drawn or edited; only reprojection,
dedupe, crop and simplify.
"""
from __future__ import annotations

import json
import math
import re

from .helpers import CURATED, GEO, RAW, crop, feature, log, rings_to_geom, shp, write_fc

CT = RAW / "canada_treaties"
R = 6378137.0
MON = "January February March April May June July August September October November December".split()
SIMPLIFY = 0.0005  # deg, ~50 m
PRECISION = {4: "year", 7: "month", 10: "day"}


def merc2ll(x, y):
    return (math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))


def parse_dates(s):
    """'May 9, 1781' / 'May 9th, 1781' -> ['1781-05-09']; 'October 31, 1923 and November 15, 1923' -> both;
    bare years / ranges -> 'YYYY' entries (reduced precision, never padded)."""
    out = []
    for m in re.finditer(r"(%s) (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})" % "|".join(MON), s):
        out.append(f"{m.group(3)}-{MON.index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}")
    if not out:
        out = re.findall(r"\b(1[6-9]\d\d)\b", s)
    return out


def date_sort_key(d):
    return d + "-00" * (2 - d.count("-"))


def dedupe(ds):
    """drop a reduced-precision date ('1905', '1793') when a more precise date with the same prefix exists"""
    ds = set(ds)
    return sorted((d for d in ds if not any(o != d and o.startswith(d) for o in ds)), key=date_sort_key)


def finish(geom):
    g = crop(geom)
    if g is None:
        return None
    g = g.simplify(SIMPLIFY, preserve_topology=True)
    return crop(g)


def load_curated():
    c = json.loads((CURATED / "canada_treaties.json").read_text())
    return c["treaties"], c["merges"]


UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _words(n):
    """0..99 in words, e.g. 52 -> 'fifty two'"""
    return UNITS[n] if n < 20 else TENS[n // 10] + ("" if n % 10 == 0 else " " + UNITS[n % 10])


def year_forms(y: str):
    """'1852' -> {'1852', 'one thousand eight hundred fifty two', 'eighteen hundred fifty two'} (text normalised without 'and')"""
    n = int(y)
    rest = _words(n % 100) if n % 100 else ""
    return {y, f"one thousand {UNITS[n // 100 % 10]} hundred {rest}".strip(), f"{UNITS[n // 100]} hundred {rest}".strip()}


def _page_text(path):
    t = re.sub(r"<[^>]+>", " ", path.read_text(errors="replace")).lower()
    t = re.sub(r"[-\s,]+", " ", t)
    return re.sub(r"\band ", "", t)


def check_pages(cur):
    """Sanity check of the curated transcription against the fetched pages: the year of every curated date should
    appear (in digits or words) on one of the pages it cites. Warns only; the dates come from the curated file."""
    texts = {}
    for key, e in cur.items():
        pages = e.get("cirnac_pages", [])
        for p in pages:
            f = CT / "cirnac_pages" / f"{p}.html"
            if p not in texts:
                texts[p] = _page_text(f) if f.exists() else ""
        for d in e.get("cirnac_dates", []):
            if d in e.get("not_on_page", []):
                continue
            if not any(form in texts[p] for p in pages for form in year_forms(d[:4])):
                log(f"  warning: {key} date {d}: year not found on CIRNAC page(s) {pages}")


def lio_signatories(r, cur):
    if "signatories" in cur:
        return cur["signatories"]
    m = r.get("MORRIS_NAM") or ""
    mm = re.search(r"\b1[6-9]\d\d\b,?\s*(.*)$", m)
    rest = mm.group(1) if mm else ""
    rest = re.sub(r",?\s*(Nos?\.|Page|Vol\.|P\.C\.).*$", "", rest).strip(" ,")
    return rest + (" (per Morris 1943 label)" if rest else "")


def start_props(dates):
    return dict(start=dates[0] if dates else None, dates=dates)


def ontario(cur, merges):
    P = next((CT / "morris").glob("*.shp")).with_suffix("")
    G = shp.read_shp(P.with_suffix(".shp"))
    A = shp.read_dbf(P.with_suffix(".dbf"))
    lio = {}
    for parts, r in zip(G, A):
        rings = [[merc2ll(x, y) for x, y in part] for part in parts]
        lio[f"ON-{r['TREATY_ID']}"] = (rings_to_geom(rings), r)
    # features with identical geometry -> one feature (curated name/signatories); first id is kept
    merged, absorbed = {}, set()
    for mg in merges:
        keep, *rest = mg["ids"]
        if all(lio[keep][0].symmetric_difference(lio[o][0]).area < 1e-9 for o in rest):
            merged[keep] = mg
            absorbed.update(rest)
        else:
            log(f"  warning: merge {mg['ids']} skipped, geometries now differ")
    feats = []
    for key, (geom, r) in sorted(lio.items()):
        c = cur.get(key, {})
        if "drop" in c or key in absorbed:
            continue
        lio_d = parse_dates(r["DATE_E"])
        morris_d = [] if c.get("ignore_morris_label_dates") else parse_dates(r.get("MORRIS_NAM") or "")
        cir = c.get("cirnac_dates", [])
        name, label = r["ALT_NAME_E"], r["TREATY_E"]
        src = {"ontario_lio_DATE_E": lio_d, "morris_1943_label": morris_d, "cirnac_treaty_texts": cir}
        sigs = lio_signatories(r, c)
        if key in merged:
            mg = merged[key]
            others = [lio[o][1] for o in mg["ids"][1:]]
            name = mg["name"]
            label = "; ".join([r["TREATY_E"]] + [o["TREATY_E"] for o in others])
            src = {"ontario_lio_DATE_E": lio_d + [d for o in others for d in parse_dates(o["DATE_E"])],
                   "morris_1943_label": morris_d,
                   "cirnac_treaty_texts": cir + [d for o in mg["ids"][1:] for d in cur.get(o, {}).get("cirnac_dates", [])]}
            sigs = mg["signatories"]
        dates = dedupe({d for v in src.values() for d in v})
        conflicts = (len({d for d in src["ontario_lio_DATE_E"] if len(d) == 10} ^ {d for d in src["cirnac_treaty_texts"] if len(d) == 10})
                     and src["cirnac_treaty_texts"] and src["ontario_lio_DATE_E"])
        tid = r["TREATY_ID"]
        note = f"Ontario LIO treaty {tid}: {label}. Morris 1943 label: {r.get('MORRIS_NAM') or '-'}. Date source: LIO DATE_E '{r['DATE_E']}'"
        if src["cirnac_treaty_texts"]:
            note += f"; CIRNAC treaty text dates {', '.join(src['cirnac_treaty_texts'])}"
        if conflicts:
            note += ". Sources disagree on the date (provisional agreement vs. confirmatory deed, or data error); start = earliest"
        if c.get("note"):
            note += ". " + c["note"]
        g = finish(geom)
        if g is None:
            continue
        feats.append(feature(g, name=name, **start_props(dates), signatories=sigs,
                             source_id="ontario_lio_treaties_morris1943", note=note,
                             treaty_id=key, treaty_label=label, date_sources=src,
                             start_precision=PRECISION.get(len(dates[0])) if dates else None))
    return feats


def federal(cur):
    P = CT / "shp/Traite_historique_Historic_Treaty_SHP"
    G = shp.read_shp(P.with_suffix(".shp"))
    A = shp.read_dbf(P.with_suffix(".dbf"))
    feats = []
    for parts, r in zip(G, A):
        tag = r["TAG_ID"]
        c = cur.get(f"CA-{tag}", {})
        if "drop" in c:
            continue
        geom = rings_to_geom([list(p) for p in parts])
        cir = c.get("cirnac_dates", [])
        dates = dedupe(cir)
        note = (f"CIRNAC/ISC Historic treaties TAG_ID {tag}, subtype '{r['SBTP_ENAME']}'. Dataset carries only the name "
                f"('{r['ENAME']}'); dates transcribed from the CIRNAC Treaty Texts pages (treaty + adhesions found there; list may be incomplete)")
        if c.get("note"):
            note += ". " + c["note"]
        g = finish(geom)
        if g is None:
            continue
        feats.append(feature(g, name=r["ENAME"], **start_props(dates),
                             signatories=c.get("signatories", ""), source_id="cirnac_historic_treaties", note=note,
                             treaty_id=f"CA-{tag}", treaty_label=r["ENAME"], date_sources={"cirnac_treaty_texts": cir},
                             start_precision=PRECISION.get(len(dates[0])) if dates else None))
    return feats


def main():
    cur, merges = load_curated()
    check_pages(cur)
    feats = ontario(cur, merges) + federal(cur)
    feats.sort(key=lambda f: date_sort_key(f["properties"]["start"] or "9999"))
    out = GEO / "canada_treaties.geojson"
    n = write_fc(out, feats)
    return n, f"{out.stat().st_size // 1024} KB"


ALL = [main]
