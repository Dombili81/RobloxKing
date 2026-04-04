"""
finance.py - Group economy and sales tracker
"""
import asyncio
import time
import requests

class GroupFinanceMonitor:
    def __init__(self, cookie: str, group_id: int):
        self.cookie = cookie
        self.group_id = group_id
        self.session = requests.Session()
        self.session.cookies[".ROBLOSECURITY"] = cookie
        
        # We track the last transaction ID we've seen so we don't spam old sales
        self.last_transaction_id = set()
        self._is_first_run = True

    def get_user_balance(self) -> dict:
        """Kullanıcının kendi bakiyesini (Robux) çeker."""
        try:
            # 1. Önce kimlik tespiti
            auth_url = "https://users.roblox.com/v1/users/authenticated"
            r_auth = self.session.get(auth_url, timeout=20)
            r_auth.raise_for_status()
            user_data = r_auth.json()
            user_id = user_data.get("id")
            user_name = user_data.get("name", "Bilinmeyen")
            
            if not user_id:
                return {"error": "Kullanıcı ID alınamadı."}
            
            # 2. Bakiye çekme
            bal_url = f"https://economy.roblox.com/v1/users/{user_id}/currency"
            r_bal = self.session.get(bal_url, timeout=20)
            r_bal.raise_for_status()
            return {
                "robux": r_bal.json().get("robux", 0),
                "user_name": user_name
            }
        except Exception as e:
            return {"error": f"Bakiye alınamadı: {e}"}

    def get_summary(self) -> dict:
        """
        Fetches pending robux, total sales for the day/month, and user balance.
        """
        results = {
            "pending": 0,
            "item_sales_robux": 0,
            "user_balance": 0,
            "user_name": "Bilinmeyen",
            "group_error": None
        }

        # 1. Kullanıcı bakiyesi her zaman alınmalı
        bal_data = self.get_user_balance()
        if "error" not in bal_data:
            results["user_balance"] = bal_data["robux"]
            results["user_name"] = bal_data["user_name"]

        # 2. Grup satış özeti
        url = f"https://economy.roblox.com/v1/groups/{self.group_id}/revenue/summary/day"
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code == 403:
                results["group_error"] = "Grup finanslarını görme yetkiniz yok (403)."
            else:
                r.raise_for_status()
                data = r.json()
                results["pending"] = data.get("pendingRobux", 0)
                
                # Roblox 'itemSaleRobux' sadece o gün HESABA GEÇEN bakiyeyi gösterdiğinden
                # gerçeği yansıtmaz. (Satışlar 3-7 gün pending'de bekler).
                # Bu yüzden gerçek satışı transactions üzerinden hesaplayalım:
                try:
                    real_sales = self._calc_today_sales_from_tx()
                    results["item_sales_robux"] = real_sales
                except Exception:
                    # Hata alırsa standart API değerine dön (fallback)
                    results["item_sales_robux"] = data.get("itemSaleRobux", 0)
        except Exception as e:
            results["group_error"] = str(e)

        return results

    def _calc_today_sales_from_tx(self) -> int:
        """Son işlemleri çekip bugünün gerçek ciro toplamını bulur."""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            url = f"https://economy.roblox.com/v2/groups/{self.group_id}/transactions?transactionType=Sale&limit=100"
            r = self.session.get(url, timeout=20)
            if r.status_code != 200:
                return 0
            
            total_today = 0
            for tx in r.json().get("data", []):
                created_str = tx.get("created", "")
                if not created_str: continue
                # Örn: 2026-04-03T18:30:00Z
                try:
                    tx_date = datetime.strptime(created_str.split(".")[0].replace("Z",""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    if tx_date.date() == now.date():
                        total_today += tx.get("currency", {}).get("amount", 0)
                except Exception:
                    pass
            return total_today
        except Exception:
            return 0

    def get_detailed_analysis(self) -> dict:
        """
        Son 100 satışı detaylı olarak analiz edip, en çok satanları
        ve kullanıcıya Akıllı Trend Tavsiyesini döner.
        """
        try:
            url = f"https://economy.roblox.com/v2/groups/{self.group_id}/transactions?transactionType=Sale&limit=100"
            r = self.session.get(url, timeout=20)
            if r.status_code == 403:
                return {"error": "Yetki Hatası (403). Cookie yazar kasa iznine sahip değil."}
            r.raise_for_status()
            transactions = r.json().get("data", [])
            
            if not transactions:
                return {"error": "Grupta hiç satış işlemi bulunamadı."}
            
            from collections import defaultdict
            import re
            
            # Gruplama
            item_stats = defaultdict(lambda: {"count": 0, "robux": 0})
            word_freq = defaultdict(int)
            total_robux = 0
            
            for tx in transactions:
                details = tx.get("details", {})
                name = details.get("name", "Bilinmeyen Ürün")
                amount = tx.get("currency", {}).get("amount", 0)
                
                item_stats[name]["count"] += 1
                item_stats[name]["robux"] += amount
                total_robux += amount
                
                # Kelime analizi için (Kıyafet tipi hariç)
                clean_name = re.sub(r'[^A-Za-z0-9 ]+', '', name.lower())
                ignore = {"shirt", "pants", "tshirt", "t-shirt", "black", "white", "red", "blue"}
                for word in clean_name.split():
                    if len(word) > 3 and word not in ignore:
                        word_freq[word] += 1
            
            # Sıralama
            top_items = sorted(item_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
            
            # AI Insight (Trend Tavsiyesi)
            insight_msg = "Henüz net bir satış trendi oluşmamış. Yeni tarzdaki kıyafetleri deneyebilirsin."
            if word_freq:
                top_word = max(word_freq.items(), key=lambda x: x[1])
                if top_word[1] >= 2:
                    insight_msg = (
                        f"🤖 **Bot AI Analizi:** Son günlerde **'{top_word[0].title()}'** tarzı veya "
                        f"iletişimli kıyafetler harika satıyor! Trend Motorunu kullanırken bu seriyi devam ettirmeyi düşünmelisin."
                    )
            
            return {
                "top_items": top_items,
                "total_robux_100": total_robux,
                "insight": insight_msg,
                "tx_count": len(transactions)
            }
            
        except Exception as e:
            return {"error": f"Analiz başarısız: {e}"}

    def check_new_sales(self) -> list[dict]:
        """
        Polls the transactions API to find any NEW sales since the last check.
        Returns a list of sale dictionaries.
        """
        # transactionType=Sale
        url = f"https://economy.roblox.com/v2/groups/{self.group_id}/transactions?transactionType=Sale&limit=10"
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
            transactions = data.get("data", [])
            
            new_sales = []
            
            for tx in transactions:
                tx_id = tx.get("id")
                if not tx_id:
                    continue
                    
                if self._is_first_run:
                    # On first run, we just populate the cache so we don't spam 10 old sales at boot
                    self.last_transaction_id.add(tx_id)
                elif tx_id not in self.last_transaction_id:
                    # IT'S A NEW SALE!
                    self.last_transaction_id.add(tx_id)
                    new_sales.append(tx)
                    
            self._is_first_run = False
            return new_sales
            
        except Exception:
            return []
