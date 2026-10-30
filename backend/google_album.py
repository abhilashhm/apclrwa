"""Read photo URLs from a publicly shared Google Photos album page.

Google does not expose a public, unauthenticated album API. This intentionally
small adapter accepts only Google Photos share URLs and returns only image URLs
hosted by Google. It does not store album HTML or photo data.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ALBUM_HOSTS = {"photos.app.goo.gl", "photos.google.com"}
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_PHOTOS = 80
_IMAGE_URL = re.compile(r"(?:https?:)?//lh\d+\.googleusercontent\.com/[^\s\"'<>\\]+", re.IGNORECASE)
_ALBUM_DATA = re.compile(r"AF_initDataCallback\s*\(\s*\{", re.IGNORECASE)


def validate_album_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALBUM_HOSTS
        or not parsed.path
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Use a public Google Photos album link from photos.app.goo.gl or photos.google.com.")
    return value.strip()


def _image_variant(value: str, size: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.split("=", 1)[0]
    return f"{parsed.scheme}://{parsed.netloc}{path}={size}"


def _embedded_album_data(value: str) -> list[object]:
    """Extract JSON payloads used by Google's AF_initDataCallback blocks."""
    results: list[object] = []
    for match in _ALBUM_DATA.finditer(value):
        data_start = value.find("data:", match.end())
        if data_start < 0:
            continue
        payload = value[data_start + len("data:"):].lstrip()
        try:
            parsed, _ = json.JSONDecoder().raw_decode(payload)
        except json.JSONDecodeError:
            continue
        results.append(parsed)
    return results


def _embedded_image_urls(value: str) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            if len(node) >= 2 and isinstance(node[0], str) and isinstance(node[1], list) and node[1] and isinstance(node[1][0], str):
                candidate = node[1][0]
                if "googleusercontent.com" in candidate:
                    found.append(candidate)
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for child in node.values():
                walk(child)

    for payload in _embedded_album_data(value):
        walk(payload)
    return found


def parse_album_html(value: str) -> list[dict[str, str]]:
    decoded = html.unescape(value)
    decoded = (
        decoded.replace("\\/", "/")
        .replace("\\u003d", "=")
        .replace("\\u0026", "&")
        .replace("\\u002F", "/")
    )
    photos: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates = [*_embedded_image_urls(decoded), *_IMAGE_URL.findall(decoded)]
    for candidate in candidates:
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        parsed = urlsplit(candidate.rstrip(",);"))
        if parsed.hostname not in {"lh3.googleusercontent.com", "lh4.googleusercontent.com", "lh5.googleusercontent.com"}:
            continue
        base = f"https://{parsed.hostname}{parsed.path.split('=', 1)[0]}"
        if base in seen:
            continue
        seen.add(base)
        photos.append({"url": _image_variant(base, "w1600-h1200"), "thumbnailUrl": _image_variant(base, "w640-h480")})
        if len(photos) >= MAX_PHOTOS:
            break
    return photos


class _GoogleRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        validate_album_url(new_url)
        return super().redirect_request(request, file, code, message, headers, new_url)


def fetch_album(value: str, limit: int = MAX_PHOTOS) -> dict[str, object]:
    url = validate_album_url(value)
    request = Request(url, headers={"Accept": "text/html", "User-Agent": "APCLRWA-community-portal/1.0"})
    opener = build_opener(_GoogleRedirects)
    with opener.open(request, timeout=12) as response:
        raw = response.read(MAX_HTML_BYTES + 1)
    if len(raw) > MAX_HTML_BYTES:
        raise ValueError("The Google Photos album page is too large to read.")
    photos = parse_album_html(raw.decode("utf-8", errors="replace"))[:limit]
    if not photos:
        raise ValueError("No public photos were found. Confirm that link sharing is enabled and the album contains photos.")
    return {"albumUrl": url, "photos": photos, "count": len(photos)}
