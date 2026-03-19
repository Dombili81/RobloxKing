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
            r_auth = self.session.get(auth_url, timeout=10)
            r_auth.raise_for_status()
            user_data = r_auth.json()
            user_id = user_data.get("id")
            user_name = user_data.get("name", "Bilinmeyen")
            
            if not user_id:
                return {"error": "Kullanıcı ID alınamadı."}
            
            # 2. Bakiye çekme
            bal_url = f"https://economy.roblox.com/v1/users/{user_id}/currency"
            r_bal = self.session.get(bal_url, timeout=10)
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
            r = self.session.get(url, timeout=10)
            if r.status_code == 403:
                results["group_error"] = "Grup finanslarını görme yetkiniz yok (403)."
            else:
                r.raise_for_status()
                data = r.json()
                results["pending"] = data.get("pendingRobux", 0)
                results["item_sales_robux"] = data.get("itemSaleRobux", 0)
        except Exception as e:
            results["group_error"] = str(e)

        return results

    def check_new_sales(self) -> list[dict]:
        """
        Polls the transactions API to find any NEW sales since the last check.
        Returns a list of sale dictionaries.
        """
        # transactionType=Sale
        url = f"https://economy.roblox.com/v2/groups/{self.group_id}/transactions?transactionType=Sale&limit=10"
        try:
            r = self.session.get(url, timeout=10)
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
