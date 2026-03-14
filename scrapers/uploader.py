import requests
import os
import time
import random

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
        print(f"[Uploader] Anti-ban delay{': ' + label if label else ''}: {wait:.1f}s ...")
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
                    r = self.session.patch(url, data=data, json=json, timeout=30)
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
                print(f"[Uploader] Rate limited! Waiting {retry_after}s before retry...")
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

    def upload_asset(self, image_path: str, name: str, description: str = "", item_type: int = 11) -> int | None:
        """
        Upload a Classic Shirt (11) or Classic Pants (12) PNG to the group.
        Returns the new assetId on success, or None on failure.
        """
        if not self._check_session_cap():
            return None

        if not os.path.exists(image_path):
            print(f"[Uploader] File not found: {image_path}")
            return None

        type_label = "Shirt" if item_type == 11 else "Pants"
        print(f"[Uploader] Uploading {type_label} '{name}' → group {self.group_id} ...")

        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/png")}
            data = {
                "AssetType": str(item_type),
                "Name": name,
                "Description": description,
                "GroupId": str(self.group_id),
            }
            r = self._post_with_retry(
                "https://itemconfiguration.roblox.com/v1/asset",
                data=data,
                files=files,
            )

        if r is None:
            print("[Uploader] Upload failed after all retries.")
            return None

        if r.status_code == 200:
            body = r.json()
            asset_id = body.get("assetId") or body.get("AssetId")
            print(f"[Uploader] Upload OK → Asset ID: {asset_id}")
            self._uploads_this_session += 1
            return asset_id
        else:
            print(f"[Uploader] Upload failed (HTTP {r.status_code}): {r.text[:300]}")
            return None

    # Keep backward-compat alias
    def upload_shirt(self, image_path: str, name: str, description: str = "") -> int | None:
        return self.upload_asset(image_path, name, description, item_type=11)

    def update_description(self, asset_id: int, name: str, description: str) -> bool:
        """Update name and description of an already-uploaded asset."""
        payload = {"name": name, "description": description}
        r = self._post_with_retry(
            f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/configure",
            json=payload,
            method="PATCH",
        )
        if r is None:
            return False
        if r.status_code in (200, 204):
            print(f"[Uploader] Description updated for asset {asset_id}.")
            return True
        print(f"[Uploader] Description update failed (HTTP {r.status_code}): {r.text[:200]}")
        return False

    def configure_sale(self, asset_id: int) -> bool:
        """Set the uploaded shirt for sale at self.price Robux. Returns True on success."""
        print(f"[Uploader] Setting asset {asset_id} on sale for {self.price} Robux ...")
        payload = {"isForSale": True, "priceInRobux": self.price}

        r = self._post_with_retry(
            f"https://itemconfiguration.roblox.com/v1/assets/{asset_id}/configure",
            json=payload,
            method="PATCH",
        )

        if r is None:
            print("[Uploader] Sale config failed after all retries.")
            return False

        if r.status_code in (200, 204):
            print(f"[Uploader] Asset {asset_id} is now on sale for {self.price} Robux!")
            return True
        else:
            print(f"[Uploader] Sale config failed (HTTP {r.status_code}): {r.text[:300]}")
            return False

    def upload_and_sell(self, image_path: str, name: str, description: str = "",
                        item_type: int = 11) -> int | None:
        """
        Full pipeline: upload → short pause → set on sale.
        Returns the new assetId on full success, or None on failure.
        """
        asset_id = self.upload_asset(image_path, name, description, item_type)
        if not asset_id:
            return None

        # Brief pause between upload and sale config
        time.sleep(random.uniform(3, 7))

        sale_ok = self.configure_sale(asset_id)
        return asset_id if sale_ok else None
