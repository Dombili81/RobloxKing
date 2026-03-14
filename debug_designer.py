import asyncio
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = "https://019c4346-c3f4-7341-be41-cea3066493e3.arena.site/"
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            await page.screenshot(path="debug_designer.png")
            
            with open("debug_designer.txt", "w", encoding="utf-8") as f:
                f.write(f"Page Title: {await page.title()}\n")
                
                # Check frames
                frames = page.frames
                f.write(f"Found {len(frames)} frames:\n")
                for i, frame in enumerate(frames):
                    f.write(f"Frame {i}: {frame.name} - {frame.url}\n")
                    try:
                        inputs = await frame.locator("input").all()
                        f.write(f"  Frame {i} has {len(inputs)} inputs.\n")
                        file_inputs = await frame.locator("input[type='file']").all()
                        f.write(f"  Frame {i} has {len(file_inputs)} file inputs.\n")
                    except Exception as e:
                        f.write(f"  Error checking frame {i}: {e}\n")

                # Get all inputs in main frame (already checked but good to keep)
                inputs = await page.locator("input").all()
                f.write(f"Main Frame Inputs: {len(inputs)}\n")

                # Get all buttons
                buttons = await page.locator("button").all()
                f.write(f"Found {len(buttons)} buttons:\n")
                for i, btn in enumerate(buttons):
                    text = await btn.text_content()
                    f.write(f"Button {i}: {text.strip()}\n")
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())
