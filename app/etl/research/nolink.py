"""Books we cite but never link and never keep (sources/no-link.json; docs/design/policy.md, "A book read
in a copy that isn't lawful is cited, never linked or kept"): the registry's `books` (archive.org items of
in-copyright books uploaded without leave) and every page of its `sites` (libraries of such copies).

A citation of such a book carries `url: "book:<id>"` instead of the copy's address, and a `title` built
from the book's author, title, publisher and year. The quote check reads the copy once, in memory, and
keeps only the quote's verdict and the words around it (research/nolink-quotes.json): never the book.

    python -m etl.research.nolink apply [<catalogue> ...]   rewrite citations of these books in the raw
                                                            catalogues (all of them by default)
    python -m etl.research.nolink purge                     delete any copy of them in the fetch cache
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from functools import lru_cache
from urllib.parse import urlparse

from etl.common import CACHE, PROTO, RESEARCH

REGISTRY = PROTO / "sources" / "no-link.json"
KEPT = RESEARCH / "nolink-quotes.json"
PREFIX = "book:"
ARCHIVE = re.compile(r"https?://(?:www\.)?archive\.org/(?:details|stream|download|embed)/([^/?#]+)")


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads(REGISTRY.read_text())


def books() -> dict[str, dict]:
    return {b["id"]: b for b in registry()["books"]}


def sites() -> set[str]:
    """Sites whose copies of books their rightsholders didn't publish (a library of in-copyright books
    put online without leave): any page of theirs is cited, never linked or kept."""
    return {s["host"] for s in registry().get("sites", [])}


def copy_id(url: str) -> str:
    return "copy-" + hashlib.sha1(url.split("#")[0].encode()).hexdigest()[:10]


@lru_cache(maxsize=1)
def by_ia() -> dict[str, dict]:
    return {ia: b for b in books().values() for ia in b.get("ia", [])}


def book_for(url: str) -> dict | None:
    """The registry's book a citation's address is a copy of, or the book a `book:` address names."""
    if url.startswith(PREFIX):
        i = url[len(PREFIX):]
        if i in books():
            return books()[i]
        c = registry().get("copies", {}).get(i)
        return {"id": i, "copy": c} if c else None
    m = ARCHIVE.match(url or "")
    if m:
        return by_ia().get(m.group(1))
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if host and any(host == h or host.endswith("." + h) for h in sites()):
        return {"id": copy_id(url), "copy": url}
    return None


def label(b: dict) -> str:
    return f"{b['author']}, {b['title']} ({b['publisher']}, {b['year']})"


def clean_title(title: str) -> str:
    """A citation's own title, kept (it often names the volume, page or chapter), without the copy it was read in."""
    t = re.sub(r",?\s*(?:read )?(?:at |on |via )?archive\.org(?: OCR| scan| text)?", "", title or "", flags=re.I)
    t = re.sub(r"\(\s*[,;]?\s*\)", "", t)
    t = re.sub(r"\(\s*([^()]*?)[,;]\s*\)", r"(\1)", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,;")


def rewrite(c: dict) -> bool:
    """Turn one citation of a listed book into its unlinked form: its address becomes `book:<id>` (or the
    lawful copy's, once there is one), its title stays its own (cleaned), or the book's if it had none."""
    b = book_for(c.get("url", ""))
    if not b:
        return False
    url = b.get("link") or PREFIX + b["id"]
    if "copy" in b:             # a page of a site of unlawful copies: noted so its quotes can be checked again
        registry().setdefault("copies", {})[b["id"]] = b["copy"]
    title = clean_title(c.get("title", "")) or (label(b) if "author" in b else urlparse(b.get("copy", "")).netloc)
    if c.get("url") == url and c.get("title") == title:
        return False
    c["url"], c["title"] = url, title
    return True


def copy_items(b: dict) -> list[str]:
    """The archive.org items the quote check may read the book from once, in memory (every text file of each:
    a multi-volume item such as the SUNY al-Tabari is one item of many volumes)."""
    return list(b.get("ia", []))


def load_kept() -> dict:
    return json.loads(KEPT.read_text()) if KEPT.exists() else {}


def save_kept(kept: dict) -> None:
    KEPT.write_text(json.dumps(dict(sorted(kept.items())), ensure_ascii=False, indent=1) + "\n")


def window(quote_norm: str, text_norm: str, words: int = 10) -> str:
    """The quote with up to `words` words either side, from the normalised text: all we keep of a book."""
    i = text_norm.find(quote_norm)
    if i < 0:
        return ""
    before = text_norm[:i].split()[-words:]
    after = text_norm[i + len(quote_norm):].split()[:words]
    return " ".join(before + [quote_norm] + after)


def apply(names: list[str]) -> None:
    from etl.research import dating
    files = [RESEARCH / f"{n}.raw.json" for n in names] if names else sorted(RESEARCH.glob("*.raw.json"))
    total = 0
    for p in files:
        raw = p.read_text()
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        n = sum(rewrite(c) for it in (d.get("claims") or []) + (d.get("events") or []) if isinstance(it, dict)
                for c in dating.citations(it))
        if n:
            indent = 1 if raw.startswith('{\n "') else 2
            p.write_text(json.dumps(d, ensure_ascii=False, indent=indent) + ("\n" if raw.endswith("\n") else ""))
            print(f"{p.name}: {n} citations unlinked")
            total += n
    reg = registry()
    if reg.get("copies"):
        reg["copies"] = dict(sorted(reg["copies"].items()))
        REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n")
    print(total, "citations unlinked in all")


def purge() -> None:
    """Delete every cached copy of a listed book: the fetch cache keys a page by its address's characters."""
    fetch = CACHE / "fetch"
    keys = [re.sub(r"[^A-Za-z0-9]+", "_", k) for k in [*by_ia(), *sites()]]
    gone = 0
    for p in fetch.glob("*") if fetch.exists() else []:
        if any(k in p.name for k in keys):
            p.unlink()
            gone += 1
    print(gone, "cached copies deleted")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["apply"]
    {"apply": lambda: apply(rest), "purge": purge}[cmd]()
