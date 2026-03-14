import asyncio
from scrapers.roblox import RobloxScraper

async def test():
    roblox = RobloxScraper()
    async with await roblox.start() as page:
        asset_id, url = await roblox.search_and_get_asset("The Boys")
        if asset_id:
            with open("last_asset.txt", "w") as f:
                f.write(f"{asset_id},{url}")
            print(f"Test Result -> Asset ID: {asset_id}, URL: {url}")
        else:
            print("Test Failed: No Asset ID found.")
        
if __name__ == "__main__":
    asyncio.run(test())
