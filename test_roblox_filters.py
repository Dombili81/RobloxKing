from playwright.async_api import async_playwright
import asyncio

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        try:
            # Construct the URL with the user-provided taxonomy ID
            # User provided: https://www.roblox.com/catalog?Keyword=homelander&taxonomy=2a2rf9qyeTd8W5iegK2Prc&salesTypeFilter=1&SortType=2&SortAggregation=3
            target_url = "https://www.roblox.com/catalog?Keyword=homelander&taxonomy=2a2rf9qyeTd8W5iegK2Prc&salesTypeFilter=1&SortType=2&SortAggregation=3"
            
            print(f"Navigating directly to filtered URL: {target_url}")
            await page.goto(target_url)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5) # Allow dynamic content to load

            print("Page Title:", await page.title())
            
            # Verify if we are seeing Classic Shirts
            print("Checking for indicators of successful filtering...")
            
            # Take a screenshot for visual verification
            await page.screenshot(path="debug_filters_direct_url.png")
            print("Screenshot saved to debug_filters_direct_url.png")
            
            # Dump HTML to verify content type
            html = await page.content()
            with open("debug_filters_direct_url.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("HTML dumped to debug_filters_direct_url.html")

        except Exception as e:
            print(f"Error during execution: {e}")
            import traceback
            traceback.print_exc()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
