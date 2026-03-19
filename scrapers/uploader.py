import requests
import os
import time
import random
from scrapers.utils import Logger

class AssetUploader:
    """
    Uploads Classic Shirt PNG files to a Roblox group and sets them on sale.
    Uses .ROBLOSECURITY cookie for authentication.

    Anti-ban measures:
    - Randomized delays between uploads (DELAY_MIN to DELAY_MAX seconds)
    - Exponential backoff on API errors
    - Per-session upload cap (MAX_UPLOADS_PER_SESSION)
    - Conservative, human-like request headers
    """

    def __init__(self, cookie: str, group_id: int, price: int = 5,
                 delay_min: int = 45, delay_max: int = 90,
                 max_uploads: int = 10):
        self.cookie = cookie
        self.group_id = group_id
        self.price = price
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_uploads = max_uploads  # 0 = unlimited
        self._uploads_this_session = 0

        self.session = requests.Session()
        self.session.cookies.set(".ROBLOSECURITY", self.cookie, domain=".roblox.com")
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json, text/plain, */*",
        })
        self._csrf_token = None

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_csrf_token(self):
        """Fetch a fresh X-CSRF-TOKEN from Roblox auth endpoint."""
        try:
            r = self.session.post("https://auth.roblox.com/v2/logout", timeout=10)
            token = r.headers.get("x-csrf-token")
            if token:
                self._csrf_token = token
            else:
                print(f"[Uploader] WARNING: Could not get CSRF token (HTTP {r.status_code}).")
        except Exception as e:
            print(f"[Uploader] ERROR getting CSRF token: {e}")

    def _ensure_csrf(self):
        if not self._csrf_token:
            self._get_csrf_token()
        if self._csrf_token:
            self.session.headers["X-CSRF-TOKEN"] = self._csrf_token

    def _random_delay(self, label: str = ""):
        """Wait a random number of seconds between delay_min and delay_max."""
        wait = random.uniform(self.delay_min, self.delay_max)
        Logger.debug(f"Anti-ban gecikmesi ({label}): {wait:.1f}s ...")
        time.sleep(wait)

    def _post_with_retry(self, url, *, data=None, json=None, files=None,
                         method="POST", max_retries=3):
        """Make a request with automatic CSRF refresh and exponential backoff."""
        backoff = 10  # seconds
        for attempt in range(1, max_retries + 1):
            self._ensure_csrf()
            try:
                if method == "POST":
                    r = self.session.post(url, data=data, json=json, files=files, timeout=30)
                else:  # PATCH
                    r = self.session.patch(url, data=data, json=json, files=files, timeout=30)
            except Exception as e:
                print(f"[Uploader] Network error (attempt {attempt}): {e}")
                time.sleep(backoff)
                backoff *= 2
                continue

            # Refresh CSRF and retry on 403
            if r.status_code == 403 and "x-csrf-token" in r.headers:
                self._csrf_token = r.headers["x-csrf-token"]
                self.session.headers["X-CSRF-TOKEN"] = self._csrf_token
                print(f"[Uploader] CSRF refreshed, retrying...")
                continue

            # Roblox rate-limit → 429
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", backoff))
                Logger.warn(f"Hız limitine takıldı! {retry_after}s bekleniyor...")
                time.sleep(retry_after)
                backoff = max(backoff, retry_after) * 2
                continue

            return r  # success or non-recoverable error

        return None  # all retries exhausted

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def _check_session_cap(self) -> bool:
        """Return False (and log) if the per-session upload cap is reached."""
        if self.max_uploads > 0 and self._uploads_this_session >= self.max_uploads:
            print(
                f"[Uploader] Session upload cap reached ({self.max_uploads}). "
                "Skipping remaining uploads for safety."
            )
            return False
        return True

    def _poll_operation(self, operation_id: str) -> int | None:
        """Poll the operation status until it's done or fails."""
        poll_url = f"https://apis.roblox.com/assets/user-auth/v1/operations/{operation_id}"
        print(f"[Uploader] Waiting for upload operation {operation_id} ...")
        
        for _ in range(15):  # Max 15 attempts (approx 30s)
            time.sleep(2)
            try:
                r = self.session.get(poll_url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("done"):
                        response = data.get("response", {})
                        asset_id = response.get("assetId")
                        if asset_id:
                            print(f"[Uploader] Operation Complete -> Asset ID: {asset_id}")
                            return int(asset_id)
                        else:
                            print(f"[Uploader] Operation failed: {data.get('error') or 'Unknown error'}")
                            return None
            except Exception as e:
                print(f"[Uploader] Polling error: {e}")
        
        Logger.debug("Polling zaman aşımı.")
        return None

    def upload_asset(self, image_path: str, name: str, description: str = "", item_type: int = 11) -> int | None:
        """
        Upload a Classic Shirt (11) or Classic Pants (12) PNG using modern APIS endpoint.
        Returns the new assetId on success (after polling), or None on failure.
        """
        if not self._check_session_cap():
            return None

        if not os.path.exists(image_path):
            print(f"[Uploader] File not found: {image_path}")
            return None

        type_label = "Shirt" if item_type == 11 else "Pants"
        Logger.upload(f"{type_label} yükleniyor: '{name}' (Grup: {self.group_id})")

        import json
        request_data = {
            "displayName": name,
            "description": description or "Uploaded by RobloxKing",
            "assetType": int(item_type),
            "creationContext": {
                "creator": {
                    "groupId": int(self.group_id)
                },
                "expectedPrice": 10
            }
        }

        with open(image_path, "rb") as f:
            files = {
                "request": (None, json.dumps(request_data), "application/json"),
                "fileContent": (os.path.basename(image_path), f, "image/png")
            }
            
            # Use specific headers for create.roblox.com
            prev_referer = self.session.headers.get("Referer")
            prev_origin = self.session.headers.get("Origin")
            self.session.headers.update({
                "Referer": "https://create.roblox.com/",
                "Origin": "https://create.roblox.com"
            })
            
            try:
                r = self._post_with_retry(
                    "https://apis.roblox.com/assets/user-auth/v1/assets",
                    files=files
                )
            finally:
                # Restore previous headers
                if prev_referer: self.session.headers["Referer"] = prev_referer
                if prev_origin: self.session.headers["Origin"] = prev_origin

        if r is None:
            Logger.error("Tüm denemelere rağmen yükleme başarısız.")
            return None

        if r.status_code in (200, 201):
            body = r.json()
            operation_id = body.get("path") or body.get("operationId")
            if operation_id:
                # 'path' is often 'operations/SOME_ID'
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

    # Keep backward-compat alias
    def upload_shirt(self, image_path: str, name: str, description: str = "") -> int | None:
        return self.upload_asset(image_path, name, description, item_type=11)

    def update_description(self, asset_id: int, name: str, description: str, item_type: int = 11) -> bool:
        """Update name and description of an already-uploaded asset using modern apis.roblox.com."""
        Logger.debug(f"Açıklama güncelleniyor (Asset: {asset_id})")
        
        url = f"https://apis.roblox.com/assets/user-auth/v1/assets/{asset_id}?updateMask=description"
        import json
        
        type_str = "Shirt" if item_type == 11 else "Pants"
        meta = {
            "assetId": str(asset_id),
            "assetType": type_str,
            "description": description
        }
        
        files = {
            "request": (None, json.dumps(meta), "application/json")
        }
        
        # Use specific headers for create.roblox.com
        prev_referer = self.session.headers.get("Referer")
        prev_origin = self.session.headers.get("Origin")
        self.session.headers.update({
            "Referer": "https://create.roblox.com/",
            "Origin": "https://create.roblox.com"
        })
        
        try:
            r = self._post_with_retry(url, files=files, method="PATCH")
        finally:
            # Restore previous headers
            if prev_referer: self.session.headers["Referer"] = prev_referer
            if prev_origin: self.session.headers["Origin"] = prev_origin

        if r is None:
            return False
        if r.status_code in (200, 204):
            Logger.success(f"Açıklama güncellendi (Asset: {asset_id}).")
            return True
        
        Logger.warn(f"Açıklama güncellenemedi (HTTP {r.status_code})")
        return False

    def configure_sale(self, asset_id: int) -> bool:
        """Set the uploaded asset for sale at self.price Robux. Returns True on success."""
        Logger.debug(f"Ürün satışa çıkarılıyor ({asset_id}, Fiyat: {self.price})")
        
        # 1. Try modern release-to-marketplace (preferred for 2025)
        publish_url = f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/release-to-marketplace"
        payload = {"price": int(self.price), "saleStatus": "OnSale"}

        r = self._post_with_retry(publish_url, json=payload, method="POST")
        if r and r.status_code in (200, 204):
            print(f"[Uploader] Asset {asset_id} successfully RELEASED to marketplace!")
            return True
        
        # 2. Fallback to basic configure endpoint
        print(f"[Uploader] Release endpoint failed ({r.status_code if r else 'None'}). Trying configure PATCH...")
        config_url = f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/configure"
        payload_legacy = {"isForSale": True, "priceInRobux": int(self.price)}
        
        r = self._post_with_retry(config_url, json=payload_legacy, method="PATCH")
        if r and r.status_code in (200, 204):
            Logger.success(f"Satış aktif: {asset_id}")
            return True
        
        Logger.error(f"Satışa çıkarma BAŞARISIZ ({asset_id}).")
        return False

    def upload_and_sell(self, image_path: str, name: str, description: str = "",
                        item_type: int = 11) -> int | None:
        """Upload asset. Publishing (On Sale) is now handled manually by the user."""
        asset_id = self.upload_asset(image_path, name, description, item_type)
        return asset_id
