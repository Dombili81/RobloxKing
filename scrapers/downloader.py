import requests
import os
import re
from scrapers.firebase_db import FirebaseManager


class AssetDownloader:
    def __init__(self):
        # Firebase üzerinden merkezi cookie yönetimi (Render dahil her ortamda aynı)
        self.db = FirebaseManager()

    def _load_cookie(self) -> str | None:
        """
        Cookie öncelik sırası:
        1) Firebase (ROBLOX_COOKIE)
        2) Ortam değişkeni (ROBLOX_COOKIE)
        3) Local cookie.txt (geliştirme için)
        """
        # 1. Firebase
        try:
            cloud = self.db.load_settings()
        except Exception:
            cloud = {}

        raw = cloud.get("ROBLOX_COOKIE")
        if raw:
            raw = str(raw).strip().strip('"').strip("'")
            if raw.startswith(".ROBLOSECURITY="):
                return raw[len(".ROBLOSECURITY="):]
            return raw

        # 2. Env var
        env_cookie = os.environ.get("ROBLOX_COOKIE")
        if env_cookie:
            env_cookie = env_cookie.strip().strip('"').strip("'")
            if env_cookie.startswith(".ROBLOSECURITY="):
                return env_cookie[len(".ROBLOSECURITY="):]
            return env_cookie

        # 3. Local file (dev)
        if os.path.exists("cookie.txt"):
            try:
                with open("cookie.txt", "r", encoding="utf-8") as f:
                    file_cookie = f.read().strip().strip('"').strip("'")
                if file_cookie:
                    if file_cookie.startswith(".ROBLOSECURITY="):
                        return file_cookie[len(".ROBLOSECURITY="):]
                    return file_cookie
            except Exception:
                pass

        return None

    async def download_template(self, asset_id):
        """
        Downloads a Roblox clothing template browserlessly.
        Attempts direct delivery, RoProxy fallback, and authenticated requests if cookie.txt exists.
        """
        print(f"Downloading asset template for ID: {asset_id}")
        
        path = f"downloads/{asset_id}.png"
        os.makedirs("downloads", exist_ok=True)

        # Try to load cookie (Firebase → Env → cookie.txt)
        cookie = self._load_cookie()
        if cookie:
            print(f"Cookie detected (starts with: {cookie[:15]}...). Using authenticated requests.")

        headers = {
            "User-Agent": "Roblox/WinInet",
        }
        if cookie:
            # Roblox cookies MUST be sent as .ROBLOSECURITY
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        # Strategy:
        # 1. Try Direct Asset Delivery
        # 2. Try RoProxy fallback
        # 3. Try version=1 fallback (sometimes bypasses generic blocks)
        
        # We try multiple variants of URLs
        base_urls = [
            f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}",
            f"https://assetdelivery.roproxy.com/v1/asset/?id={asset_id}",
            f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}&version=1"
        ]

        for url in base_urls:
            try:
                print(f"Attempting: {url}")
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
                
                if response.status_code == 200:
                    content = response.content
                    
                    if content.startswith(b"\x89PNG"):
                        with open(path, "wb") as f:
                            f.write(content)
                        print("Download success (Direct PNG).")
                        return path
                    
                    # Check for Image ID in XML/Response
                    text = content.decode("utf-8", errors="ignore")
                    match = re.search(r"rbxassetid://(\d+)", text)
                    if not match:
                        match = re.search(r"id=(\d+)", text)
                        
                    if match:
                        image_id = match.group(1)
                        print(f"Detected Image ID: {image_id}. Fetching PNG...")
                        
                        img_url = f"https://assetdelivery.roblox.com/v1/asset/?id={image_id}"
                        # Try RoProxy as well for the image if direct fails
                        img_urls = [img_url, img_url.replace("roblox.com", "roproxy.com")]
                        
                        for i_url in img_urls:
                            img_resp = requests.get(i_url, headers=headers, timeout=10)
                            if img_resp.status_code == 200 and img_resp.content.startswith(b"\x89PNG"):
                                with open(path, "wb") as f:
                                    f.write(img_resp.content)
                                print(f"Download success via Image ID: {image_id}")
                                return path
                
                print(f"Request failed (Status: {response.status_code})")
            except Exception as e:
                print(f"Error during request: {e}")

        print("\nDownload failed. Tips:")
        print("1. If the item is new/restricted, place your .ROBLOSECURITY inside 'cookie.txt'")
        print("2. Ensure the ID is for a 'Classic Shirt' asset.")
        return None
