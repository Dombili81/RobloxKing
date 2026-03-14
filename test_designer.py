import asyncio
from scrapers.designer import TemplateDesigner

async def test():
    designer = TemplateDesigner()
    # Using dummy path for asset, assuming it exists or creating it
    # We can use the one from downloader test
    asset_path = "downloads/15901064855.png" 
    template_path = "template.png"
    
    print(f"Testing Designer with Asset: {asset_path}, Template: {template_path}")
    path = await designer.process_image(asset_path, template_path)
    
    if path:
        print(f"Test Result -> Final Design: {path}")
    else:
        print("Test Failed: Processing failed.")

if __name__ == "__main__":
    asyncio.run(test())
