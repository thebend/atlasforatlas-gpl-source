"""Tie a verifier's verdicts to the words it checked, so a rewritten card can't keep an old verdict.

    python -m etl.research.stamp <name> mark          list the cards changed since the last commit in meta.edited_ids
    python -m etl.research.stamp <name> seal <part>   record what a verification part checked (e.g. partz2)

merge.py leaves out a card named in meta.edited_ids unless its verdict is sealed to its present title and
statement, and any card whose sealed verdict no longer matches. Seal right after verifying, and after applying
a verifier's own fix word for word; any other change needs verifying again."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys

from etl.common import RESEARCH


def text_sha(item: dict) -> str:
    return hashlib.sha1(f"{item.get('title') or ''}|{item.get('statement') or ''}".encode()).hexdigest()[:16]


def _save(path, data, raw: str) -> None:
    indent = 1 if raw.startswith('{\n "') else 2
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + ("\n" if raw.endswith("\n") else ""))


def mark(name: str) -> None:
    path = RESEARCH / f"{name}.raw.json"
    raw = path.read_text()
    new = json.loads(raw)
    rel = path.resolve().relative_to(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    old = json.loads(subprocess.check_output(["git", "show", f"HEAD:{rel}"], text=True))
    before = {i["id"]: text_sha(i) for i in old.get("events", []) + old.get("claims", [])}
    changed = {i["id"] for i in new.get("events", []) + new.get("claims", []) if before.get(i["id"]) != text_sha(i)}
    ids = sorted(set(new["meta"].get("edited_ids", [])) | changed)
    new["meta"]["edited_ids"] = ids
    _save(path, new, raw)
    print(f"{len(changed)} changed; {len(ids)} cards must have a sealed verdict")


def seal(name: str, part: str) -> None:
    raw = json.loads((RESEARCH / f"{name}.raw.json").read_text())
    now = {i["id"]: text_sha(i) for i in raw.get("events", []) + raw.get("claims", [])}
    path = RESEARCH / f"{name}.verification.{part}.json"
    text = path.read_text()
    d = json.loads(text)
    n = 0
    for k, v in d["items"].items():
        if k in now:
            v["sha"] = now[k]
            n += 1
    _save(path, d, text)
    print(f"{n} verdicts sealed")


if __name__ == "__main__":
    if sys.argv[2] == "mark":
        mark(sys.argv[1])
    else:
        seal(sys.argv[1], sys.argv[3])
