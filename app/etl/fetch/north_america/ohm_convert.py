"""Assemble OHM admin relations (raw/ohm/geom/chunk_*.json) into cropped polygon GeoJSON, split into
 - ohm_canada_bna      Canada / British North America / Rupert's Land / New France etc.
 - ohm_mexico_newspain Mexico / New Spain internal divisions
 - ohm_other_polities  US states & colonies, Caribbean, Central America, other colonial claims, Indigenous polities
"""
from __future__ import annotations
import collections
import json
import re

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from .helpers import GEO, RAW, crop, feature, log, write_fc

CANADA = re.compile(r"canada|quebec|québec|ontario|nova scotia|new brunswick|prince edward|st\. john's island|île saint-jean|newfoundland|rupert|north-west terr|manitoba|british columbia|vancouver island|columbia district|new caledonia|red river|keewatin|yukon|stickeen|cape breton|acadi|nouvelle-france|queen charlotte|saint-pierre|kalaallit|beothuk|labrador|district of (franklin|mackenzie|athabasca|assiniboia|ungava)|alberta|saskatchewan|arctic territories|alaska boundary", re.I)
MEXICO = re.compile(r"viceroyalty of new spain|inner provinces|new galicia|new navarre|new philippines|new santander|new kingdom of le[óo]n|the californias|(alamos|arizona|batopilas|california|chihuahua|sonora) department|mexic|méxic|nueva (españa|galicia|vizcaya|extremadura|navarre|segovia)|nuevo (méxico|reino de león|león|santander)|nuevas filipinas|las californias|alta california|baja california|provincias internas|intendencia|reino de |tejas|coahuila|chihuahua|sonora|sinaloa|durango|zacatecas|jalisco|guanajuato|querétaro|michoac|oaxaca|puebla|veracruz|vera cruz|tamaulipas|san luis potos|yucat|campeche|tabasco|chiapas|colima|nayarit|tlaxcala|hidalgo|morelos|guerrero|aguascalientes|arizpe|valladolid|departamento de (alamos|arizona|batopilas|california|chihuahua|sonora)|distrito federal de méxico|sierra gorda|istmo de tehuantepec|isla del carmen|moracia|texas|rio grande|río grande|joint mexico|la florida|florida françoise|virreinato de la nueva|rio bravo|gadsden", re.I)

# US-ish names that the Mexico/Canada regexes would otherwise swallow
NOT_MEX = re.compile(r"^(Republic of Texas|Texas|Joint Mexico-Texas Claim|La Florida|Florida)", re.I)


def tag_name(t):
    return t.get("name:en") or t.get("name") or t.get("name:es") or t.get("name:fr") or ""


def assemble(el):
    outers, inners = [], []
    for m in el.get("members", []):
        g = m.get("geometry")
        if m["type"] != "way" or not g or len(g) < 2:
            continue
        ls = LineString([(p["lon"], p["lat"]) for p in g])
        (inners if m.get("role") == "inner" else outers).append(ls)
    if not outers:
        return None
    polys = list(polygonize(unary_union(outers)))
    if not polys:
        return None
    area = unary_union(polys)
    if inners:
        ip = list(polygonize(unary_union(inners)))
        if ip:
            area = area.difference(unary_union(ip))
    return area


def main():
    feats = []
    stats = collections.Counter()
    for p in sorted((RAW / "ohm/geom").glob("chunk_*.json")):
        for el in json.load(open(p))["elements"]:
            t = el["tags"]
            stats["relations"] += 1
            g = assemble(el)
            if g is None:
                stats["no_geometry"] += 1
                continue
            g = crop(g)
            if g is not None:  # OHM coasts are full resolution (hundreds of MB): ~250 m tolerance is plenty at atlas scale
                g = crop(g.simplify(0.0025, preserve_topology=True))
            if g is None:
                stats["outside_window_or_empty"] += 1
                continue
            name = tag_name(t)
            start, end = t.get("start_date"), t.get("end_date")
            lvl = t.get("admin_level")
            note = f"OHM relation {el['id']}; admin_level {lvl}"
            for k in ("wikidata", "description", "note"):
                if t.get(k):
                    note += f"; {k}: {t[k]}"
            c = g.representative_point()
            f = feature(g, name=name, start=start, end=end, source_id="", note=note,
                        ohm_id=el["id"], admin_level=lvl, license=t.get("license"),
                        _cx=c.x, _cy=c.y)
            feats.append(f)
    groups = collections.defaultdict(list)
    for f in feats:
        p = f["properties"]
        n, cx, cy = p["name"], p.pop("_cx"), p.pop("_cy")
        if NOT_MEX.match(n):
            grp = "ohm_other_polities"
        elif CANADA.search(n) and not (cx < -100 and cy < 30):
            grp = "ohm_canada_bna"
        elif MEXICO.search(n):
            grp = "ohm_mexico_newspain"
        else:
            grp = "ohm_other_polities"
        p["source_id"] = grp
        groups[grp].append(f)
    for grp, fs in groups.items():
        fs.sort(key=lambda f: (f["properties"]["name"], f["properties"]["start"] or ""))
        log(" ", grp, write_fc(GEO / f"{grp}.geojson", fs))
    log(" ", dict(stats))


ALL = [main]
