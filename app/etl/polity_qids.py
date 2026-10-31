"""Which Wikidata item each territory name on a period's map stands for, at each date it is shown.

A name on the map opens a card with the polity's Wikipedia article, so the link has to be the
historical entity, not a namesake: "Ottoman Empire", not Turkey; "Germany" in 1914 is the German
Empire, in 1925 the Weimar Republic. Every label the periods draw (public/data/<period>/fields.json,
from etl/history/labels.py) is a side and the name it shows, over a set of dates. Each is resolved
here, at build time, by the first of:

  1. sources/polity_qids.manual.json: a judgement, cited where it needed research (a regime
     timeline for a side whose map name is the modern state's: [[until_year, item], ...], where an
     item is a QID or an English Wikipedia title; or null, for a label with no article of its own);
  2. where Cliopatria draws the side, the item it links for the side's row of the label's name in
     each year (not a composite's row, whose link is one member's), if it is a polity of that
     date; an item named exactly as the label, live then, comes first (Cliopatria links its
     "Sasanian Empire" rows to the Indo-Sassanids);
  3. otherwise one item for all the label's dates: the period's research catalogue's item for the
     polity, or an item whose English label or alias is the name exactly (a nation also as "<name>
     people"), of a political entity, people or culture class; a dated item must cover most of the
     label's dates, and covering more wins.

Everything is read through the Wikidata Query Service (labels, dates, sitelinks, classes), cached.
Labels nothing resolves stay without a link: the map leaves them unclickable. Nothing is guessed in
the app; it only looks the label up in what is written here.

Output: sources/polity_qids.json (committed)   {"side|name": {"spans": [[from, qid], ...], "how", "wd"}}
  spans: the item from that year until the next span's year (the first from any earlier date).
  labels.py attaches the item to each label anchor.
Report: .cache/polity_qids/report.tsv, every label with how it was resolved, for review.
Run: uv run --project .. python -m etl.polity_qids   (after a period's labels change; then its labels
step again, which attaches the items: ATLAS_SCENE=<period> uv run --project .. python -m etl.history.labels)
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile

from etl.common import CACHE, MANIFESTS, PROTO, PUBLIC, RESEARCH
from etl.net import get_json

C = CACHE / "polity_qids"
OUT = PROTO / "sources" / "polity_qids.json"
MANUAL = PROTO / "sources" / "polity_qids.manual.json"
SPARQL = "https://query.wikidata.org/sparql"
CLIO = CACHE / "sources" / "cliopatria" / "cliopatria.geojson.zip"
SIDES = json.loads((PROTO / "sources" / "sides.json").read_text())["sides"]
# a political territorial entity (states, empires, colonies, provinces...), a people or tribe, an
# archaeological culture, a dynasty, a historical period: what a territory's name can stand for
ROOTS = ["Q1048835", "Q7275", "Q3024240", "Q41710", "Q133311", "Q2472587", "Q465299", "Q164950", "Q11514315", "Q1371849"]


def _cached(name: str, fetch):
    p = C / name
    if p.exists():
        return json.loads(p.read_text())
    v = fetch()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v))
    return v


def _key(s: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9]+', '_', s)[:80]}_{hashlib.sha1(s.encode()).hexdigest()[:8]}"


def sparql(q: str) -> list[dict]:
    return get_json(SPARQL, {"query": q, "format": "json"})["results"]["bindings"]


def _lit(s: str) -> str:
    return json.dumps(s, ensure_ascii=False) + "@en"


def _q(b: dict, k: str) -> str:
    return b[k]["value"].rsplit("/", 1)[1]


def _year(v: str | None) -> float | None:
    """A query's dateTime ("1871-01-18T00:00:00Z", "-0322-01-01T...") as a decimal year."""
    m = re.match(r"(-?)(\d+)-(\d\d)", v or "")
    if not m:
        return None
    return int(m.group(2)) * (-1 if m.group(1) else 1) + (int(m.group(3)) - 1) / 12


def entities(qids: list[str]) -> dict[str, dict]:
    """Compact items: English label, span (inception or start .. dissolution or end), English
    Wikipedia title, sitelink count."""
    out: dict[str, dict] = {}
    todo = []
    for q in sorted({q for q in qids if q}):
        p = C / "ent" / f"{q}.json"
        if p.exists():
            out[q] = json.loads(p.read_text())
        else:
            todo.append(q)
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        vals = " ".join(f"wd:{x}" for x in batch)
        rec: dict[str, dict] = {q: {"missing": True} for q in batch}
        for b in sparql("SELECT ?i ?label ?t ?n (MIN(?s) AS ?start) (MAX(?e) AS ?end) WHERE { VALUES ?i { " + vals + " } "
                        "OPTIONAL { ?i rdfs:label ?label FILTER(LANG(?label) = 'en') } "
                        "OPTIONAL { ?a schema:about ?i; schema:isPartOf <https://en.wikipedia.org/>; schema:name ?t } "
                        "OPTIONAL { ?i wikibase:sitelinks ?n } OPTIONAL { ?i wdt:P571|wdt:P580 ?s } "
                        "OPTIONAL { ?i wdt:P576|wdt:P582 ?e } } GROUP BY ?i ?label ?t ?n"):
            q = _q(b, "i")
            rec[q] = {"label": b.get("label", {}).get("value"), "start": _year(b.get("start", {}).get("value")),
                      "end": _year(b.get("end", {}).get("value")),
                      "enwiki": b.get("t", {}).get("value"), "sitelinks": int(b.get("n", {}).get("value", 0))}
        (C / "ent").mkdir(parents=True, exist_ok=True)
        for q, r in rec.items():
            (C / "ent" / f"{q}.json").write_text(json.dumps(r))
            out[q] = r
    return out


def by_titles(titles: list[str]) -> dict[str, str | None]:
    """English Wikipedia title (exact, not a redirect) -> its item."""
    def fetch(t: str) -> dict:
        rows = sparql("SELECT ?i WHERE { ?a schema:about ?i; schema:isPartOf <https://en.wikipedia.org/>; schema:name " + _lit(t) + " }")
        return {"q": _q(rows[0], "i") if rows else None}
    return {t: _cached(f"title/{_key(t)}.json", lambda t=t: fetch(t))["q"] for t in sorted(set(titles))}


def named(names: list[str]) -> dict[str, list[str]]:
    """Name -> the items whose English label or alias it is exactly (not people, disambiguation
    pages or lists)."""
    out: dict[str, list[str]] = {}
    todo = []
    for n in sorted(set(names)):
        p = C / "named" / f"{_key(n)}.json"
        if p.exists():
            out[n] = json.loads(p.read_text())
        else:
            todo.append(n)
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        got: dict[str, list[str]] = {n: [] for n in batch}
        for b in sparql("SELECT DISTINCT ?i ?n WHERE { VALUES ?n { " + " ".join(_lit(n) for n in batch) + " } "
                        "{ ?i rdfs:label ?n } UNION { ?i skos:altLabel ?n } "
                        "FILTER NOT EXISTS { ?i wdt:P31 ?x VALUES ?x { wd:Q5 wd:Q4167410 wd:Q13406463 wd:Q11266439 } } }"):
            if b["i"]["value"].rsplit("/", 1)[1].startswith("Q"):
                got.setdefault(b["n"]["value"], []).append(_q(b, "i"))
        (C / "named").mkdir(parents=True, exist_ok=True)
        for n, qs in got.items():
            if n in batch:
                (C / "named" / f"{_key(n)}.json").write_text(json.dumps(qs))
                out[n] = qs
    return out


def polityish(qids: list[str]) -> set[str]:
    """The items that are (subclasses of) a political entity, people, culture, dynasty or period."""
    p = C / "class.json"
    known: dict[str, bool] = json.loads(p.read_text()) if p.exists() else {}
    todo = sorted(set(qids) - set(known))
    for i in range(0, len(todo), 60):
        batch = todo[i:i + 60]
        q = ("SELECT DISTINCT ?i WHERE { VALUES ?i { " + " ".join(f"wd:{x}" for x in batch) + " } VALUES ?r { "
             + " ".join(f"wd:{r}" for r in ROOTS) + " } ?i wdt:P31/wdt:P279* ?r . }")
        d = get_json(SPARQL, {"query": q, "format": "json"})
        hit = {b["i"]["value"].rsplit("/", 1)[1] for b in d["results"]["bindings"]}
        for x in batch:
            known[x] = x in hit
        C.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(known))
    return {q for q in qids if known.get(q)}


def covers(e: dict, y: float, slack: float = 1.0) -> bool | None:
    """Whether an item existed in year y (None: it has no dates)."""
    s, t = e.get("start"), e.get("end")
    if s is None and t is None:
        return None
    return (s is None or s - slack <= y) and (t is None or y < t + slack)


def collect() -> dict[str, dict]:
    """Every label the built periods draw: "side|name" -> its years, periods, whether research-modelled."""
    out: dict[str, dict] = {}
    for sid in MANIFESTS:
        p = PUBLIC / "data" / sid / "fields.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text())
        sides = {s["id"]: s for s in m["sides"]}
        for by_year in (m.get("labels") or {}).values():
            for y, anchors in by_year.items():
                for a in anchors:
                    s = sides.get(a["side"], {})
                    if s.get("kind") == "culture":
                        continue
                    name = a.get("name") or s.get("name") or a["side"]
                    k = f"{a['side']}|{name}"
                    r = out.setdefault(k, {"side": a["side"], "name": name, "default": name == s.get("name"),
                                           "years": set(), "scenes": set(), "research": bool(s.get("research"))})
                    r["years"].add(float(y))
                    r["scenes"].add(sid)
    return out


def cliopatria_rows() -> dict[str, list[tuple[float, float, str, str]]]:
    """Cliopatria's rows by the side the periods draw them as (etl/history/border_sides.py): side ->
    [(from, to, item, name)]. Not the composite rows: their Wikidata column is one member's item."""
    p = C / "cliopatria.json"
    if p.exists():
        return {k: [tuple(x) for x in v] for k, v in json.loads(p.read_text()).items()}
    if not CLIO.exists():
        return {}
    from etl.history.border_sides import BY_CLIO, slug
    with zipfile.ZipFile(CLIO) as zf:
        d = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith(".geojson"))))
    out: dict[str, list] = {}
    for f in d["features"]:
        pr = f["properties"]
        if not pr.get("Wikidata") or pr["Name"].startswith("("):
            continue
        top = (pr["MemberOf"] or "").strip("()") or pr["Name"]
        sid = BY_CLIO.get(top) or BY_CLIO.get(pr["Name"]) or slug(top)
        out.setdefault(sid, []).append((float(pr["FromYear"]), float(pr["ToYear"]) + 1, pr["Wikidata"], pr["Name"]))
    C.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def clio_pick(rows: list[tuple[float, float, str, str]], name: str, y: float, ok) -> str | None:
    """The item of the side's row of the label's name in year y (or within a few years: labels sit
    on slice dates), where ok(item, y) accepts it: Cliopatria links some rows to the wrong item."""
    names = {n.casefold() for n in variants(name)}
    own = [r for r in rows if r[3].casefold() in names]
    live = [r[2] for r in own if r[0] <= y < r[1]]
    if not live:
        near = sorted((min(abs(y - r[0]), abs(y - r[1])), r[2]) for r in own)
        live = [near[0][1]] if near and near[0][0] <= 5 else []
    qs = [q for q in live if ok(q, y)]
    return max(set(qs), key=qs.count) if qs else None


def research_items() -> dict[tuple[str, str], str]:
    """(period, side) -> the item its research catalogue gives the polity."""
    alias = {a: sid for sid, s in SIDES.items() for a in s["aliases"]}
    out = {}
    for sid, m in MANIFESTS.items():
        for name in m.get("research", []):
            p = RESEARCH / f"{name}.raw.json"
            if not p.exists():
                continue
            for pol in json.loads(p.read_text()).get("polities") or []:
                if pol.get("qid"):
                    out[(sid, pol["id"])] = pol["qid"]
                    if pol["id"] in alias:
                        out.setdefault((sid, alias[pol["id"]]), pol["qid"])
    return out


def plain(name: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", name).strip()


def variants(name: str) -> list[str]:
    """The name, without its bracketed gloss, and each of "Persia / Iran"'s names."""
    parts = [x.strip("();") for x in name.split(");(")] if ");(" in name else []   # a Cliopatria composite's names
    out = [name, plain(name), *(x.strip() for x in plain(name).split(" / ")), *parts]
    # Wikidata labels in sentence case: "Habsburg monarchy"
    return list(dict.fromkeys(out + [x[0] + x[1:].lower() for x in out if x]))


def search_names(name: str) -> list[str]:
    """What to look for in Wikidata's labels: the variants, and a nation's "<name> people"."""
    return list(dict.fromkeys([*variants(name), *(f"{v} people" for v in variants(name))]))


def runs(years: list[float], pick) -> list[list]:
    """Consecutive years with the same item as spans [[from, qid], ...] (None where nothing covers)."""
    out: list[list] = []
    for y in years:
        q = pick(y)
        if not out or out[-1][1] != q:
            out.append([y, q])
    return out


def load() -> dict[str, dict]:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def lookup(table: dict[str, dict], side: str, name: str, y: float) -> str | None:
    """The item a label stands for in year y (labels.py), from the table written here."""
    spans = (table.get(f"{side}|{name}") or {}).get("spans")
    if not spans:
        return None
    return next((q for y0, q in reversed(spans) if y0 <= y), spans[0][1])


def main() -> None:
    labels = collect()
    manual = {k: v for k, v in (json.loads(MANUAL.read_text()) if MANUAL.exists() else {}).items() if not k.startswith("_")}
    clio = cliopatria_rows()
    clio_scenes = {sid for sid, m in MANIFESTS.items()
                   if any((b if isinstance(b, str) else b["source"]) == "cliopatria" for b in m.get("etl", {}).get("borders") or [])}
    research = research_items()

    # every candidate item, fetched once
    cand: dict[str, list[tuple[str, str]]] = {}
    titles = [x for v in manual.values() if isinstance(v, list) for _, x in v if x and not re.fullmatch(r"Q\d+", x)]
    titles += [v for v in manual.values() if isinstance(v, str) and not re.fullmatch(r"Q\d+", v)]
    title_q = by_titles(titles)
    hits = named([v for k, r in labels.items() if k not in manual for v in search_names(r["name"])])
    for k, r in labels.items():
        c = [("research", research[(s, r["side"])]) for s in sorted(r["scenes"]) if (s, r["side"]) in research]
        c += [("search", q) for nm in search_names(r["name"]) for q in hits.get(nm, [])]
        cand[k] = list(dict.fromkeys(c))
    manual_q = [x for v in manual.values() for _, x in (v if isinstance(v, list) else [[0, v]]) if x and re.fullmatch(r"Q\d+", x)]
    ents = entities([q for c in cand.values() for _, q in c] + [q for q in title_q.values() if q] + manual_q
                    + [x[2] for rows in clio.values() for x in rows])
    klass = polityish([q for c in cand.values() for s, q in c if s == "search"] + [x[2] for rows in clio.values() for x in rows])

    def clio_ok(q: str, y: float) -> bool:
        e = ents.get(q) or {}
        return q in klass and not e.get("missing") and covers(e, y, slack=10) is not False

    table, report = {}, []
    for k, r in sorted(labels.items()):
        years = sorted(r["years"])
        how, spans = None, None
        if k in manual:
            v = manual[k]
            if v is None:
                how = "manual: no article"
            else:
                tl = v if isinstance(v, list) else [[99999, v]]
                tl = [[u, x if re.fullmatch(r"Q\d+", x or "") else title_q.get(x)] for u, x in tl]
                if any(x is None for _, x in tl):
                    raise SystemExit(f"{k}: an English Wikipedia title in the manual table has no item: {v}")
                spans = runs(years, lambda y, tl=tl: next(q for u, q in tl if y < u))
                how = "manual"
        best = None
        if how is None:
            score = None
            for src, q in cand[k]:
                e = ents.get(q) or {}
                if e.get("missing") or not e.get("enwiki") and e.get("sitelinks", 0) == 0:
                    continue
                if src == "search" and q not in klass:
                    continue
                cov = [covers(e, y) for y in years]
                dated = any(x is not None for x in cov)
                frac = sum(1 for x in cov if x) / len(years) if dated else 0.0
                if dated and frac < (0.3 if src != "search" else 0.5):
                    continue
                # a dated item that covers the label beats an undated one; research's link beats a
                # search hit; then the better known. One item for all the label's dates: a name
                # whose regimes change under it has a timeline in the manual table.
                s = (round(frac, 1) if dated else 0.25, src == "research", e.get("sitelinks", 0))
                if score is None or s > score:
                    best, score, how = q, s, src
        # the border source's own link, year by year, where Cliopatria draws the side; that match where it has none
        if k not in manual and r["scenes"] & clio_scenes and clio.get(r["side"]):
            picks = {y: clio_pick(clio[r["side"]], r["name"], y, clio_ok) for y in years}
            if any(picks.values()):
                # an item of exactly the label's name, live then, over Cliopatria's link of another name
                # (it links its "Sasanian Empire" rows to the Indo-Sassanids)
                eb = ents.get(best or "", {})
                exact = best and (eb.get("label") or "").casefold() in {v.casefold() for v in variants(r["name"])}
                got = [q for q in picks.values() if q]

                def pick(y, picks=picks, best=best, eb=eb, exact=exact, got=got):
                    if exact and covers(eb, y) is not False:
                        return best
                    if picks[y]:
                        return picks[y]
                    # a date the rows of that name miss: the item they have nearest in time
                    return best or min(((abs(y - yy), q) for yy, q in picks.items() if q))[1]
                spans = runs(years, pick)
                how = "cliopatria" if all(picks.values()) else f"cliopatria+{how or 'nearest'}"
        if k not in manual and not spans and best:
            spans = [[years[0], best]]
        rec: dict = {"how": how or "unresolved"}
        if spans:
            rec["spans"] = spans
            rec["wd"] = [ents.get(q, {}).get("label") if q else None for _, q in spans]
            table[k] = rec
        report.append([k, rec["how"], " ; ".join(f"{y:g}:{q}" for y, q in rec.get("spans", [])),
                       " ; ".join(x or "" for x in rec.get("wd", [])), ",".join(sorted(r["scenes"])), f"{years[0]:g}-{years[-1]:g}"])
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    C.mkdir(parents=True, exist_ok=True)
    (C / "report.tsv").write_text("\n".join("\t".join(x) for x in report) + "\n")
    by: dict[str, int] = {}
    for x in report:
        by[x[1].split(":")[0]] = by.get(x[1].split(":")[0], 0) + 1
    print(f"{len(table)} of {len(labels)} labels linked;", by)


if __name__ == "__main__":
    main()
