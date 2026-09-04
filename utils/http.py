"""
Minimal HTTP client on top of the standard library.

Why not `requests`? The project installs with a short requirements list and
must keep working on locked-down / offline machines. urllib covers the few
things we need (JSON APIs, RSS, local Ollama) with proxy + timeout + gzip
support and adds no dependency.
"""

import gzip
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_UA = "Mozilla/5.0 (compatible; ai-trader/1.0; +local-analysis)"


class HttpError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url

    def __str__(self) -> str:  # pragma: no cover - repr helper
        base = super().__str__()
        return f"{base} [{self.status}] {self.url}".strip()


def _opener(proxy: Optional[str]):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def request(
    url: str,
    *,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 8.0,
    proxy: Optional[str] = None,
) -> bytes:
    """Perform a request and return raw bytes. Raises HttpError on any failure."""
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{query}"

    body = None
    all_headers = {"User-Agent": DEFAULT_UA, "Accept-Encoding": "gzip, deflate"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        all_headers["Content-Type"] = "application/json"
    if headers:
        all_headers.update(headers)

    req = urllib.request.Request(url, data=body, headers=all_headers, method=method)

    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise HttpError(f"HTTP error: {exc.reason} {detail[:180]}".strip(), exc.code, url) from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"connection failed: {exc.reason}", None, url) from exc
    except Exception as exc:  # noqa: BLE001 - timeouts, TLS, ...
        raise HttpError(f"{exc.__class__.__name__}: {exc}", None, url) from exc

    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass

    return raw


def request_text(url: str, **kwargs) -> str:
    return request(url, **kwargs).decode("utf-8", "replace")


def request_json(url: str, **kwargs) -> Any:
    text = request_text(url, **kwargs)
    text = text.strip()
    if not text:
        raise HttpError("empty response", None, url)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HttpError(f"invalid json: {exc.msg}", None, url) from exc


def is_absolute_url(value: str) -> bool:
    return str(value).startswith(("http://", "https://"))
