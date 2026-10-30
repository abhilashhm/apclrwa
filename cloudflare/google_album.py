"""Bounded reader for publicly shared Google Photos album pages."""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

try:
    from workers import fetch as worker_fetch
except ImportError:  # Local unit tests do not install the Workers runtime.
    worker_fetch = None


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
    decoded = html.unescape(value).replace("\\/", "/").replace("\\u003d", "=").replace("\\u0026", "&").replace("\\u002F", "/")
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


async def _fetch_html(url: str) -> str:
    current = validate_album_url(url)
    for _ in range(5):
        if worker_fetch is None:
            raise RuntimeError("The Cloudflare fetch runtime is unavailable.")
        response = await worker_fetch(current, redirect="manual", headers={"Accept": "text/html", "User-Agent": "APCLRWA-community-portal/1.0"})
        status_code = int(response.status)
        if status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                break
            current = validate_album_url(urljoin(current, location))
            continue
        if status_code != 200:
            raise ValueError("Google Photos did not return a public album page.")
        raw = await response.text()
        if len(raw.encode("utf-8")) > MAX_HTML_BYTES:
            raise ValueError("The Google Photos album page is too large to read.")
        return str(raw)
    raise ValueError("Google Photos redirected too many times while opening the album.")


async def fetch_album(value: str, limit: int = MAX_PHOTOS) -> dict[str, Any]:
    url = validate_album_url(value)
    photos = parse_album_html(await _fetch_html(url))[:limit]
    if not photos:
        raise ValueError("No public photos were found. Confirm that link sharing is enabled and the album contains photos.")
    return {"albumUrl": url, "photos": photos, "count": len(photos)}
