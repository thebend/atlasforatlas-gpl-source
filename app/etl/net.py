"""Polite HTTP for the ETL: every request the build makes to an outside service goes through here.

Every request
  - says who is asking: common.UA, the project by its address (https://atlasforatlas.com), never a
    person's email;
  - waits at least `delay` seconds after the previous one (DELAY_S unless the caller knows the
    service asks for less or more; none for map tiles and range reads);
  - retries what is worth retrying, with growing pauses: 429 and 5xx (honouring Retry-After), a
    dropped connection or a timeout, and a body that fails the caller's `check` (a truncated JSON
    reply, an HTML error page where a TIFF should be);
  - refuses a bot-check page served in place of the content (reCAPTCHA, as PMC serves scripts;
    hCaptcha; Cloudflare's challenge): Blocked, never cached or parsed as the source.
Files are written to <dst>.part and renamed into place only when complete, so an interrupted run
never leaves a truncated file that a later run would skip.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any

from etl.common import UA

DELAY_S = 1.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WDQS = "https://query.wikidata.org/sparql"
# a bot check in place of the page; looked for in the first 200 kB of an HTML reply
CHALLENGE = re.compile(rb"g-recaptcha|www\.google\.com/recaptcha|Checking your browser - reCAPTCHA|hcaptcha\.com/"
                       rb"|challenges\.cloudflare\.com|<title>Just a moment\.\.\.</title>", re.I)
_last = 0.0


class Blocked(RuntimeError):
    """The server answered with a bot check (a CAPTCHA) instead of the content."""


def _wait(delay: float) -> None:
    global _last
    gap = time.monotonic() - _last
    if gap < delay:
        time.sleep(delay - gap)
    _last = time.monotonic()


def _req(url: str, params: dict | None, data: bytes | dict | None, headers: dict | None, method: str | None) -> urllib.request.Request:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    return urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})


def _pause(e: Exception, attempt: int, backoff: float) -> float:
    if isinstance(e, urllib.error.HTTPError):
        ra = (e.headers.get("Retry-After") or "").strip()
        if ra.isdigit():
            return float(ra)
    return backoff * (attempt + 1)


def _retrying(url: str, go: Callable[[], Any], tries: int, backoff: float, delay: float, log: Callable[[str], None]) -> Any:
    """Run one request (`go`) until it succeeds or stops being worth retrying."""
    for attempt in range(tries):
        _wait(delay)
        try:
            return go()
        except Blocked:
            raise
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == tries - 1:
                raise
            err: Exception = e
        except (OSError, http.client.HTTPException, ValueError) as e:     # URLError, timeouts, resets; a failed check
            if attempt == tries - 1:
                raise
            err = e
        wait = _pause(err, attempt, backoff)
        log(f"  retry {attempt + 1}/{tries - 1} in {wait:.0f} s: {url[:120]}: {err}")
        time.sleep(wait)
    raise AssertionError("unreachable")


def _blocked(body: bytes, ctype: str, url: str) -> None:
    if "html" in ctype.lower() and CHALLENGE.search(body[:200_000]):
        raise Blocked(f"bot check instead of the page: {url}")


def fetch(url: str, *, params: dict | None = None, data: bytes | dict | None = None, headers: dict | None = None,
          method: str | None = None, timeout: float = 60, delay: float = DELAY_S, tries: int = 4, backoff: float = 5.0,
          check: Callable[[bytes], object] | None = None, log: Callable[[str], None] = print) -> bytes:
    """The body of a GET (or a POST, with `data`: bytes, or a dict sent as a form). `check(body)`
    raises ValueError for a reply that isn't what was asked for, and the request is tried again."""
    req = _req(url, params, data, headers, method)

    def go() -> bytes:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            _blocked(body, r.headers.get("Content-Type", ""), url)
        if check:
            check(body)
        return body
    return _retrying(url, go, tries, backoff, delay, log)


def get_json(url: str, params: dict | None = None, *, strict: bool = True, **kw: Any) -> Any:
    """A JSON reply, parsed (a truncated or non-JSON reply is tried again). strict=False lets
    strings hold raw control characters (Wikidata labels sometimes do)."""
    return json.loads(fetch(url, params=params, check=lambda b: json.loads(b, strict=strict), **kw), strict=strict)


def sparql(query: str, *, endpoint: str = WDQS, post: bool = False, timeout: float = 120, **kw: Any) -> list[dict]:
    """A SPARQL query's result rows (results.bindings), by GET or, for a long query, POST."""
    form = {"query": query, "format": "json"}
    headers = {"Accept": "application/sparql-results+json"}
    d = get_json(endpoint, None if post else form, data=form if post else None, headers=headers, timeout=timeout, **kw)
    return d["results"]["bindings"]


def head(url: str, *, timeout: float = 60, delay: float = DELAY_S, tries: int = 4, backoff: float = 5.0,
         log: Callable[[str], None] = print) -> Message:
    """A HEAD request's headers (Content-Length, for reading a remote file by ranges)."""
    req = _req(url, None, None, None, "HEAD")

    def go() -> Message:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.headers
    return _retrying(url, go, tries, backoff, delay, log)


def download(url: str, dst: Path, *, headers: dict | None = None, timeout: float = 300, delay: float = DELAY_S,
             tries: int = 4, backoff: float = 5.0, check: Callable[[Path], object] | None = None,
             log: Callable[[str], None] = print) -> str:
    """Fetch url to dst atomically; returns the file's sha1. `check(part_path)` raises ValueError for
    a file that isn't what was asked for (it is fetched again)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    req = _req(url, None, None, headers, None)

    def go() -> str:
        h = hashlib.sha1()
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
            ctype = r.headers.get("Content-Type", "")
            first = True
            while chunk := r.read(1 << 20):
                if first:
                    _blocked(chunk, ctype, url)
                    first = False
                f.write(chunk)
                h.update(chunk)
        if check:
            check(part)
        return h.hexdigest()
    try:
        sha = _retrying(url, go, tries, backoff, delay, log)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dst)
    return sha


def is_tiff(body: bytes) -> None:
    """A check for fetch(): the reply is a TIFF (an error page is not)."""
    if body[:2] not in (b"II", b"MM"):
        raise ValueError(f"not a TIFF ({body[:60]!r})")


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def commons_title(page_url: str) -> str:
    """'https://commons.wikimedia.org/wiki/File:A_b.ogg' -> 'File:A b.ogg'."""
    path = urllib.parse.urlparse(page_url).path
    return urllib.parse.unquote(path.rsplit("/wiki/", 1)[1]).replace("_", " ")


def commons_imageinfo(titles: list[str], **extra: str | int) -> dict[str, list[dict]]:
    """Title -> imageinfo list (newest version first) for File: pages, 50 titles per request.

    Keys are the titles as asked; Commons normalises and redirects are followed.
    """
    out: dict[str, list[dict]] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        r = get_json(COMMONS_API, {"action": "query", "format": "json", "formatversion": 2,
                                   "redirects": 1, "prop": "imageinfo",
                                   "iiprop": "url|size|sha1|timestamp", "titles": "|".join(batch),
                                   **extra})
        q = r["query"]
        alias = {t: t for t in batch}
        for kind in ("normalized", "redirects"):
            for m in q.get(kind, []):
                for asked, cur in alias.items():
                    if cur == m["from"]:
                        alias[asked] = m["to"]
        pages = {p["title"]: p for p in q["pages"]}
        for asked, cur in alias.items():
            p = pages.get(cur)
            if p is None or "imageinfo" not in p:
                raise SystemExit(f"Commons has no file {asked!r}")
            out[asked] = p["imageinfo"]
    return out
