"""Merge the agentic-research catalogue with both verification passes.

Inputs:
  .cache/research/<name>.quotes.json         researcher output + deterministic quote checks (verify_quotes.py)
  research/<name>.verification.part*.json    independent support verdicts (second-pass agents; committed)
Output:
  .cache/research/<name>.json                canonical catalogue (read by the field builders and fronts.py)
  public/data/catalogue/research/<name>.json  (served to the app: stored once, whichever periods and tours use it)

Only items the second pass verified or partially verified are kept: unverified and rejected ones stay
in research/<name>.raw.json and its verification parts as the audit record, and are never served.

Every served item is labelled `label: "AI-verified"`. A person's review, recorded in
research/<name>.reviews.json (etl/research/review.py), is folded into its `review` block (status,
verdict, tier: human or expert, by, date) without touching the evidence, so what the map shows is
always traceable to who checked what; an item the reviewer rejected is left out like an unverified one.
"""
from __future__ import annotations

import json
from collections import Counter

import sys

from etl.common import CATALOGUE, RCACHE, RESEARCH, write_json
from etl.research import dating, review
from etl.research.stamp import text_sha

SERVED = ("verified", "partially-verified", "awaiting-recheck")   # the statuses a card is served with

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
    # every part's verdict on each card, in the parts' order: a later part's stale verdict (sealed on
    # text since rewritten) must not hide an earlier part's verdict sealed on the text as it is now
    cands: dict[str, list[dict]] = {}
    for pp in parts:
        d = json.loads(pp.read_text())
        merged["meta"]["parts"].append(d.get("meta", {}))
        merged["items"].update(d.get("items", {}))
        for k, v in d.get("items", {}).items():
            cands.setdefault(k, []).append(v)
    write_json(vp, merged)
    ver = json.loads(vp.read_text())
    verdicts = ver.get("items", {})
    stats: Counter = Counter()
    edited = set(cat.get("meta", {}).get("edited_ids", []))
    # the owner may serve a card edited since its verdict before it is re-checked: it shows as awaiting
    # that check (no verification badge, docs/design/policy.md), until a new verdict is sealed
    recheck = bool(cat.get("meta", {}).get("edits_awaiting_recheck"))
    bad = [f"{item['id']}: {p}" for item in cat.get("claims", []) + cat.get("events", []) for p in dating.problems(item)]
    if bad:
        raise SystemExit("dating problems (etl/research/dating.py):\n  " + "\n  ".join(bad))
    for item in cat.get("claims", []) + cat.get("events", []):
        checks = [c.get("quote_check") for c in dating.citations(item)]
        # the latest verdict sealed on this card's text as it stands; else the latest of all (checked below)
        sha = text_sha(item)
        v = next((x for x in reversed(cands.get(item["id"], [])) if x.get("sha") == sha), None) \
            or verdicts.get(item["id"], {"status": "unverified", "note": "no verdict from second pass"})
        # a rewritten card keeps no verdict from before its rewrite (etl/research/stamp.py)
        if (item["id"] in edited or v.get("sha")) and v.get("sha") != text_sha(item):
            v = {"status": "awaiting-recheck" if recheck else "unverified", "note": "its text has changed since the verdict"}
        item["verification"] = {
            "status": v.get("status", "unverified"),
            "note": v.get("note", ""),
            "fields_unsupported": v.get("fields_unsupported", []),
            **({"held_to_end": v["held_to_end"]} if "held_to_end" in v else {}),   # an open-ended control claim (fronts.py)
            "quotes_found": sum(1 for c in checks if c in ("found", "fuzzy")),
            "quotes_total": len(checks),
        }
        item["label"] = "AI-verified"
        stats[(item["type"], item["verification"]["status"])] += 1
    kept = SERVED
    for k in ("claims", "events"):
        if k in cat:
            cat[k] = [it for it in cat[k] if it["verification"]["status"] in kept]
    reviewed = review.fold(NAME, cat)
    cat["meta"]["verification"] = {
        "pass1": "deterministic: every quote located in the fetched source text (exact or ≥80% token window)",
        "pass2": ver.get("meta", {}),
        "counts": {f"{k[0]}:{k[1]}": n for k, n in sorted(stats.items()) if k[1] in kept},
    }
    cat["meta"]["label"] = "AI-verified; a historian's review, where there is one, on each item"
    write_json(RCACHE / f"{NAME}.json", cat)
    write_json(CATALOGUE / "research" / f"{NAME}.json", cat)
    left = sum(n for k, n in stats.items() if k[1] not in kept)
    print(dict(stats), f"({left} left out: kept in the raw catalogue only)" if left else "",
          f"review: {reviewed['human']} human-reviewed, {reviewed['expert']} expert-verified, {reviewed['rejected']} rejected" if any(reviewed.values()) else "")


if __name__ == "__main__":
    main()
