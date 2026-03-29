import asyncio
import re
import random
import time
from collections import defaultdict
import requests
from scrapers.firebase_db import FirebaseManager

try:
    from pytrends.request import TrendReq
except ImportError:
    TrendReq = None

TEMPLATES = {
    "general": ["{name} Aesthetic", "{name} Outfit", "{name} Drip", "Dark {name}", "Soft {name}", "{name} Core"],
}

class TrendEngine:
    def __init__(self, db_manager: FirebaseManager):
        self.db = db_manager
        self.session = requests.Session()
        self.cache = {"time": 0, "data": []}

    def _clean_item_name(self, name: str) -> str:
        spam = ["y2k", "emo", "goth", "preppy", "grunge", "cheap", "cute", "aesthetic", "outfit", "drip", "core", "shirt", "pants", "boy", "girl", "hair", "face", "top", "bottom"]
        words = re.findall(r'\b[A-Za-z0-9]+\b', name)
        cleaned = [w for w in words if w.lower() not in spam]
        if not cleaned: return ""
        return " ".join(cleaned[:3]).title()

    def _fetch_roblox_hot(self):
        try:
            # SortType 2 = MostFavorited, SortAggregation 3 = PastWeek
            params = {"Category": 3, "SortType": 2, "SortAggregation": 3, "Limit": 30}
            search_resp = self.session.get("https://catalog.roblox.com/v1/search/items", params=params, timeout=5)
            if search_resp.status_code != 200: return []
                
            items = search_resp.json().get("data", [])
            ids = [it["id"] for it in items if "id" in it]
            if not ids: return []
                
            token_resp = self.session.post("https://catalog.roblox.com/v1/catalog/items/details")
            csrf = token_resp.headers.get("x-csrf-token", "")
            
            det_resp = self.session.post(
                "https://catalog.roblox.com/v1/catalog/items/details",
                json={"items": [{"itemType": "Asset", "id": i} for i in ids]},
                headers={"x-csrf-token": csrf},
                timeout=5
            )
            return det_resp.json().get("data", []) if det_resp.status_code == 200 else []
        except Exception as e:
            print(f"Roblox fetch err: {e}")
            return []

    def _fetch_google_trends(self):
        if not TrendReq: return []
        try:
            pt = TrendReq(hl='en-US', tz=360, retries=2, backoff_factor=0.5)
            pt.build_payload(["anime outfit", "gaming aesthetic", "kpop fashion"], timeframe='now 7-d')
            related = pt.related_queries()
            trends = []
            for kw in ["anime outfit", "gaming aesthetic", "kpop fashion"]:
                if related.get(kw) and related[kw].get("rising") is not None:
                    rising = related[kw]["rising"]
                    trends.extend(rising['query'].head(5).tolist())
            return trends
        except Exception:
            return []

    def get_suggestions_sync(self):
        if time.time() - self.cache["time"] < 1800 and self.cache["data"]:
            return self.cache["data"]

        # 1. Fetch Roblox
        roblox_items = self._fetch_roblox_hot()
        candidates = {} 
        for item in roblox_items:
            favs = item.get("favoriteCount", 0)
            name = item.get("name", "")
            cleaned = self._clean_item_name(name)
            if len(cleaned) > 2:
                if cleaned not in candidates or candidates[cleaned]["favs"] < favs:
                    candidates[cleaned] = {"favs": favs, "sample": name}
                
        # 2. Add Google Trends
        g_trends = self._fetch_google_trends()
        for t in g_trends:
            cleaned = t.title()
            if len(cleaned) > 2 and cleaned not in candidates:
                 candidates[cleaned] = {"favs": 50000, "sample": f"Google Trend: {t}"}

        # 3. Transform and finalize without hitting Roblox Catalog API in a loop!
        # Sort candidates by top favorites
        top_bases = sorted(candidates.items(), key=lambda x: x[1]["favs"], reverse=True)[:15]
        
        final_list = []
        for base, data in top_bases:
            # Pick one variant
            test_kw = random.choice([tmpl.replace("{name}", base) for tmpl in TEMPLATES["general"]])
            
            # Fetch Firebase click history bonus
            clicks = 0
            if self.db and self.db.is_active:
                try:
                    doc = self.db.db.collection("trend_analytics").document(test_kw).get()
                    if doc.exists:
                        clicks = doc.to_dict().get("click_count", 0)
                except: pass
                
            final_score = data["favs"] + (clicks * 50000)
            
            final_list.append({
                "kw": test_kw,
                "favorites": data["favs"],
                "score": final_score,
                "sample_item": data["sample"],
                "clicks": clicks,
                "base": base
            })

        # Sort by final score
        final_list.sort(key=lambda x: x["score"], reverse=True)
        top5 = final_list[:5]
        
        self.cache["data"] = top5
        self.cache["time"] = time.time()
        
        return top5

    async def get_suggestions(self):
        return await asyncio.to_thread(self.get_suggestions_sync)
