"""Dated settlements and forts: evidence of where a colonial power actually held land.

A colonial charter or viceroyalty polygon is a claim. Around the towns, missions
and forts that existed inside it at a given date, the power held the land; the
scene builder turns those neighbourhoods into held "cores" of the claim (see
scene_na_sides.colonial_cores). Source: Wikidata (CC0), items with an inception
date (P571) and coordinates, of settlement / fort / mission / trading-post types,
with at least a few sitelinks so the date is likely to be checked.

Output: .cache/scenes/<scene>/settlements.json  [{qid, name, lon, lat, from, kind, sitelinks}]

Run: ATLAS_SCENE=north-america uv run --project .. python -m etl.history.settlements
"""
from __future__ import annotations

from etl.common import CFG, SCACHE, write_json
from etl.history.events_from_wikidata import inside, parse_date, parse_point, sparql

Y0, Y1 = CFG["years"]
KINDS = {
    "Q486972": "settlement", "Q515": "city", "Q3957": "town", "Q532": "village",
    "Q1785071": "fort", "Q57821": "fortification", "Q2232001": "mission",  # Spanish mission (Q2232001 = mission church?)
    "Q1061229": "trading post", "Q15661340": "ancient city",
}
MIN_SITELINKS = 4


def main() -> None:
    out: dict[str, dict] = {}
    for cls, kind in KINDS.items():
        q = f"""SELECT ?p ?label ?inc ?prec ?coord ?sl WHERE {{
  ?p wdt:P31 wd:{cls} .
  ?p wikibase:sitelinks ?sl . FILTER(?sl >= {MIN_SITELINKS})
  ?p p:P571/psv:P571 ?tv . ?tv wikibase:timeValue ?inc ; wikibase:timePrecision ?prec .
  FILTER(YEAR(?inc) >= 1000 && YEAR(?inc) <= {Y1})
  ?p wdt:P625 ?coord .
  OPTIONAL {{ ?p rdfs:label ?label FILTER(LANG(?label) = "en") }}
}}"""
        rows = sparql(q)
        kept = 0
        for r in rows:
            try:
                lon, lat = parse_point(r["coord"]["value"])
                y = parse_date(r["inc"]["value"])[0]
            except ValueError:
                continue
            if not inside(lon, lat) or "label" not in r or int(r["prec"]["value"]) < 9:
                continue
            qid = r["p"]["value"].rsplit("/", 1)[-1]
            cur = out.get(qid)
            if cur is None or y < cur["from"]:
                out[qid] = {"qid": qid, "name": r["label"]["value"], "lon": round(lon, 4), "lat": round(lat, 4),
                            "from": y, "kind": kind, "sitelinks": int(r["sl"]["value"])}
                kept += 1
        print(f"{cls} {kind}: {len(rows)} rows, {kept} kept")
    res = sorted(out.values(), key=lambda s: s["from"])
    write_json(SCACHE / "settlements.json", res)
    print("settlements", len(res), "before 1800:", sum(1 for s in res if s["from"] < 1800))


if __name__ == "__main__":
    main()
