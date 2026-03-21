import requests
import re
from scrapers.utils import Logger

class RobloxScraper:
    def __init__(self, cookie=None, sort_type: int = 2, sort_agg: int = 5):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self.has_auth = False
        # Search sort config (mirrors Roblox Catalog API)
        # sort_type: 0=Relevance, 1=Favorited, 2=Sales, 4=PriceAsc, 5=PriceDesc...
        # sort_agg : 1=PastDay, 3=PastWeek, 4=PastMonth, 5=AllTime
        self.sort_type = sort_type
        self.sort_agg  = sort_agg
        self._desc_cache = {} # Cache to avoid 429s on description calls
        
        if cookie:
            self.session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
            try:
                # Fetch CSRF token
                r = self.session.post("https://auth.roblox.com/v2/logout")
                csrf = r.headers.get("x-csrf-token")
                if csrf:
                    self.session.headers["X-CSRF-TOKEN"] = csrf
                    self.has_auth = True
                    Logger.success("Roblox oturumu başarıyla doğrulandı (CSRF aktif).")
            except Exception as e:
                Logger.error(f"Oturum doğrulama başarısız: {e}")

    def _request_with_retry(self, method, url, max_retries=3, initial_delay=2, **kwargs):
        """Helper to handle 429 Rate Limit with exponential backoff."""
        import time
        attempt = 0
        while attempt < max_retries:
            try:
                if method.upper() == "GET":
                    r = self.session.get(url, **kwargs)
                else:
                    r = self.session.post(url, **kwargs)
                
                if r.status_code == 429:
                    wait_time = initial_delay * (2 ** attempt)
                    Logger.warn(f"Oran limitine takıldı (429)! {wait_time}s bekleniyor ({attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                    attempt += 1
                    continue
                return r
            except Exception as e:
                Logger.error(f"İstek hatası: {e}")
                time.sleep(initial_delay)
                attempt += 1
        return None

    async def start(self):
        return self

    async def stop(self):
        self.session.close()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def search_and_get_assets(self, keyword, count=5, asset_type=11):
        asset_name = "Shirt" if asset_type == 11 else "Pants" if asset_type == 12 else f"Accessory_{asset_type}"
        category = 3 if asset_type in (11, 12, 2) else 11
        Logger.search(f"Marketplace taranıyor: {keyword} ({asset_name})")
        
        found_assets = []
        cursor = ""
        url = "https://catalog.roblox.com/v1/search/items/details"

        subcat_map = {
            # Roblox Catalog API v1 subcategory values
            8: 8,   # Hat (ClassicHat)
            41: 9,  # Hair (HairAccessories)
            42: 10, # Face (FaceAccessories)
            43: 11, # Neck (NeckAccessories)
            44: 12, # Shoulder (ShoulderAccessories)
            45: 13, # Front (FrontAccessories)
            46: 14, # Back (BackAccessories)
            47: 15, # Waist (WaistAccessories)
        }
        subcategory = subcat_map.get(asset_type) if category == 11 else None

        for page in range(4):
            params = {
                "keyword": keyword,
                "category": category,
                "limit": 30,
                "cursor": cursor,
                "sortType": self.sort_type,
                "sortAggregation": self.sort_agg,
            }
            if category == 11 and subcategory:
                params["subcategory"] = subcategory
            else:
                params["assetTypes"] = asset_type
                
            try:
                response = self._request_with_retry("GET", url, params=params, timeout=10)
                if response and response.status_code == 200:
                    data = response.json()
                    listings = data.get("data", [])
                    cursor = data.get("nextPageCursor")
                    
                    Logger.debug(f"Sayfa {page+1} tarandı. {len(listings)} ürün bulundu.")
                    
                    for item in listings:
                        if item.get("id"):
                            asset_id = str(item.get("id"))
                            # Avoid duplicates
                            if any(a[0] == asset_id for a in found_assets):
                                continue
                                
                            item_name = item.get("name", "Asset")
                            creator_name = item.get("creatorName", "Unknown")
                            item_url = f"https://www.roblox.com/catalog/{asset_id}/"
                            Logger.found(f"{item_name} (ID: {asset_id}) - Yapan: {creator_name}")
                            found_assets.append((asset_id, item_url, creator_name, item_name))
                            
                else:
                    Logger.debug(f"Arama başarısız (Status: {response.status_code})")
                    break
            except Exception as e:
                Logger.debug(f"Arama hatası: {e}")
                break
                            
        if found_assets:
            return found_assets
        
        Logger.warn(f"'{keyword}' için ürün bulunamadı.")
        return []

    async def search_and_yield_assets(self, keyword, asset_type=11):
        is_clothing = asset_type in (11, 12, 2)
        is_accessory = asset_type in (8, 41, 42, 43, 44, 45, 46, 47)
        
        asset_name_map = {
            11: "Shirt", 12: "Pants",
            8: "Hat", 41: "Hair", 42: "Face", 43: "Neck",
            44: "Shoulder", 45: "Front", 46: "Back", 47: "Waist"
        }
        asset_name = asset_name_map.get(asset_type, f"Accessory_{asset_type}")
        Logger.search(f"{keyword} için stream başlatıldı ({asset_name})")
        
        cursor = ""
        url = "https://catalog.roblox.com/v1/search/items/details"
        seen_ids = set()

        # All accessories: search entire catalog by keyword only (subcategory filter broken for Hat/Hair)
        for page in range(10):
            if is_clothing:
                params = {
                    "keyword": keyword,
                    "category": 3,
                    "assetTypes": asset_type,
                    "limit": 30,
                    "cursor": cursor,
                    "sortType": self.sort_type,
                    "sortAggregation": self.sort_agg,
                }
            else:
                # Accessories — no category/subcategory, search whole catalog by keyword
                params = {
                    "keyword": keyword,
                    "limit": 30,
                    "cursor": cursor,
                    "sortType": self.sort_type,
                    "sortAggregation": self.sort_agg,
                }
                
            try:
                response = self._request_with_retry("GET", url, params=params, timeout=10)
                if response and response.status_code == 200:
                    data = response.json()
                    listings = data.get("data", [])
                    cursor = data.get("nextPageCursor")
                    
                    Logger.debug(f"Stream Sayfa {page+1} tarandı. {len(listings)} ürün bulundu.")
                    
                    for item in listings:
                        if item.get("id"):
                            asset_id = str(item.get("id"))
                            if asset_id in seen_ids:
                                continue
                            seen_ids.add(asset_id)
                                
                            item_name = item.get("name", "Asset")
                            creator_name = item.get("creatorName", "Unknown")
                            item_url = f"https://www.roblox.com/catalog/{asset_id}/"
                            Logger.found(f"Sıradaki: {item_name} ({asset_id})")
                            yield (asset_id, item_url, creator_name, item_name)
                    
                    if not cursor:
                        break
                else:
                    Logger.debug(f"Stream arama başarısız (Status: {response.status_code})")
                    break
            except Exception as e:
                Logger.debug(f"Stream hatası: {e}")
                break

    async def get_paired_pants(self, shirt_asset_id: str, keyword: str) -> list[tuple[str, str]]:
        """
        Check a shirt's description for catalog links to Classic Pants.
        Returns a list of (asset_id, url) tuples for any paired pants found.
        AssetType 12 = Classic Pants.
        """
        # 0. Check cache
        if shirt_asset_id in self._desc_cache:
            return self._desc_cache[shirt_asset_id]

        # 1. Fetch asset details to get description
        try:
            # Add a small delay for every description fetch to be gentle
            import time
            time.sleep(0.3)
            
            r = self._request_with_retry(
                "GET",
                f"https://economy.roblox.com/v2/assets/{shirt_asset_id}/details",
                timeout=10,
            )
            if not r or r.status_code != 200:
                code = r.status_code if r else "Timeout"
                Logger.warn(f"Açıklama alınamadı ({shirt_asset_id}). Status: {code}")
                return []
            details = r.json()
            description = details.get("Description") or details.get("description") or ""
            # Cache positive but empty results to avoid retrying
            if not description:
                self._desc_cache[shirt_asset_id] = []
                return []
        except Exception as e:
            Logger.error(f"Açıklama hatası ({shirt_asset_id}): {e}")
            return []

        if not description:
            return []

        # 2. Extract all catalog IDs from description text
        found_ids = re.findall(r"roblox\.com/catalog/(\d+)", description)
        if not found_ids:
            return []

        # Eğer açıklamada birden fazla farklı katalog linki varsa,
        # yanlış/mix set riskini azaltmak için bu shirt'i tamamen atla.
        if len(set(found_ids)) != 1:
            Logger.warn(f"Açıklamada birden fazla ID bulundu ({shirt_asset_id}). Karışıklığı önlemek için atlanıyor.")
            return []
        
        
        Logger.debug(f"PairedPants: Açıklamada {len(found_ids)} link bulundu.")

        import time
        # 3. Verify each linked asset is Classic Pants (assetType=12)
        pants_assets = []
        for linked_id in found_ids:
            Logger.debug(f"Pants ID doğrulanıyor: {linked_id}")
            
            try:
                keyword_l = (keyword or "").lower()
                # Use catalog endpoint if auth available, otherwise fallback to economy v2 (with delay)
                if self.has_auth:
                    body = {"items": [{"itemType": "Asset", "id": linked_id}]}
                    r2 = self.session.post("https://catalog.roblox.com/v1/catalog/items/details", json=body, timeout=10)
                    if r2.status_code == 200:
                        data = r2.json().get("data", [])
                        if data:
                            item = data[0]
                            asset_type = item.get("assetType")
                            name = item.get("name", f"Pants_{linked_id}")
                            name_l = name.lower()
                            # Hem asset tipini kontrol et, hem de isim içinde keyword geçsin
                            if asset_type == 12 and (not keyword_l or keyword_l in name_l):
                                url = f"https://www.roblox.com/catalog/{linked_id}/"
                                Logger.success(f"Eşleşen Pants bulundu: {name}")
                                pants_assets.append((linked_id, url))
                            else:
                                print(f"  [PairedPants] Ignored. AssetType is {asset_type} (not 12).")
                    else:
                        print(f"  [PairedPants] Verification failed. Status {r2.status_code}")
                else:
                    # Fallback
                    time.sleep(1.5)
                    r2 = self.session.get(f"https://economy.roblox.com/v2/assets/{linked_id}/details", timeout=10)
                    if r2.status_code == 200:
                        item = r2.json()
                        asset_type = item.get("AssetTypeId")
                        name = item.get("Name", f"Pants_{linked_id}")
                        name_l = name.lower()
                        if asset_type == 12 and (not keyword_l or keyword_l in name_l):
                            url = f"https://www.roblox.com/catalog/{linked_id}/"
                            print(f"[PairedPants] SUCCESS: Matched Classic Pants: {name}")
                            pants_assets.append((linked_id, url))
            except Exception as e:
                print(f"[PairedPants] Error checking linked asset {linked_id}: {e}")

        self._desc_cache[shirt_asset_id] = pants_assets
        return pants_assets

    async def get_thumbnail(self, asset_id: str) -> str | None:
        """Katalog eşyası için thumbnail URL'si alır."""
        url = f"https://thumbnails.roblox.com/v1/assets?assetIds={asset_id}&size=420x420&format=Png&isCircular=false"
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    return data[0].get("imageUrl")
        except Exception as e:
            Logger.debug(f"Thumbnail hatası ({asset_id}): {e}")
        return None

