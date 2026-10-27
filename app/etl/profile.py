"""Build profiles: which sources a build may ship (sources/profiles.json; docs/design/licensing.md).

ATLAS_PROFILE picks one (default "open"). A profile blocks licence classes from sources/catalogue.json;
the "commercial" profile blocks noncommercial and unverified. Under it:
  - every scene manifest is rewritten before any step reads it (etl/common.py): the profile's scene
    overrides first, then its `replace` map on the manifest's per-layer source lists, and every
    border source the manifest still names must be allowed, or the build stops;
  - steps that read a blocked source skip it and remove what an earlier build left (fetch.sky's
    gufm1.json), and per-record licences are filtered (GBIF records; Commons media, where the
    profile's `media_blocks` can block more classes);
  - the served research catalogues keep every citation's link, but quotes past the profile's
    `quotes` caps are withheld (trim_quotes, from etl/catalogue.py);
  - the last step (etl/licences.py) scans the built data for anything blocked and fails if it finds it.

A scene override (profiles.<name>.scenes.<id>) replaces top-level manifest keys, except:
  "etl"            merged one level deep; in its "borders", {"keep": "<source>"} stands for the
                   manifest's own entry for that source (an OHM relation list, say)
  "pipeline_swap"  {step: replacement}: a pipeline step replaced by a shared step name, or dropped (null)
  "sources"        merged per layer
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
PROFILES = json.loads((PROTO / "sources" / "profiles.json").read_text())["profiles"]
CATALOGUE = json.loads((PROTO / "sources" / "catalogue.json").read_text())["sources"]

NAME = os.environ.get("ATLAS_PROFILE", "open")
if NAME not in PROFILES:
    raise SystemExit(f"ATLAS_PROFILE={NAME!r}: not in sources/profiles.json ({', '.join(PROFILES)})")
PROFILE = PROFILES[NAME]
BLOCKS: set[str] = set(PROFILE.get("blocks", []))

# a manifest's etl.borders names -> the catalogue datasets each one reads; North America leaves
# historical-basemaps out itself if a profile blocks it (Cliopatria instead: etl/history/na_sides.py)
BORDER_SOURCES = {
    "cshapes": ["cshapes"], "cliopatria": ["cliopatria"], "ohm": ["ohm"],
    "europe": ["cshapes", "hb"],                                   # etl/fetch/europe/borders.py
    "north-america": ["newberry", "royce", "ohm", "canada"],      # etl/fetch/north_america, etl/history/na_sides.py
    "antarctica": ["claims"],
}


def blocked_class(cls: str) -> bool:
    return cls in BLOCKS


def blocked(source_id: str) -> bool:
    """True when this profile may not ship the dataset (a catalogue id). A source the catalogue marks
    `blocks_commercial` (open licence, but its owner refuses commercial use, say) counts as noncommercial."""
    s = CATALOGUE.get(source_id)
    if s is None:
        raise SystemExit(f"profile: {source_id!r} is not in sources/catalogue.json")
    return s["cls"] in BLOCKS or ("noncommercial" in BLOCKS and bool(s.get("blocks_commercial")))


def _name(b) -> str:
    return b if isinstance(b, str) else b.get("source") or b.get("keep")


def apply(m: dict) -> dict:
    """The manifest as this profile builds it (unchanged under "open")."""
    if not BLOCKS:
        return m
    m = copy.deepcopy(m)
    ov = PROFILE.get("scenes", {}).get(m["id"], {})
    for k, v in ov.items():
        if k == "etl":
            etl = m.setdefault("etl", {})
            for ek, ev in v.items():
                if ek == "borders":
                    own = {_name(b): b for b in etl.get("borders", [])}
                    ev = [own[b["keep"]] if isinstance(b, dict) and "keep" in b else b for b in ev]
                etl[ek] = copy.deepcopy(ev)
        elif k == "pipeline_swap":
            out = []
            for st in m.get("pipeline", []):
                key = st if isinstance(st, str) else st.get("step")
                if key in v:
                    if v[key] is not None and v[key] not in out:
                        out.append(v[key])
                else:
                    out.append(st)
            m["pipeline"] = out
        elif k == "sources":
            m["sources"] = {**m.get("sources", {}), **v}
        else:
            m[k] = copy.deepcopy(v)
    rep = PROFILE.get("replace", {})
    for layer, ids in (m.get("sources") or {}).items():
        new = []
        for i in ids:
            j = rep.get(i, i)
            if j not in new:
                new.append(j)
        m["sources"][layer] = new
    check(m)
    return m


def check(m: dict) -> None:
    """Stop the build when a profiled manifest still names a blocked source."""
    bad = []
    for b in (m.get("etl") or {}).get("borders", []):
        bad += [f"etl.borders {_name(b)} ({s})" for s in BORDER_SOURCES.get(_name(b), [_name(b)]) if blocked(s)]
    for layer, ids in (m.get("sources") or {}).items():
        bad += [f"sources.{layer} {i}" for i in ids if blocked(i)]
    if bad:
        raise SystemExit(f"profile {NAME}: scene {m['id']} still uses blocked sources: {'; '.join(bad)}. "
                         "Give it an override in sources/profiles.json.")


def _host(url: str) -> str:
    h = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return h[4:] if h.startswith("www.") else h


def trim_quotes(cats: dict[str, dict]) -> dict:
    """The profile's quotation policy ("quotes") on the research catalogues the app is served
    (etl/catalogue.py), in place. Every citation keeps its link and title; its quote is withheld
    (`quote_withheld`) when it is longer than max_words, or when the quotes already kept from the
    same page reach per_url_words. Hosts in `open_hosts` publish under an open licence or in the
    public domain and keep every quote (Wikipedia's are shown with its CC BY-SA notice)."""
    pol = PROFILE.get("quotes")
    if not pol:
        return {}
    cap, per_url = pol.get("max_words", 10 ** 9), pol.get("per_url_words", 10 ** 9)
    free = tuple(pol.get("open_hosts", []))
    used: dict[str, int] = {}
    n = {"kept": 0, "withheld_long": 0, "withheld_page_cap": 0}
    for name in sorted(cats):
        for item in cats[name].get("claims", []) + cats[name].get("events", []):
            for c in item.get("citations", []):
                q = c.get("quote")
                if not q:
                    continue
                h, w = _host(c.get("url", "")), len(q.split())
                if any(h == f or h.endswith("." + f) for f in free):
                    n["kept"] += 1
                    continue
                why = "long" if w > cap else "page_cap" if used.get(c["url"], 0) + w > per_url else None
                if why:
                    del c["quote"]
                    c["quote_withheld"] = f"profile {NAME}: " + (f"over {cap} words" if why == "long" else f"over {per_url} words quoted from this page")
                    n[f"withheld_{why}"] += 1
                else:
                    used[c["url"]] = used.get(c["url"], 0) + w
                    n["kept"] += 1
    return n


def media_class(licence: str) -> str:
    """A media file's licence as Commons names it ("CC BY-SA 4.0", "Public domain", "CC0") -> licence class."""
    s = (licence or "").lower().replace("-", " ")
    if not s:
        return "unverified"
    if " nc" in f" {s}" or "noncommercial" in s or " nd" in f" {s}":
        return "noncommercial"        # NoDerivatives is grouped here: the build adapts (crops, loops) media
    if "public domain" in s or "cc0" in s or "pdm" in s:
        return "public"
    if "by sa" in s or "gfdl" in s:
        return "share-alike"
    if s.startswith("cc by"):
        return "attribution"
    return "unverified"


def media_blocked(licence: str) -> bool:
    """True when this profile may not ship a media file under this licence: a blocked class, or one of the
    profile's `media_blocks` (the commercial profile adds share-alike: the build adapts its recordings,
    and CC counts a sound timed to moving images as an adaptation, which would make the loops BY-SA)."""
    c = media_class(licence)
    return c in BLOCKS or c in PROFILE.get("media_blocks", [])
