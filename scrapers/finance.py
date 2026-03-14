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

    def get_summary(self) -> dict:
        """
        Fetches pending robux, total sales for the day/month.
        """
        url = f"https://economy.roblox.com/v1/groups/{self.group_id}/revenue/summary/day"
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            return {
                "pending": data.get("pendingRobux", 0),
                "item_sales_robux": data.get("itemSaleRobux", 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def check_new_sales(self) -> list[dict]:
        """
        Polls the transactions API to find any NEW sales since the last check.
        Returns a list of sale dictionaries.
        """
        # transactionType=Sale (9)
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
