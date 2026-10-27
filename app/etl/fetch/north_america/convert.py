"""Convert Newberry AHCB state/territory, Royce cessions and aourednik/historical-basemaps to cropped GeoJSON."""
from __future__ import annotations
import datetime as dt
import json

from shapely.geometry import shape

from etl import profile
from .fetch import HB_YEARS
from .helpers import GEO, RAW, crop, feature, rings_to_geom, shp, write_fc, ymd


def newberry():
    p = RAW / "ahcb/US_AtlasHCB_StateTerr_Gen001/US_HistStateTerr_Gen001_Shapefile/US_HistStateTerr_Gen001"
    rows = shp.read_dbf(p.with_suffix(".dbf"))
    geoms = shp.read_shp(p.with_suffix(".shp"))
    assert len(rows) == len(geoms)
    feats = []
    for r, parts in zip(rows, geoms):
        start = ymd(r["START_DATE"])
        if start > "1900-12-31":
            continue
        g = crop(rings_to_geom(parts))
        if g is None:
            continue
        feats.append(feature(
            g, name=r["FULL_NAME"] or r["NAME"], start=start, end=ymd(r["END_DATE"]),
            source_id="newberry_ahcb_stateterr",
            note=f'{r["TERR_TYPE"]}. {r["CHANGE"]} {r["CITATION"]}'.strip(),
            ahcb_id=r["ID"], terr_type=r["TERR_TYPE"], version=int(r["VERSION"] or 0)))
    feats.sort(key=lambda f: (f["properties"]["start"], f["properties"]["name"]))
    n = write_fc(GEO / "newberry_ahcb_stateterr.geojson", feats)
    yrs = sorted(f["properties"]["start"] for f in feats)
    return n, yrs[0], yrs[-1]


def iso(ms):
    if ms is None:
        return None
    return (dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=ms)).strftime("%Y-%m-%d")


def royce():
    polys = json.load(open(RAW / "royce/polys.geojson"))["features"]
    table = {t["cessnum"]: t for t in json.load(open(RAW / "royce/table.json"))}
    feats, nogeom, nodate = [], [], []
    seen = set()
    for f in polys:
        cn = f["properties"]["cessnum"]
        seen.add(cn)
        t = table.get(cn)
        g = crop(shape(f["geometry"]))
        if g is None:
            nogeom.append(cn); continue
        if t is None:
            nodate.append(cn); continue
        dates = sorted(d for d in (iso(t.get(f"cessdate{i}")) for i in range(1, 6)) if d)
        if not dates:
            nodate.append(cn); continue
        links = []
        for i in range(1, 6):
            if t.get(f"cessdate{i}"):
                links.append({"date": iso(t[f"cessdate{i}"]),
                              "royce_schedule": t.get(f"date{i}link_royce_schedule"),
                              "kappler_treaty": t.get(f"date{i}link_kappler_treaty")})
        instr = []
        if any(l["kappler_treaty"] for l in links): instr.append("treaty")
        if t.get("link_federal_statute"): instr.append("federal statute")
        if t.get("link_executive_order"): instr.append("executive order")
        if t.get("link_other_treaty"): instr.append("other treaty")
        tribes = t.get("schdtrb") or ""
        mapname = t.get("mapname") or ""
        name = f"Cession {cn}" + (f": {tribes}" if tribes else "")
        note = (f"Royce cession no. {cn} ({mapname}); signed/enacted {', '.join(dates)}; "
                f"instrument: {'/'.join(instr) or 'unspecified'}; Schedule citations: {t.get('citation1') or ''}")
        if t.get("state"): note += f"; present-day states: {t['state']}"
        feats.append(feature(g, name=name, start=dates[0], end=None, source_id="royce_cessions",
                             note=note, cessnum=cn, dates=dates, tribes_schedule=tribes,
                             tribes_present_day=t.get("presdaytrb"), royce_map=mapname,
                             instrument=instr, entries=links, states=t.get("state")))
    feats.sort(key=lambda f: (f["properties"]["start"], int("".join(c for c in f["properties"]["cessnum"] if c.isdigit())), f["properties"]["cessnum"]))
    n = write_fc(GEO / "royce_cessions.geojson", feats)
    nospatial = sorted(set(table) - seen, key=int)
    return n, feats[0]["properties"]["start"], feats[-1]["properties"]["start"], dict(
        outside_window=nogeom, no_table_row=nodate, table_rows_without_polygon=nospatial,
        poly_total=len(polys), table_total=len(table))


def basemaps():
    if profile.blocked("hb"):
        return {}
    years = HB_YEARS
    out = {}
    for i, y in enumerate(years):
        d = json.load(open(RAW / f"hb/world_{y}.geojson"))
        nxt = years[i + 1] if i + 1 < len(years) else None
        feats = []
        for f in d["features"]:
            if not f["geometry"]:
                continue
            g = crop(shape(f["geometry"]))
            if g is None:
                continue
            p = f["properties"]
            name = p.get("NAME") or p.get("ABBREVN") or p.get("SUBJECTO") or p.get("PARTOF")
            feats.append(feature(g, name=name, start=str(y), end=str(nxt) if nxt else None,
                                 source_id="historical_basemaps",
                                 note=f'snapshot {y}; subject to: {p.get("SUBJECTO")}; part of: {p.get("PARTOF")}; border precision {p.get("BORDERPRECISION")} (1 approx, 3 treaty)',
                                 subjecto=p.get("SUBJECTO"), partof=p.get("PARTOF"), precision=p.get("BORDERPRECISION")))
        feats.sort(key=lambda f: f["properties"]["name"] or "")
        out[y] = write_fc(GEO / f"historical_basemaps_{y}.geojson", feats)
        out[y] = (out[y], d.get("crs"))
    return out


ALL = [newberry, royce, basemaps]
