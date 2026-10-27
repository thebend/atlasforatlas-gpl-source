"""Events and settlement labels for a scene straight from Wikidata (observed).

Events: items whose P31 is one of a list of event classes, dated by P585 or
P580 inside the scene's years, located by their own P625 or by the P625 of
their P276 location, inside the scene window. Settlements: notable places
(by sitelinks) with an inception date, so the map only labels a town once it
exists. Responses are cached under .cache/scenes/<scene>/sparql/.

Run: ATLAS_SCENE=north-america uv run --project .. python -m etl.history.events_from_wikidata
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request

from etl.common import CFG, LAT0, LAT1, LON0, LON1, SCACHE, SCENE, SCENE_EVENTS, UA, write_json

ENDPOINT = "https://query.wikidata.org/sparql"
Y0, Y1 = CFG["years"]

EVENT_CLASSES = {
    "Q178561": "battle", "Q1261499": "battle", "Q188055": "siege", "Q131569": "treaty",
    "Q3199915": "event", "Q124734": "event", "Q645883": "battle", "Q625298": "battle",
    "Q1006311": "event", "Q8016240": "treaty",
}
# Q1261499 naval battle, Q3199915 massacre, Q124734 rebellion, Q645883 military
# operation, Q625298 peace treaty (some), Q1006311 war of national liberation,
# Q8016240 armistice
# notability floor: a dense, well-documented scene (Europe) needs more sitelinks to stay readable
MIN_SITELINKS = CFG.get("min_sitelinks", 3)


def sparql(q: str) -> list[dict]:
    key = hashlib.sha1(q.encode()).hexdigest()[:16]
    p = SCACHE / "sparql" / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text())
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    for attempt in range(4):
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=120).read())["results"]["bindings"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rows))
            time.sleep(1.0)
            return rows
        except Exception as e:  # noqa: BLE001 — retry then surface
            print("  retry", attempt, e)
            time.sleep(5 * (attempt + 1))
    raise SystemExit("SPARQL failed repeatedly")


def box() -> str:
    return (f'SERVICE wikibase:box {{ ?place wdt:P625 ?coord . '
            f'bd:serviceParam wikibase:cornerSouthWest "Point({LON0} {LAT0})"^^geo:wktLiteral . '
            f'bd:serviceParam wikibase:cornerNorthEast "Point({LON1} {LAT1})"^^geo:wktLiteral . }}')


def parse_point(wkt: str) -> tuple[float, float]:
    lon, lat = wkt.replace("Point(", "").replace(")", "").split()
    return float(lon), float(lat)


def parse_date(v: str) -> tuple[int, int | None, int | None]:
    neg = v.startswith("-")
    s = v.lstrip("+-")
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    return (-y if neg else y), (m or None), (d or None)


def inside(lon: float, lat: float) -> bool:
    return LON0 <= lon <= LON1 and LAT0 <= lat <= LAT1


def events() -> list[dict]:
    out: dict[str, dict] = {}
    for cls, icon in EVENT_CLASSES.items():
        for via in ("self", "P276"):
            loc = "?item wdt:P625 ?coord ." if via == "self" else "?item wdt:P276 ?place . ?place wdt:P625 ?coord ."
            # bbox filtering happens locally: the box service enumerates every coordinate in the window
            q = f"""SELECT ?item ?label ?date ?prec ?coord ?sl ?article WHERE {{
  ?item wdt:P31 wd:{cls} .
  ?item wikibase:sitelinks ?sl . FILTER(?sl >= {MIN_SITELINKS})
  ?item p:P585|p:P580 ?st . ?st psv:P585|psv:P580 ?tv . ?tv wikibase:timeValue ?date ; wikibase:timePrecision ?prec .
  FILTER(YEAR(?date) >= {Y0} && YEAR(?date) <= {Y1})
  {loc}
  OPTIONAL {{ ?item rdfs:label ?label FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
}}"""
            rows = sparql(q)
            kept = 0
            for r in rows:
                qid = r["item"]["value"].rsplit("/", 1)[-1]
                try:
                    lon, lat = parse_point(r["coord"]["value"])
                except ValueError:
                    continue
                if not inside(lon, lat) or "label" not in r:
                    continue
                if qid in out and (out[qid]["via"] == "self" or via != "self"):
                    continue
                y, m, d = parse_date(r["date"]["value"])
                prec = int(r["prec"]["value"])
                out[qid] = {
                    "qid": qid, "title": r["label"]["value"], "year": y,
                    "month": m if prec >= 10 else None, "day": d if prec >= 11 else None,
                    "lon": round(lon, 4), "lat": round(lat, 4), "icon": icon,
                    "sitelinks": int(r["sl"]["value"]),
                    "url": r.get("article", {}).get("value") or f"https://www.wikidata.org/wiki/{qid}",
                    "source": "Wikidata (SPARQL)" + ("" if via == "self" else ", located via P276"),
                    "class": "observed", "via": via,
                }
                kept += 1
            print(f"{cls} via {via}: {len(rows)} rows, {kept} in window")
    ev = sorted(out.values(), key=lambda e: (e["year"], e["month"] or 0, e["day"] or 0))
    for e in ev:
        e.pop("via", None)
    return ev


def settlements() -> list[dict]:
    q = """SELECT ?place ?label ?inc ?coord ?sl WHERE {
  VALUES ?cls { wd:Q515 wd:Q1549591 wd:Q3957 wd:Q532 wd:Q1093829 wd:Q5119 }
  ?place wdt:P31 ?cls .
  ?place wikibase:sitelinks ?sl . FILTER(?sl >= 60)
  ?place wdt:P625 ?coord .
  OPTIONAL { ?place wdt:P571 ?inc . }
  OPTIONAL { ?place rdfs:label ?label FILTER(LANG(?label) = "en") }
}"""
    rows = sparql(q)
    best: dict[str, dict] = {}
    for r in rows:
        qid = r["place"]["value"].rsplit("/", 1)[-1]
        try:
            lon, lat = parse_point(r["coord"]["value"])
        except ValueError:
            continue
        if not inside(lon, lat) or "label" not in r:
            continue
        try:
            inc = parse_date(r["inc"]["value"])[0] if "inc" in r else None
        except ValueError:
            inc = None
        cur = best.get(qid)
        if cur is None or (inc is not None and (cur["from"] is None or inc < cur["from"])):
            best[qid] = {"name": r["label"]["value"], "qid": qid, "lon": round(lon, 4), "lat": round(lat, 4),
                         "from": inc, "sitelinks": int(r["sl"]["value"]), "source": "Wikidata (SPARQL)"}
    cities = sorted(best.values(), key=lambda c: -c["sitelinks"])
    # "cities": "dated" (ancient periods): a city with no inception date may be modern (Abu Dhabi in 331 BCE)
    dated = CFG.get("cities") == "dated"
    # "cities": "none" (prehistory): an inception date is a city's earliest trace, not a settlement the map can show
    if CFG.get("cities") == "none":
        return []
    return [c for c in cities if (c["from"] is None and not dated) or (c["from"] is not None and c["from"] <= Y1)][:140]


def main() -> None:
    ev = events()
    cities = settlements()
    write_json(SCENE_EVENTS, {"events": ev, "cities": cities,
                                     "source": "Wikidata SPARQL; classes " + ", ".join(EVENT_CLASSES)})
    print(SCENE, "events", len(ev), "cities", len(cities))


if __name__ == "__main__":
    main()
