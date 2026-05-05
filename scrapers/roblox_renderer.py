"""
roblox_renderer.py — Roblox Thumbnails API'sinden kıyafetli avatar render'ı indirir.
Kıyafet katalog thumbnail'ı = karakterin o kıyafeti giydiği 3D render.
Başarısız olursa caller mevcut shirt_path PNG'yi kullanır (graceful fallback).
"""
import os
import time
import requests
from scrapers.utils import Logger

TMP_DIR        = "tmp"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/assets"
CDN_TIMEOUT    = 25   # tr.rbxcdn.com yavaş olabiliyor
API_TIMEOUT    = 12


class RobloxRenderer:
    def __init__(self, cookie: str = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        if cookie:
            self.session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")

    def get_outfit_render(
        self,
        shirt_id: str,
        pants_id: str = None,
        size: str = "420x420",
    ) -> tuple:
        """
        Shirt ve pants için render PNG indirir.
        Returns: (shirt_render_path_or_None, pants_render_path_or_None)
        """
        os.makedirs(TMP_DIR, exist_ok=True)
        shirt = self._fetch_one(shirt_id, size, "shirt") if shirt_id else None
        pants = self._fetch_one(pants_id, size, "pants") if pants_id else None
        return shirt, pants

    # ────────────────────────────────────────────────────────────────────────────
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
        """Thumbnails API'yi çağırır, gerekirse 'Pending' durumunu bekler."""
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
        """CDN URL'sinden PNG indirir."""
        targets = [url]

        for target in targets:
            try:
                resp = self.session.get(target, timeout=CDN_TIMEOUT)
                if resp.status_code == 200 and resp.content[:4] in (b"\x89PNG", b"\xff\xd8\xff"):
                    out = os.path.join(TMP_DIR, filename)
                    with open(out, "wb") as f:
                        f.write(resp.content)
                    Logger.success(f"Render indirildi: {filename}")
                    return out
            except Exception as e:
                Logger.warn(f"CDN deneme başarısız ({target[:60]}): {e}")
        return None
