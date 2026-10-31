"""Human and expert review: a person's verdict on research items, recorded and folded into the catalogues.

Inputs (committed):
  research/reviewers.json             who may review: id, name, role, affiliation, an optional public URL, date added
  research/<name>.reviews.json        per catalogue: {meta, items: {item id: {reviewer, date, verdict, note?}}}
Kept out of the repository and of anything served:
  research/reviewers.private.json     contact emails, {reviewer id: {email}} (gitignored; never read by the build)

A reviewer's `role` sets what their acceptance means: `reviewer` (a person checked the item against
its sources: "Human-reviewed") or `expert` (a historian with stated credentials or an institution:
"Expert-verified"). A verdict is `accepted` (the item says what its sources say), `corrected` (the
reviewer had it fixed in the raw catalogue, then accepted it) or `rejected` (it does not hold). `fold`
writes each verdict into the item's `review` block, with its tier and the reviewer's public name,
affiliation and URL; a rejected item is left out of what is served, as unverified ones are. `merge.py` folds on every merge; recording a
review here also folds it into the served catalogue at once, so the app shows it without a rebuild.

  python -m etl.research.review <name> <item-id> --reviewer <id> --verdict accepted [--note ...] [--date YYYY-MM-DD]
  python -m etl.research.review <name> <item-id> --clear          remove a review
  python -m etl.research.review <name> --pending [--limit N]      served items no one has reviewed yet
  python -m etl.research.review --reviewers                       the registry (no emails)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from etl.common import CATALOGUE, RCACHE, RESEARCH, write_json

REVIEWERS = RESEARCH / "reviewers.json"
VERDICTS = ("accepted", "corrected", "rejected")
ROLES = {"reviewer": "human", "expert": "expert"}      # role -> the tier an acceptance gives
UNREVIEWED = {"status": "unreviewed", "by": None, "date": None}


def reviewers() -> dict[str, dict]:
    """The registry's public entries by id (reviewers.json holds no emails, so none can leak)."""
    if not REVIEWERS.exists():
        return {}
    out = {r["id"]: r for r in json.loads(REVIEWERS.read_text()).get("reviewers", [])}
    for r in out.values():
        if not r.get("placeholder") and r.get("role") not in ROLES:
            raise SystemExit(f"research/reviewers.json: {r['id']} needs a role, one of {', '.join(ROLES)}")
    return out


def reviews_path(name: str) -> Path:
    return RESEARCH / f"{name}.reviews.json"


def load_reviews(name: str) -> dict:
    p = reviews_path(name)
    return json.loads(p.read_text()) if p.exists() else {"meta": {"catalogue": name}, "items": {}}


def fold(name: str, cat: dict) -> dict[str, int]:
    """Write each item's review block from <name>.reviews.json; drop rejected items. Idempotent."""
    revs, who = load_reviews(name)["items"], reviewers()
    counts = {"human": 0, "expert": 0, "rejected": 0}
    for k in ("claims", "events"):
        kept = []
        for item in cat.get(k, []):
            r = revs.get(item["id"])
            if not r:
                item["review"] = dict(UNREVIEWED)
                kept.append(item)
                continue
            p = who.get(r["reviewer"])
            if not p or p.get("placeholder"):
                raise SystemExit(f"{name}/{item['id']}: reviewer {r['reviewer']!r} is not in research/reviewers.json")
            status = "rejected" if r["verdict"] == "rejected" else "accepted"
            tier = ROLES[p["role"]]
            item["review"] = {"status": status, "verdict": r["verdict"], "tier": tier, "by": p["name"], "reviewer": p["id"],
                              "affiliation": p.get("affiliation") or None, "url": p.get("url") or None,
                              "date": r["date"], **({"note": r["note"]} if r.get("note") else {})}
            counts["rejected" if status == "rejected" else tier] += 1
            if status == "accepted":
                item["label"] = "Expert-verified" if tier == "expert" else "Human-reviewed"
                kept.append(item)
        if k in cat:
            cat[k] = kept
    cat.setdefault("meta", {})["review"] = counts
    return counts


def _served(name: str) -> list[Path]:
    return [p for p in (CATALOGUE / "research" / f"{name}.json", RCACHE / f"{name}.json") if p.exists()]


def _refold(name: str) -> None:
    for p in _served(name):
        cat = json.loads(p.read_text())
        fold(name, cat)
        write_json(p, cat)


def _items(name: str) -> dict[str, dict]:
    paths = _served(name)
    if not paths:
        raise SystemExit(f"no merged catalogue for {name}: run `python -m etl.research.merge {name}` first")
    cat = json.loads(paths[0].read_text())
    return {it["id"]: it for k in ("claims", "events") for it in cat.get(k, [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", nargs="?", help="research catalogue, e.g. alexander-conquests-336-323-bce")
    ap.add_argument("item", nargs="?", help="item id")
    ap.add_argument("--reviewer")
    ap.add_argument("--verdict", choices=VERDICTS)
    ap.add_argument("--note")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--clear", action="store_true", help="remove the item's review")
    ap.add_argument("--pending", action="store_true", help="list served items without a review")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--reviewers", action="store_true", help="list the registry")
    a = ap.parse_args()

    if a.reviewers:
        for r in reviewers().values():
            print(f"{r['id']:<20} {r['name']} ({r.get('role', '?')}){' (placeholder: not usable yet)' if r.get('placeholder') else ''}"
                  f"{' · ' + r['affiliation'] if r.get('affiliation') else ''}")
        return
    if not a.name:
        ap.error("name the research catalogue")
    if a.pending:
        revs = load_reviews(a.name)["items"]
        todo = [it for i, it in _items(a.name).items() if i not in revs]
        for it in todo[: a.limit]:
            print(f"{it['id']:<12} {(it.get('title') or it['place']['name'])[:90]}")
        print(f"{len(todo)} of {len(_items(a.name))} served items await review")
        return
    if not a.item:
        ap.error("name the item to review (or use --pending)")

    doc = load_reviews(a.name)
    if a.clear:
        if doc["items"].pop(a.item, None) is None:
            raise SystemExit(f"{a.item} has no review")
    else:
        if a.item not in _items(a.name) and a.item not in doc["items"]:
            raise SystemExit(f"{a.item} is not a served item of {a.name}")
        p = reviewers().get(a.reviewer or "")
        if not p or p.get("placeholder"):
            raise SystemExit(f"reviewer {a.reviewer!r} is not in research/reviewers.json (or is still a placeholder)")
        if not a.verdict:
            ap.error("--verdict is required")
        dt.date.fromisoformat(a.date)
        doc["items"][a.item] = {"reviewer": p["id"], "date": a.date, "verdict": a.verdict, **({"note": a.note} if a.note else {})}
    doc["items"] = dict(sorted(doc["items"].items()))
    reviews_path(a.name).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    _refold(a.name)
    if a.clear:
        print(f"{a.name}/{a.item}: review removed (if it had been rejected, re-merge to serve it again)")
    else:
        print(f"{a.name}/{a.item}: {a.verdict}" + ("; it is left out of the served catalogue" if a.verdict == "rejected" else ""))


if __name__ == "__main__":
    main()
