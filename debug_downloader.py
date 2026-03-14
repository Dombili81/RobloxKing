import asyncio
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to rbxdex.com...")
        await page.goto("https://rbxdex.com/template-downloader/")
        await page.wait_for_load_state("networkidle")
        
        with open("debug_html.txt", "w", encoding="utf-8") as f:
            # Get all inputs
            inputs = await page.locator("input").all()
            f.write(f"Found {len(inputs)} inputs:\n")
            for i, inp in enumerate(inputs):
                html = await inp.evaluate("el => el.outerHTML")
                f.write(f"Input {i}: {html}\n")
                
            # Get all buttons
            buttons = await page.locator("button").all()
            f.write(f"Found {len(buttons)} buttons:\n")
            for i, btn in enumerate(buttons):
                text = await btn.text_content()
                f.write(f"Button {i}: {text.strip()}\n")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())
