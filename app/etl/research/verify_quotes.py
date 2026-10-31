"""Deterministic first verification pass for the agentic-research catalogue.

For every citation: fetch the source once, reduce it to plain text and check
that the quoted words really appear there (exact after normalisation, else a
token-window fuzzy match). archive.org book pages are checked against the
item's OCR full text. Results are written next to each citation as
`quote_check: found|fuzzy|missing|unfetchable`, and a per-item summary is
saved for the second (support) pass.

Run: uv run python -m etl.research.verify_quotes <catalogue-name>   (reads research/<name>.raw.json)
"""
from __future__ import annotations

import html
import http.client
import json
import re
import subprocess
import unicodedata
import urllib.error
import urllib.parse

from etl import net
from etl.common import CACHE, RCACHE, RESEARCH, write_json

import sys
NAME = sys.argv[1] if len(sys.argv) > 1 else "northeast-1790-1820"
RAW = RESEARCH / f"{NAME}.raw.json"
OUTP = RCACHE / f"{NAME}.quotes.json"
FETCH = CACHE / "fetch"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("-\n", "").lower()
    s = re.sub(r"[\W_]+", " ", s)       # letters of any script: a Russian quote is checked as words, not reduced to its digits
    return re.sub(r"\s+", " ", s).strip()


def to_text(raw: str) -> str:
    # a plain-text body (an archive.org _djvu.txt download, a Gutenberg .txt) has no tags to strip,
    # and its OCR's stray "<" would otherwise swallow the text up to the next ">"
    if not re.search(r"(?i)<(html|body|head|div|p|!doctype)\b", raw[:5000]):
        return html.unescape(raw)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return html.unescape(raw)


def source_url(url: str) -> str:
    # (a citation that names the item's text file itself, whose name needn't be the item's, is read as cited)
    m = re.match(r"https?://archive\.org/(?:details|stream)/([^/?#]+)/?(?:[?#].*)?$", url)
    if m:
        ident = m.group(1)
        return f"https://archive.org/stream/{ident}/{ident}_djvu.txt"
    # non-ASCII titles (Starčevo, Ötzi) must be percent-encoded for urllib
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def pdf_text(raw: bytes) -> str:
    """A PDF's text (an arXiv paper, a scanned article), by poppler's pdftotext where it is installed;
    without it the PDF counts as unfetchable rather than as a page its quotes are missing from."""
    try:
        return subprocess.run(["pdftotext", "-q", "-", "-"], input=raw, capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def fetch(url: str) -> str | None:
    FETCH.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9]+", "_", url)[:180]
    p = FETCH / key
    if p.exists():
        return p.read_text(errors="replace") or None
    try:
        raw = net.fetch(url, headers={"Accept": "text/html,text/plain,*/*"}, delay=0.4, tries=3, backoff=3)
        body = pdf_text(raw) if raw[:5] == b"%PDF-" else raw.decode("utf-8", "replace")
    except net.Blocked:
        return None                 # a bot check, not the page: not kept, so a later run asks again
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        body = ""                   # gone, refused or unreachable after retries: kept as nothing
    p.write_text(body)
    return body or None


PMC = re.compile(r"https?://(?:pmc\.ncbi\.nlm\.nih\.gov/articles|www\.ncbi\.nlm\.nih\.gov/pmc/articles)/(PMC\d+)")


def source_text(url: str) -> str | None:
    """The cited page as plain text. PMC often serves scripts a reCAPTCHA page instead of the article:
    then the same open-access article is read from Europe PMC (full-text XML where it has it, and the
    abstract, which is all it holds for some journals)."""
    m = PMC.match(url)
    if not m:
        body = fetch(source_url(url))
        return to_text(body) if body else None
    texts = []
    body = fetch(url)
    if body and "Checking your browser - reCAPTCHA" not in body:
        texts.append(to_text(body))
    else:
        rest = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        for u in (f"{rest}/{m.group(1)}/fullTextXML", f"{rest}/search?query=PMCID:{m.group(1)}&resultType=core&format=json"):
            b = fetch(u)
            if b:
                texts.append(to_text(b))
    return "\n".join(texts) or None


def check(quote: str, text: str) -> str:
    q, t = norm(quote), norm(text)
    if not q:
        return "missing"
    if q in t:
        return "found"
    qt = q.split()
    if len(qt) < 4:
        return "missing"
    words = t.split()
    need = max(4, int(len(qt) * 0.8))
    qs = set(qt)
    # sliding window of the quote's length (+30%) over the source
    win = int(len(qt) * 1.3) + 2
    first = {w for w in qt[:3]}
    for i, w in enumerate(words):
        if w not in first:
            continue
        hit = sum(1 for x in words[i:i + win] if x in qs)
        if hit >= need:
            return "fuzzy"
    return "missing"


def main() -> None:
    cat = json.loads(RAW.read_text())
    cache: dict[str, str | None] = {}
    summary = {}
    for item in cat.get("claims", []) + cat.get("events", []):
        res = []
        for c in item.get("citations", []):
            src = c.get("url", "")
            if src not in cache:
                cache[src] = source_text(src)
            text = cache[src]
            st = "unfetchable" if text is None else check(c.get("quote", ""), text)
            c["quote_check"] = st
            res.append(st)
        summary[item["id"]] = res
    write_json(OUTP, cat)
    flat = [s for v in summary.values() for s in v]
    print({k: flat.count(k) for k in ("found", "fuzzy", "missing", "unfetchable")},
          "items with >=1 found/fuzzy:", sum(1 for v in summary.values() if any(s in ("found", "fuzzy") for s in v)),
          "/", len(summary), "sources fetched:", len(cache))


if __name__ == "__main__":
    main()
