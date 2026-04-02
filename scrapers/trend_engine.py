"""
trend_engine.py - Pop Kültür Radar + Roblox Talep Doğrulama

Akış:
  1. 8 Dış Kaynaktan "şu an ne gündemde?" entity'leri topla
     (Anime/Manga, Film/Dizi, Spor, Müzik, Oyun)
  2. Her entity için Roblox Catalog'da keyword araması yap
     → Kaç ürün var? Talep ispatlanıyor mu?
  3. Skor = Kaynak Ağırlığı × log(Roblox Sonuç Sayısı + 1) + Firebase Bonus
  4. Top 15 öneri sun
"""
import asyncio
import re
import math
import random
import time
import requests
import xml.etree.ElementTree as ET
from scrapers.firebase_db import FirebaseManager

# ─── Template Varyantları ──────────────────────────────────────────────────
TEMPLATES = [
    "{name} Aesthetic",
    "{name} Outfit",
    "{name} Drip",
    "Dark {name}",
    "Soft {name}",
    "{name} Core",
    "{name} Grunge",
    "{name} Alt",
    "Vintage {name}",
    "{name} Era",
    "{name} Warrior",
    "{name} Y2K",
]

# Haber jargonu — entity çıkarmada kullanılacak filtre
HEADLINE_NOISE = {
    "Season", "Episode", "Part", "Vol", "Arc", "Chapter", "Gets", "New",
    "Anime", "Series", "Film", "Movie", "Show", "Teaser", "Trailer",
    "First", "Second", "Third", "Official", "The", "A", "Of", "In",
    "For", "And", "Or", "Is", "Are", "Has", "With", "To", "At", "By",
    "Preview", "Debut", "Release", "Announce", "Reveal", "Stream",
    "Watch", "Review", "Week", "Year", "Day", "Live", "Latest",
    "Breaking", "Update", "Report", "Confirms", "Reveals", "Says",
    "Will", "Set", "How", "Why", "What", "When", "Who", "Win",
    "Wins", "Won", "Dead", "Star", "Cast", "Drops", "Launches",
    "Returns", "Coming", "Exclusive", "Source", "Exclusive", "Awards",
    "Top", "Best", "Big", "Super", "Final", "Last", "Next",
}


class TrendEngine:
    def __init__(self, db_manager: FirebaseManager):
        self.db = db_manager
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.cache = {"time": 0, "data": []}

    # ══════════════════════════════════════════════════════════════════════
    # ADIM 1: Dış Kaynaklardan Trending Entity'leri Topla
    # ══════════════════════════════════════════════════════════════════════

    def _get_jikan_entities(self) -> list[dict]:
        """
        Jikan (MyAnimeList) API'den bu sezon yayındaki animeleri çeker.
        → Garantili doğru veri, API rate limiti yok.
        """
        try:
            resp = self.session.get(
                "https://api.jikan.moe/v4/seasons/now",
                params={"limit": 25},
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            result = []
            for anime in resp.json().get("data", []):
                members = anime.get("members", 0) or 0
                if members < 10_000:
                    continue
                synonyms = anime.get("title_synonyms") or []
                name = (
                    anime.get("title_english")
                    or (synonyms[0] if synonyms else None)
                    or anime.get("title", "")
                )
                if not name or len(name) < 2:
                    continue
                score = anime.get("score") or 0
                # Ağırlık: popülerlik + IMDB skoru
                weight = 2.5 + (score / 10) + math.log(max(members, 1)) / 10
                result.append({
                    "name": name,
                    "source": "🎌 Yeni Anime Sezonu",
                    "weight": weight,
                    "extra": f"⭐{score} | {members//1000}K üye",
                })
            return result
        except Exception as e:
            print(f"Jikan err: {e}")
            return []

    def _get_rss_entities(self) -> list[dict]:
        """
        8 RSS kaynağından haber başlıklarını çeker ve içlerinden
        proper noun entity'leri çıkarır.
        """
        rss_sources = [
            # Anime
            ("https://www.animenewsnetwork.com/all/rss.xml",  "🎌 Anime Haber",  2.0),
            ("https://anitrendz.net/news/feed",               "📊 Anitrendz",    2.2),
            # Film & Dizi
            ("https://variety.com/feed/",                     "🎥 Film/Dizi",    2.1),
            ("https://tvline.com/feed/",                      "📺 Dizi Haber",   1.9),
            # Spor
            ("https://www.espn.com/espn/rss/news",            "⚽ Spor",         2.0),
            # Müzik
            ("https://www.billboard.com/feed/",               "🎵 Müzik",        1.9),
            # Oyun
            ("https://feeds.ign.com/ign/all",                 "🎮 Oyun",         1.8),
            # Genel Pop Kültür
            ("https://ew.com/feed/",                          "🌟 Pop Kültür",   2.0),
        ]

        raw: list[tuple[str, str, float]] = []

        for url, label, weight in rss_sources:
            try:
                resp = self.session.get(url, timeout=7)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                count = 0
                for item in root.iter("item"):
                    title_el = item.find("title")
                    if title_el is None or not title_el.text:
                        continue
                    raw.append((title_el.text.strip(), label, weight))
                    count += 1
                    if count >= 20:  # Kaynak başına max 20 başlık
                        break
            except Exception as e:
                print(f"RSS err ({url}): {e}")

        # Başlıklardan entity çıkar
        entities: list[dict] = []
        seen: set[str] = set()

        for title, label, weight in raw:
            # Proper noun grupları bul: büyük harfle başlayan ardışık kelimeler
            words = title.split()
            entity_parts: list[str] = []

            for j, word in enumerate(words):
                clean = re.sub(r"[^A-Za-z0-9']", "", word)
                if clean and clean[0].isupper() and len(clean) >= 2:
                    entity_parts.append(clean)
                else:
                    self._flush_entity(entity_parts, label, weight, seen, entities)
                    entity_parts = []
            self._flush_entity(entity_parts, label, weight, seen, entities)

        return entities

    def _flush_entity(self, parts: list, label: str, weight: float,
                      seen: set, out: list):
        """Entity parçalarını temizleyip listeye ekler."""
        if not parts:
            return
        # Sadece noise olan parçaları at
        filtered = [p for p in parts if p not in HEADLINE_NOISE]
        if not filtered:
            return
        entity = " ".join(filtered[:3])
        # Çok kısa veya zaten görülmüş ise atla
        if len(entity) < 4 or entity.lower() in seen:
            return
        seen.add(entity.lower())
        out.append({
            "name": entity,
            "source": label,
            "weight": weight,
            "extra": "",
        })

    # ══════════════════════════════════════════════════════════════════════
    # ADIM 2: Roblox Catalog'da Talep Doğrulama
    # ══════════════════════════════════════════════════════════════════════

    def _check_roblox_demand(self, keyword: str) -> int:
        """
        Roblox Catalog'da keyword araması yapar ve kaç ürün döndüğünü verir.
        Bu sayı = kullanıcı talebinin Roblox'taki kanıtı.
        """
        try:
            resp = self.session.get(
                "https://catalog.roblox.com/v1/search/items",
                params={
                    "keyword": keyword,
                    "category": 3,   # Clothing
                    "limit": 10,
                },
                timeout=5,
            )
            if resp.status_code != 200:
                return 0
            data = resp.json()
            # totalResults varsa kullan, yoksa data listesinin uzunluğuna bak
            return data.get("totalResults", len(data.get("data", [])))
        except Exception:
            return 0

    # ══════════════════════════════════════════════════════════════════════
    # ADIM 3: Ana Algoritma
    # ══════════════════════════════════════════════════════════════════════

    def get_suggestions_sync(self, force_refresh: bool = False) -> list:
        if not force_refresh and time.time() - self.cache["time"] < 1800 and self.cache["data"]:
            return self.cache["data"]

        # 1) Tüm dış kaynaklardan entity topla
        all_entities: list[dict] = []
        all_entities += self._get_jikan_entities()
        all_entities += self._get_rss_entities()

        # 2) Entity deduplikasyonu (aynı isim farklı kaynaklardan gelebilir)
        #    Aynı isim varsa en yüksek ağırlıklı kaynağı tut
        dedup: dict[str, dict] = {}
        for e in all_entities:
            key = e["name"].lower()
            if key not in dedup or dedup[key]["weight"] < e["weight"]:
                dedup[key] = e

        unique_entities = list(dedup.values())

        # Ağırlığa göre sırala, en umut verici 40'ı kontrol et
        unique_entities.sort(key=lambda x: x["weight"], reverse=True)
        candidates = unique_entities[:40]

        # 3) Her entity için Roblox talebi kontrol et
        scored: list[dict] = []
        for entity in candidates:
            roblox_count = self._check_roblox_demand(entity["name"])
            if roblox_count == 0:
                # Roblox'ta hiç yoksa düşük puanla yine de ekle (potansiyel fırsat)
                roblox_factor = 0.5
            else:
                # log scale: 1 ürün=0, 10 ürün=2.3, 100 ürün=4.6, 1000 ürün=6.9
                roblox_factor = math.log(roblox_count + 1)

            score = entity["weight"] * roblox_factor

            # Roblox'ta çok az ürün varsa = rakipsiz fırsat bonosu
            opportunity_bonus = 1.3 if 0 < roblox_count < 50 else 1.0

            scored.append({
                "name": entity["name"],
                "source": entity["source"],
                "weight": entity["weight"],
                "extra": entity.get("extra", ""),
                "roblox_count": roblox_count,
                "score": score * opportunity_bonus,
            })

        # 4) Sırala: en yüksek skor önce
        scored.sort(key=lambda x: x["score"], reverse=True)

        # 5) Çeşitlilik: aynı ilk kelimeden sadece 1 entity tutulur
        diverse: dict[str, dict] = {}
        for s in scored:
            first_word = s["name"].split()[0].lower()
            if first_word not in diverse:
                diverse[first_word] = s

        top_candidates = list(diverse.values())[:15]

        # 6) Template uygula + Firebase click bonus
        used_templates: set = set()
        final_list: list[dict] = []

        for item in top_candidates:
            available = [t for t in TEMPLATES if t not in used_templates]
            if not available:
                available = TEMPLATES
            tmpl = random.choice(available)
            used_templates.add(tmpl)
            kw = tmpl.replace("{name}", item["name"])

            clicks = 0
            if self.db and self.db.is_active:
                try:
                    doc = self.db.db.collection("trend_analytics").document(kw).get()
                    if doc.exists:
                        clicks = doc.to_dict().get("click_count", 0)
                except Exception:
                    pass

            # Extra bilgiye Roblox sayısı da ekle
            roblox_count = item["roblox_count"]
            extra_parts = []
            if item.get("extra"):
                extra_parts.append(item["extra"])
            if roblox_count < 50:
                extra_parts.append(f"🆕 Az Rakip ({roblox_count} ürün)")
            elif roblox_count < 300:
                extra_parts.append(f"📦 {roblox_count} ürün")

            final_list.append({
                "kw": kw,
                "favorites": roblox_count,
                "score": item["score"] + clicks * 50000,
                "sample_item": item["name"],
                "label": item["source"],
                "extra": " | ".join(extra_parts),
                "clicks": clicks,
                "base": item["name"],
            })

        final_list.sort(key=lambda x: x["score"], reverse=True)
        top15 = final_list[:15]

        self.cache["data"] = top15
        self.cache["time"] = time.time()
        return top15

    async def get_suggestions(self, force_refresh: bool = False) -> list:
        return await asyncio.to_thread(self.get_suggestions_sync, force_refresh)
