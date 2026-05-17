import os
import time
import json
import random
from curl_cffi import CurlMime
from scrapers.utils import Logger, make_session

class AssetUploader:
    """
    Uploads Classic Shirt PNG files to a Roblox group and sets them on sale.
    Uses .ROBLOSECURITY cookie for authentication.
    """

    def __init__(self, cookie: str, group_id: int, price: int = 5,
                 delay_min: int = 45, delay_max: int = 90,
                 max_uploads: int = 10):
        self.cookie = cookie
        self.group_id = group_id
        self.price = price
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_uploads = max_uploads
        self._uploads_this_session = 0

        self.session = make_session(self.cookie)
        self.session.headers.update({
            "Origin": "https://www.roblox.com",
            "Accept": "application/json, text/plain, */*",
        })
        self._csrf_token = None

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_csrf_token(self):
        """Fetch a fresh X-CSRF-TOKEN from Roblox auth endpoint."""
        endpoints = [
            "https://auth.roblox.com/v2/logout",
            "https://auth.roblox.com/v1/authentication-ticket",
        ]
        r = None
        for url in endpoints:
            try:
                r = self.session.post(url, timeout=20)
                token = r.headers.get("x-csrf-token")
                if token:
                    self._csrf_token = token
                    return
            except Exception as e:
                Logger.error(f"CSRF token hatası ({url}): {e}")
        if r:
            Logger.warn(f"CSRF token alınamadı (HTTP {r.status_code}).")

    def _ensure_csrf(self):
        if not self._csrf_token:
            self._get_csrf_token()
        if self._csrf_token:
            self.session.headers["X-CSRF-TOKEN"] = self._csrf_token

    def _random_delay(self, label: str = ""):
        wait = random.uniform(self.delay_min, self.delay_max)
        Logger.debug(f"Anti-ban gecikmesi ({label}): {wait:.1f}s ...")
        time.sleep(wait)

    def _build_mime(self, parts: list) -> CurlMime:
        """
        Build a CurlMime from a list of part dicts.
        Each part: {"name": str, "data": bytes, "content_type": str, "filename": str|None}
        """
        mp = CurlMime()
        for p in parts:
            kwargs = {
                "name": p["name"],
                "data": p["data"] if isinstance(p["data"], bytes) else p["data"].encode(),
                "content_type": p.get("content_type", "application/octet-stream"),
            }
            if p.get("filename"):
                kwargs["filename"] = p["filename"]
            mp.addpart(**kwargs)
        return mp

    def _post_with_retry(self, url, *, data=None, json_body=None,
                         mime_parts=None, method="POST", max_retries=3):
        """
        Make a request with automatic CSRF refresh and exponential backoff.
        mime_parts: list of part dicts for CurlMime (rebuilt each retry).
        """
        backoff = 10
        for attempt in range(1, max_retries + 1):
            self._ensure_csrf()
            try:
                multipart = self._build_mime(mime_parts) if mime_parts else None
                if method == "POST":
                    r = self.session.post(url, data=data, json=json_body,
                                          multipart=multipart, timeout=30)
                else:  # PATCH
                    r = self.session.patch(url, data=data, json=json_body,
                                           multipart=multipart, timeout=30)
            except Exception as e:
                Logger.warn(f"Ağ hatası (deneme {attempt}): {e}")
                time.sleep(backoff)
                backoff *= 2
                continue

            if r.status_code == 403 and "x-csrf-token" in r.headers:
                self._csrf_token = r.headers["x-csrf-token"]
                self.session.headers["X-CSRF-TOKEN"] = self._csrf_token
                Logger.debug("CSRF yenilendi, yeniden deneniyor...")
                continue

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", backoff))
                Logger.warn(f"Hız limitine takıldı! {retry_after}s bekleniyor...")
                time.sleep(retry_after)
                backoff = max(backoff, retry_after) * 2
                continue

            return r

        return None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def _check_session_cap(self) -> bool:
        if self.max_uploads > 0 and self._uploads_this_session >= self.max_uploads:
            Logger.warn(f"Oturum yükleme limiti ({self.max_uploads}) doldu.")
            return False
        return True

    def _poll_operation(self, operation_id: str) -> int | None:
        poll_url = f"https://apis.roblox.com/assets/user-auth/v1/operations/{operation_id}"
        Logger.info(f"Yükleme operasyonu bekleniyor: {operation_id}")

        for _ in range(15):
            time.sleep(2)
            try:
                r = self.session.get(poll_url, timeout=20)
                if r.status_code == 200:
                    body = r.json()
                    if body.get("done"):
                        asset_id = body.get("response", {}).get("assetId")
                        if asset_id:
                            Logger.success(f"Yükleme tamamlandı → Asset ID: {asset_id}")
                            return int(asset_id)
                        else:
                            Logger.error(f"Yükleme başarısız: {body.get('error') or 'Bilinmeyen hata'}")
                            return None
            except Exception as e:
                Logger.warn(f"Polling hatası: {e}")

        Logger.debug("Polling zaman aşımı.")
        return None

    def upload_asset(self, image_path: str, name: str, description: str = "",
                     item_type: int = 11) -> int | None:
        if not self._check_session_cap():
            return None
        if not os.path.exists(image_path):
            Logger.error(f"Dosya bulunamadı: {image_path}")
            return None

        type_label = "Shirt" if item_type == 11 else "Pants"
        Logger.upload(f"{type_label} yükleniyor: '{name}' (Grup: {self.group_id})")

        request_data = {
            "displayName": name,
            "description": description or "Uploaded by RobloxKing",
            "assetType": int(item_type),
            "creationContext": {
                "creator": {"groupId": int(self.group_id)},
                "expectedPrice": 10
            }
        }

        with open(image_path, "rb") as f:
            file_bytes = f.read()

        mime_parts = [
            {
                "name": "request",
                "data": json.dumps(request_data).encode(),
                "content_type": "application/json",
                "filename": None,
            },
            {
                "name": "fileContent",
                "data": file_bytes,
                "content_type": "image/png",
                "filename": os.path.basename(image_path),
            },
        ]

        prev_referer = self.session.headers.get("Referer")
        prev_origin = self.session.headers.get("Origin")
        self.session.headers.update({
            "Referer": "https://create.roblox.com/",
            "Origin": "https://create.roblox.com",
        })

        try:
            r = self._post_with_retry(
                "https://apis.roblox.com/assets/user-auth/v1/assets",
                mime_parts=mime_parts
            )
        finally:
            if prev_referer:
                self.session.headers["Referer"] = prev_referer
            elif "Referer" in self.session.headers:
                del self.session.headers["Referer"]
            if prev_origin:
                self.session.headers["Origin"] = prev_origin

        if r is None:
            Logger.error("Tüm denemelere rağmen yükleme başarısız.")
            return None

        if r.status_code in (200, 201):
            body = r.json()
            operation_id = body.get("path") or body.get("operationId")
            if operation_id:
                op_id = operation_id.split("/")[-1]
                asset_id = self._poll_operation(op_id)
                if asset_id:
                    self._uploads_this_session += 1
                    return asset_id
            return None
        else:
            Logger.error(f"Yükleme BAŞARISIZ (HTTP {r.status_code})")
            Logger.debug(f"Response: {r.text[:500]}")
            return None

    def upload_shirt(self, image_path: str, name: str, description: str = "") -> int | None:
        return self.upload_asset(image_path, name, description, item_type=11)

    def update_description(self, asset_id: int, name: str, description: str,
                           item_type: int = 11) -> bool:
        Logger.debug(f"Açıklama güncelleniyor (Asset: {asset_id})")

        url = f"https://apis.roblox.com/assets/user-auth/v1/assets/{asset_id}?updateMask=description"
        type_str = "Shirt" if item_type == 11 else "Pants"
        meta = {
            "assetId": str(asset_id),
            "assetType": type_str,
            "description": description,
        }

        mime_parts = [
            {
                "name": "request",
                "data": json.dumps(meta).encode(),
                "content_type": "application/json",
                "filename": None,
            }
        ]

        prev_referer = self.session.headers.get("Referer")
        prev_origin = self.session.headers.get("Origin")
        self.session.headers.update({
            "Referer": "https://create.roblox.com/",
            "Origin": "https://create.roblox.com",
        })

        try:
            r = self._post_with_retry(url, mime_parts=mime_parts, method="PATCH")
        finally:
            if prev_referer:
                self.session.headers["Referer"] = prev_referer
            elif "Referer" in self.session.headers:
                del self.session.headers["Referer"]
            if prev_origin:
                self.session.headers["Origin"] = prev_origin

        if r is None:
            return False
        if r.status_code in (200, 204):
            Logger.success(f"Açıklama güncellendi (Asset: {asset_id}).")
            return True

        Logger.warn(f"Açıklama güncellenemedi (HTTP {r.status_code})")
        return False

    def configure_sale(self, asset_id: int) -> bool:
        Logger.debug(f"Ürün satışa çıkarılıyor ({asset_id}, Fiyat: {self.price})")

        publish_url = f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/release-to-marketplace"
        r = self._post_with_retry(publish_url,
                                  json_body={"price": int(self.price), "saleStatus": "OnSale"},
                                  method="POST")
        if r and r.status_code in (200, 204):
            Logger.success(f"Asset {asset_id} pazaryerine yayınlandı!")
            return True

        Logger.warn(f"Release endpoint başarısız ({r.status_code if r else 'None'}), configure PATCH deneniyor...")
        config_url = f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/configure"
        r = self._post_with_retry(config_url,
                                  json_body={"isForSale": True, "priceInRobux": int(self.price)},
                                  method="PATCH")
        if r and r.status_code in (200, 204):
            Logger.success(f"Satış aktif: {asset_id}")
            return True

        Logger.error(f"Satışa çıkarma BAŞARISIZ ({asset_id}).")
        return False

    def upload_and_sell(self, image_path: str, name: str, description: str = "",
                        item_type: int = 11) -> int | None:
        return self.upload_asset(image_path, name, description, item_type)
