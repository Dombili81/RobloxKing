"""
roblox_renderer.py — Roblox Thumbnails API'sinden kıyafetli avatar render'ı indirir.
Kıyafet katalog thumbnail'ı = karakterin o kıyafeti giydiği 3D render.
Başarısız olursa caller mevcut shirt_path PNG'yi kullanır (graceful fallback).
"""
import os
import time
import random
from curl_cffi import requests as cffi_requests
from scrapers.utils import Logger, make_session

TMP_DIR        = "tmp"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/assets"
CDN_TIMEOUT    = 20
API_TIMEOUT    = 12

# Ücretsiz proxy listesi API'leri (yalnızca herkese açık CDN indirme için)
_PROXY_LIST_URLS = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

_proxy_cache: list[str] = []
_proxy_cache_time: float = 0
_PROXY_CACHE_TTL = 600  # 10 dakika


def _fetch_public_proxies() -> list[str]:
    global _proxy_cache, _proxy_cache_time
    if _proxy_cache and (time.time() - _proxy_cache_time) < _PROXY_CACHE_TTL:
        return _proxy_cache
    proxies = []
    for url in _PROXY_LIST_URLS:
        try:
            r = cffi_requests.get(url, timeout=10, impersonate="chrome124")
            if r.status_code == 200:
                lines = [l.strip() for l in r.text.splitlines() if ":" in l.strip()]
                proxies.extend(f"http://{l}" for l in lines[:80])
                if proxies:
                    break
        except Exception:
            continue
    random.shuffle(proxies)
    _proxy_cache = proxies
    _proxy_cache_time = time.time()
    Logger.info(f"{len(proxies)} public proxy yüklendi.")
    return proxies


def _cdn_session_with_proxy(proxy: str) -> cffi_requests.Session:
    return cffi_requests.Session(impersonate="chrome124", proxy=proxy)


class RobloxRenderer:
    def __init__(self, cookie: str = None):
        self.cookie = cookie
        self.session = make_session(cookie)

    def get_outfit_render(
        self,
        shirt_id: str,
        pants_id: str = None,
        size: str = "420x420",
    ) -> tuple:
        os.makedirs(TMP_DIR, exist_ok=True)
        shirt = self._fetch_one(shirt_id, size, "shirt") if shirt_id else None
        pants = self._fetch_one(pants_id, size, "pants") if pants_id else None
        return shirt, pants

    def _fetch_one(self, asset_id: str, size: str, label: str) -> str | None:
        try:
            image_url = self._get_thumbnail_url(asset_id, size)
            if not image_url:
                return None
            return self._download_png(image_url, f"render_{asset_id}_{label}.png")
        except Exception as e:
            Logger.warn(f"Render alınamadı ({label} {asset_id}): {e}")
            return None

    def _get_thumbnail_url(self, asset_id: str, size: str) -> str | None:
        for attempt in range(3):
            try:
                r = self.session.get(
                    THUMBNAILS_URL,
                    params={"assetIds": asset_id, "size": size, "format": "Png", "isCircular": "false"},
                    timeout=API_TIMEOUT,
                )
                if r.status_code != 200:
                    return None
                data = r.json().get("data", [])
                if not data:
                    return None
                item = data[0]
                state = item.get("state", "")
                if state == "Completed":
                    return item.get("imageUrl")
                if state == "Pending":
                    time.sleep(3)
                    continue
                return None
            except Exception:
                time.sleep(2)
        return None

    def _download_png(self, url: str, filename: str) -> str | None:
        # Önce proxy olmadan dene
        result = self._try_download(url, filename, session=self.session)
        if result:
            return result

        # Başarısız olduysa public proxy rotasyonu ile dene
        Logger.info("Direkt bağlantı başarısız, public proxy deneniyor...")
        proxies = _fetch_public_proxies()
        for proxy in proxies[:15]:
            try:
                s = _cdn_session_with_proxy(proxy)
                result = self._try_download(url, filename, session=s, timeout=12)
                if result:
                    Logger.info(f"Proxy ile indirildi: {proxy}")
                    return result
            except Exception:
                continue

        Logger.warn(f"CDN indirme tamamen başarısız: {filename}")
        return None

    def _try_download(self, url: str, filename: str, session, timeout: int = CDN_TIMEOUT) -> str | None:
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200 and resp.content[:4] in (b"\x89PNG", b"\xff\xd8\xff"):
                out = os.path.join(TMP_DIR, filename)
                with open(out, "wb") as f:
                    f.write(resp.content)
                return out
        except Exception:
            pass
        return None
