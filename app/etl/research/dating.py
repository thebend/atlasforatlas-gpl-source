"""A date in dispute: the readings scholars give for when something happened, each with its source.

A research item whose date is argued over carries, beside its `date` (the year the tour stops at), a
`dating` block (docs/design/date-ranges.md):

    "dating": {
      "earliest": 300, "latest": 1266,          # astronomical years: 1 BCE is 0, 300 BCE is -299
      "positions": [
        {"from": 300, "to": 1100, "label": "long chronology, older radiocarbon", "by": "Kirch 1985",
         "citation": {"url": "...", "title": "...", "quote": "verbatim, at most 40 words", "kind": "..."}},
        {"from": 1219, "to": 1266, "label": "short chronology, high-precision radiocarbon", "by": "Wilmshurst et al. 2011",
         "citation": {...}}
      ]
    }

`earliest` and `latest` enclose every position; positions run oldest first. Where a source gives a wider
overall span than any one reading ("estimates have ranged from 400 to 1300"), the block's own `citation`
backs it, and an end past every position needs one. Each position's citation is checked like the item's own
(verify_quotes writes its `quote_check`), and an independent verifier passes the block with the card:
it is part of the words a verdict is sealed to (stamp.text_sha).

    python -m etl.research.dating [<name> ...]     check every catalogue's dating blocks (exit 1 on a problem)
"""
from __future__ import annotations

import json
import sys

from etl.common import RESEARCH

MAX_POSITIONS = 4
MAX_LABEL = 60          # characters: the card's bar gives each one a line


def positions(item: dict) -> list[dict]:
    return ((item.get("dating") or {}).get("positions")) or []


def citations(item: dict) -> list[dict]:
    """Every citation an item rests on: its own, then each dating position's."""
    d = item.get("dating") or {}
    own = [d["citation"]] if isinstance(d.get("citation"), dict) else []
    return list(item.get("citations", [])) + own + [p["citation"] for p in positions(item) if isinstance(p.get("citation"), dict)]


def span(item: dict) -> tuple[int, int] | None:
    """The years the dating allows, earliest to latest, or None for an item without one."""
    d = item.get("dating")
    return (d["earliest"], d["latest"]) if d else None


def problems(item: dict) -> list[str]:
    """What is wrong with an item's dating block, as short sentences (none for a sound one or none at all)."""
    d = item.get("dating")
    if d is None:
        return []
    out = []
    lo, hi, ps = d.get("earliest"), d.get("latest"), d.get("positions")
    if not isinstance(lo, int) or not isinstance(hi, int) or lo > hi:
        out.append("earliest and latest must be whole years, earliest first")
    if not isinstance(ps, list) or not 2 <= len(ps) <= MAX_POSITIONS:
        return out + [f"a dispute needs 2 to {MAX_POSITIONS} positions"]
    prev = None
    for i, p in enumerate(ps, 1):
        a, b = p.get("from"), p.get("to")
        if not isinstance(a, int) or not isinstance(b, int) or a > b:
            out.append(f"position {i}: from and to must be whole years, from first")
            continue
        if isinstance(lo, int) and isinstance(hi, int) and (a < lo or b > hi):
            out.append(f"position {i}: {a} to {b} is outside earliest to latest ({lo} to {hi})")
        if prev is not None and a < prev:
            out.append(f"position {i}: positions run oldest first")
        prev = a
        label = (p.get("label") or "").strip()
        if not label or len(label) > MAX_LABEL:
            out.append(f"position {i}: a label of 1 to {MAX_LABEL} characters")
        c = p.get("citation")
        if not isinstance(c, dict) or not c.get("url") or not (c.get("quote") or "").strip():
            out.append(f"position {i}: a citation with a url and a verbatim quote")
        elif len(c["quote"].split()) > 40:
            out.append(f"position {i}: its quote runs over 40 words")
    if isinstance(lo, int) and isinstance(hi, int) and all(isinstance(p.get("from"), int) and isinstance(p.get("to"), int) for p in ps):
        wider = lo < min(p["from"] for p in ps) or hi > max(p["to"] for p in ps)
        c = d.get("citation")
        if wider and not (isinstance(c, dict) and c.get("url") and (c.get("quote") or "").strip()):
            out.append("earliest or latest goes past every position: the block's own citation must give that span")
    y = (item.get("date") or {}).get("year")
    if isinstance(y, int) and isinstance(lo, int) and isinstance(hi, int) and not lo <= y <= hi:
        out.append(f"the card's year {y} is outside earliest to latest")
    return out


def check(names: list[str]) -> int:
    bad = 0
    for name in names:
        cat = json.loads((RESEARCH / f"{name}.raw.json").read_text())
        for it in cat.get("claims", []) + cat.get("events", []):
            for p in problems(it):
                print(f"{name}/{it['id']}: {p}")
                bad += 1
    return bad


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name.removesuffix(".raw.json") for p in RESEARCH.glob("*.raw.json"))
    n = check(names)
    print(f"{n} dating problems" if n else "dating: ok")
    sys.exit(1 if n else 0)
