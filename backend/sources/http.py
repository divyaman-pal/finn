"""Shared HTTP client: browser-like headers, polite retries, and a disk cache for immutable files (PDFs)."""
import hashlib
import time

import httpx

from ..config import CACHE_DIR

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_client = httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True)


def get(url: str, *, params=None, referer: str | None = None, accept: str | None = None,
        retries: int = 3) -> httpx.Response:
    headers = {}
    if referer:
        headers["Referer"] = referer
    if accept:
        headers["Accept"] = accept
    for attempt in range(retries):
        try:
            r = _client.get(url, params=params, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            return r
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def get_file(url: str, referer: str | None = None) -> bytes:
    """Download once, then serve from disk forever: filings never change after they're published."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".bin")
    if path.exists():
        return path.read_bytes()
    r = get(url, referer=referer)
    r.raise_for_status()
    if r.content.startswith(b"%PDF"):  # dead links often return an HTML page with 200; never cache those
        path.write_bytes(r.content)
    return r.content
