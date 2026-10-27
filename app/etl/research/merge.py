"""Merge the agentic-research catalogue with both verification passes.

Inputs:
  .cache/research/<name>.quotes.json         researcher output + deterministic quote checks (verify_quotes.py)
  research/<name>.verification.part*.json    independent support verdicts (second-pass agents; committed)
Output:
  .cache/research/<name>.json                canonical catalogue (read by the field builders and fronts.py)
  public/data/catalogue/research/<name>.json  (served to the app: stored once, whichever periods and tours use it)

Only items the second pass verified or partially verified are kept: unverified and rejected ones stay
in research/<name>.raw.json and its verification parts as the audit record, and are never served.

Every item is labelled `label: "AI research — unreviewed"`. A human review
later flips `review.status` (unreviewed -> accepted/rejected) without touching
the evidence, so what the map shows is always traceable to who checked what.
"""
from __future__ import annotations

import json
from collections import Counter

import sys

from etl.common import CATALOGUE, RCACHE, RESEARCH, write_json

NAME = sys.argv[1] if len(sys.argv) > 1 else "northeast-1790-1820"


def main() -> None:
    cat = json.loads((RCACHE / f"{NAME}.quotes.json").read_text())
    # verification comes in parts from independent verifier agents (committed source data);
    # the folded verification.json is regenerated every time
    vp = RCACHE / f"{NAME}.verification.json"
    parts = sorted(RESEARCH.glob(f"{NAME}.verification.part*.json"))
    if not parts:
        raise SystemExit(f"no verification parts for {NAME}")
    merged = {"meta": {"parts": []}, "items": {}}
    for pp in parts:
        d = json.loads(pp.read_text())
        merged["meta"]["parts"].append(d.get("meta", {}))
        merged["items"].update(d.get("items", {}))
    write_json(vp, merged)
    ver = json.loads(vp.read_text())
    verdicts = ver.get("items", {})
    stats: Counter = Counter()
    for item in cat.get("claims", []) + cat.get("events", []):
        checks = [c.get("quote_check") for c in item.get("citations", [])]
        v = verdicts.get(item["id"], {"status": "unverified", "note": "no verdict from second pass"})
        item["verification"] = {
            "status": v.get("status", "unverified"),
            "note": v.get("note", ""),
            "fields_unsupported": v.get("fields_unsupported", []),
            "quotes_found": sum(1 for c in checks if c in ("found", "fuzzy")),
            "quotes_total": len(checks),
        }
        item["label"] = "AI research — unreviewed"
        item["review"] = {"status": "unreviewed", "by": None, "date": None}
        stats[(item["type"], item["verification"]["status"])] += 1
    kept = ("verified", "partially-verified")
    for k in ("claims", "events"):
        if k in cat:
            cat[k] = [it for it in cat[k] if it["verification"]["status"] in kept]
    cat["meta"]["verification"] = {
        "pass1": "deterministic: every quote located in the fetched source text (exact or ≥80% token window)",
        "pass2": ver.get("meta", {}),
        "counts": {f"{k[0]}:{k[1]}": n for k, n in sorted(stats.items()) if k[1] in kept},
    }
    cat["meta"]["label"] = "AI research — unreviewed by a human"
    write_json(RCACHE / f"{NAME}.json", cat)
    write_json(CATALOGUE / "research" / f"{NAME}.json", cat)
    left = sum(n for k, n in stats.items() if k[1] not in kept)
    print(dict(stats), f"({left} left out: kept in the raw catalogue only)" if left else "")


if __name__ == "__main__":
    main()
