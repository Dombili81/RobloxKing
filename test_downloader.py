import asyncio
from scrapers.downloader import AssetDownloader

async def test():
    # Read asset ID from file
    try:
        with open("last_asset.txt", "r") as f:
            content = f.read().strip()
            asset_id = content.split(",")[0]
            print(f"Testing Downloader with Asset ID: {asset_id}")
    except FileNotFoundError:
        print("No asset ID file found. Using dummy ID.")
        asset_id = "123456789" # Dummy

    downloader = AssetDownloader()
    path = await downloader.download_template(asset_id)
    
    if path:
        print(f"Test Result -> Downloaded to: {path}")
    else:
        print("Test Failed: Download failed.")

if __name__ == "__main__":
    asyncio.run(test())
