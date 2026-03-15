import asyncio
import sys
import os
import random
import time
from scrapers.roblox import RobloxScraper
from scrapers.downloader import AssetDownloader
from scrapers.designer import TemplateDesigner
from scrapers.uploader import AssetUploader
from scrapers.tags import get_tags, BASE_TAGS
from scrapers.firebase_db import FirebaseManager

# --- Firebase Init ---
db_manager = FirebaseManager()

# --- Load Config ---
def load_config(path="config.txt"):
    config = {
        "GROUP_ID": int(os.environ.get("GROUP_ID", 0)),
        "PRICE": int(os.environ.get("PRICE", 5)),
        "DELAY_MIN": int(os.environ.get("DELAY_MIN", 45)),
        "DELAY_MAX": int(os.environ.get("DELAY_MAX", 90)),
        "MAX_UPLOADS_PER_SESSION": int(os.environ.get("MAX_UPLOADS_PER_SESSION", 10)),
    }
    
    # 1. First, check Firebase for persistent settings
    cloud_settings = db_manager.load_settings()
    for k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "MAX_UPLOADS_PER_SESSION"]:
        if k in cloud_settings:
            try:
                config[k] = int(cloud_settings[k])
            except ValueError:
                pass

    # 2. Then check local file
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in config: # File values overwrite Env Vars
                    try:
                        v = int(val.strip())
                        if v != 0 and v != 5 and v != 45 and v != 90 and v != 10:
                            config[key] = v
                        elif not os.environ.get(key):
                            config[key] = v
                    except ValueError:
                        pass
    return config

# --- Load Cookie ---
def load_cookie(path="cookie.txt"):
    # 1. First, check Firebase
    cloud_settings = db_manager.load_settings()
    if cloud_settings.get("ROBLOX_COOKIE"):
        env_cookie = cloud_settings["ROBLOX_COOKIE"]
        if env_cookie.startswith(".ROBLOSECURITY="):
            return env_cookie[len(".ROBLOSECURITY="):]
        return env_cookie

    # 2. Local file
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip().strip('"').strip("'")
            if raw:
                if raw.startswith(".ROBLOSECURITY="):
                    return raw[len(".ROBLOSECURITY="):]
                return raw

    env_cookie = os.environ.get("ROBLOX_COOKIE")
    if env_cookie:
        if env_cookie.startswith(".ROBLOSECURITY="):
            return env_cookie[len(".ROBLOSECURITY="):]
        return env_cookie
    return None

# ---------------------------------------------------------------------------
# Metadata generator  (tags come from scrapers/tags.py)
# ---------------------------------------------------------------------------
def generate_metadata(keyword: str, item_type: str, pair_url: str = "") -> tuple[str, str]:
    """
    Returns (name, description) for a shirt or pants upload.
    item_type : 'shirt' or 'pants'
    pair_url  : catalog URL of the matching piece (optional)
    """
    kw_title = keyword.title()
    name = f"{kw_title} [+]"

    pair_line = f"\nMatching Pants/Shirts: \n{pair_url}\n" if pair_url else ""

    char_tags = get_tags(keyword)
    tags_line = f"{keyword} {BASE_TAGS} {char_tags}"

    description = (
        "⭐️Don't forget to favorite our shirt for more cool clothes! "
        f"{pair_line}\n"
        "🔥𝐎𝐑𝐈𝐆𝐈𝐍𝐀𝐋🔥 \n"
        "~~~\n"
        f"Tags: {tags_line}"
    )

    return name, description


# ---------------------------------------------------------------------------
# Download + design only (no upload)
# ---------------------------------------------------------------------------
async def download_and_design(asset_id: str, search_tag: str, item_type: str,
                               downloader, designer, custom_label: str | None = None) -> str | None:
    """Download template and run design overlay. Returns output path or None."""
    print(f"Downloading {item_type} template for ID: {asset_id} ...")
    download_path = await downloader.download_template(asset_id)
    if not download_path:
        print(f"  Failed to download {item_type} {asset_id}. Skipping.")
        return None

    if custom_label:
        label = f"{custom_label}_{asset_id}.png"
    else:
        label = f"{search_tag.replace(' ', '_')}_{item_type}_{asset_id}.png"
    final_output = await designer.process_image(
        download_path, "template.png",
        output_dir="output", custom_filename=label
    )
    if not final_output:
        print(f"  Design failed for {item_type} {asset_id}.")
        return None

    print(f"  Saved: {final_output}")
    return final_output


# ---------------------------------------------------------------------------
# Upload a matched shirt+pants pair with cross-linked descriptions
# ---------------------------------------------------------------------------
async def upload_pair_with_crosslink(
        shirt_id: str, shirt_path: str,
        pants_id: str, pants_path: str,
        keyword: str, uploader, upload_count: int, cfg: dict
) -> int:
    """
    Upload shirt and pants, then update both descriptions to cross-link each other.
    Returns updated upload_count.
    """
    max_uploads = cfg["MAX_UPLOADS_PER_SESSION"]
    delay_min   = cfg["DELAY_MIN"]
    delay_max   = cfg["DELAY_MAX"]
    price       = cfg["PRICE"]

    def _can_upload():
        return max_uploads == 0 or upload_count < max_uploads

    def _anti_ban():
        wait = random.uniform(delay_min, delay_max)
        print(f"[Anti-ban] Waiting {wait:.1f}s ...")
        time.sleep(wait)

    # --- Upload Shirt (no pair_url yet) ---
    if not _can_upload():
        print(f"[Anti-ban] Session cap reached. Skipping uploads.")
        return upload_count

    shirt_name, shirt_desc_temp = generate_metadata(keyword, "shirt")
    if upload_count > 0:
        _anti_ban()

    shirt_asset_id = uploader.upload_and_sell(shirt_path, shirt_name, shirt_desc_temp, item_type=11)
    if shirt_asset_id:
        upload_count += 1
        print(f"[Upload] '{shirt_name}' listed for {price} Robux! ({upload_count} total)")
    else:
        print(f"[Upload] Failed to upload shirt {shirt_id}.")
        return upload_count

    # --- Upload Pants (no pair_url yet) ---
    if not _can_upload():
        return upload_count

    pants_name, pants_desc_temp = generate_metadata(keyword, "pants")
    _anti_ban()

    pants_asset_id = uploader.upload_and_sell(pants_path, pants_name, pants_desc_temp, item_type=12)
    if pants_asset_id:
        upload_count += 1
        print(f"[Upload] '{pants_name}' listed for {price} Robux! ({upload_count} total)")
    else:
        print(f"[Upload] Failed to upload pants {pants_id}.")
        return upload_count

    # --- Cross-link: update descriptions with each other's catalog URL ---
    shirt_url = f"https://www.roblox.com/catalog/{shirt_asset_id}/"
    pants_url = f"https://www.roblox.com/catalog/{pants_asset_id}/"

    _, shirt_desc_linked = generate_metadata(keyword, "shirt",  pair_url=pants_url)
    _, pants_desc_linked = generate_metadata(keyword, "pants", pair_url=shirt_url)

    print(f"[CrossLink] Updating shirt {shirt_asset_id} with pants URL ...")
    uploader.update_description(shirt_asset_id, shirt_name, shirt_desc_linked)

    print(f"[CrossLink] Updating pants {pants_asset_id} with shirt URL ...")
    uploader.update_description(pants_asset_id, pants_name, pants_desc_linked)

    return upload_count


# ---------------------------------------------------------------------------
# Legacy single-asset helper (non-paired; no crosslink)
# ---------------------------------------------------------------------------
async def process_asset(asset_id, search_tag, item_type,
                         downloader, designer, uploader,
                         upload_count, cfg):
    """Download → design → upload + sell a single unpaired asset."""
    price       = cfg["PRICE"]
    delay_min   = cfg["DELAY_MIN"]
    delay_max   = cfg["DELAY_MAX"]
    max_uploads = cfg["MAX_UPLOADS_PER_SESSION"]

    final_output = await download_and_design(asset_id, search_tag, item_type, downloader, designer)
    if not final_output:
        return upload_count

    if uploader:
        if max_uploads > 0 and upload_count >= max_uploads:
            print(f"[Anti-ban] Session cap ({max_uploads}) reached. Skipping upload.")
            return upload_count

        if upload_count > 0:
            wait = random.uniform(delay_min, delay_max)
            print(f"[Anti-ban] Waiting {wait:.1f}s before next upload ...")
            time.sleep(wait)

        itype_int  = 11 if item_type == "shirt" else 12
        name, desc = generate_metadata(search_tag, item_type)
        asset_new  = uploader.upload_and_sell(final_output, name, desc, item_type=itype_int)
        if asset_new:
            upload_count += 1
            print(f"[Upload] '{name}' listed for {price} Robux! ({upload_count} total)")
        else:
            print(f"[Upload] Failed for {item_type} {asset_id}.")

    return upload_count


async def main():
    print("--- Roblox Automation Tool (Server Ready) ---")

    cfg         = load_config()
    group_id    = cfg["GROUP_ID"]
    price       = cfg["PRICE"]
    delay_min   = cfg["DELAY_MIN"]
    delay_max   = cfg["DELAY_MAX"]
    max_uploads = cfg["MAX_UPLOADS_PER_SESSION"]
    cookie      = load_cookie()

    if group_id == 0:
        print("WARNING: GROUP_ID not set in config.txt. Upload step skipped.")
        upload_enabled = False
    elif not cookie:
        print("WARNING: cookie.txt not found. Upload step skipped.")
        upload_enabled = False
    else:
        upload_enabled = True
        print(f"[Config] Group: {group_id} | Price: {price} Robux | "
              f"Delay: {delay_min}-{delay_max}s | Max uploads: {max_uploads}")

    uploader = (
        AssetUploader(cookie, group_id, price,
                      delay_min=delay_min, delay_max=delay_max,
                      max_uploads=max_uploads)
        if upload_enabled else None
    )

    # User Input
    if len(sys.argv) > 1:
        keyword_list = [k.strip() for k in sys.argv[1].split(',')]
    else:
        try:
            keywords = input("Enter keywords (e.g., 'homelander, the boys'): ")
            keyword_list = [k.strip() for k in keywords.split(',')]
        except EOFError:
            print("No input provided. Exiting.")
            return

    # Initialize Modules
    roblox     = RobloxScraper(cookie=cookie)
    downloader = AssetDownloader()
    designer   = TemplateDesigner()

    # Process Shirts then Pants
    upload_count = 0
    
    # Step 1: Search Shirts and Process valid pairs
    print(f"Searching for keywords: {keyword_list}")
    upload_count = 0
    
    for keyword in keyword_list:
        print(f"\n=======================================================")
        print(f"  PROCESSING KEYWORD: {keyword}")
        print(f"=======================================================\n")
        
        pairs_found = 0
        target_pairs = 5
        
        # Step 0: Pre-fetch pants pool for fallback
        print(f"  Preparing pants pool for creator-match fallback...")
        pants_pool = await roblox.search_and_get_assets(keyword, count=40, asset_type=12)
        used_pants_ids = set()

        try:
            # We use the generator to continually pull shirts until we find 5 valid pairs
            async for asset_id, item_url, creator in roblox.search_and_yield_assets(keyword):
                if pairs_found >= target_pairs:
                    print(f"  Reached target of {target_pairs} pairs for '{keyword}'. Moving to next keyword.")
                    break
                    
                print(f"\n--- Checking Shirt: {asset_id} (Tag: {keyword}) by {creator} ---")
                
                # Method A: Direct link in description
                try:
                    paired_pants = await roblox.get_paired_pants(asset_id)
                except Exception as e:
                    paired_pants = []
                    print(f"[PairedPants] Error: {e}")

                pants_id = None
                pants_catalog_url = None

                if paired_pants:
                    pants_id, pants_catalog_url = paired_pants[0]
                    print(f"  [Match] Found via direct link: {pants_id}")
                else:
                    # Method B: Creator matching fallback
                    match = [(p[0], p[1]) for p in pants_pool if p[2] == creator and p[0] not in used_pants_ids]
                    if match:
                        pants_id, pants_catalog_url = match[0]
                        print(f"  [Match] Found via creator fallback: {pants_id}")

                if not pants_id:
                    print(f"  No match found (neither link nor creator fallback). Skipping.")
                    continue
                        
                used_pants_ids.add(pants_id)
                print(f"  Proceeding with shirt and pants download. (Pair {pairs_found + 1}/{target_pairs})")
                
                try:
                    # 1. Download and design the shirt
                    shirt_out = await download_and_design(
                        asset_id, keyword, "shirt", downloader, designer
                    )

                    # 2. Download and design the pants
                    print(f"\n  └─ Paired Pants: {pants_id} - {pants_catalog_url}")
                    pants_out = await download_and_design(
                        pants_id, keyword, "pants", downloader, designer
                    )

                    # 3. Upload the pair (if uploader active)
                    if uploader and shirt_out and pants_out:
                        upload_count = await upload_pair_with_crosslink(
                            asset_id, shirt_out,
                            pants_id, pants_out,
                            keyword, uploader, upload_count, cfg
                        )
                    
                    pairs_found += 1

                except Exception as e:
                    print(f"Error processing asset pair for {asset_id}: {e}")

        except Exception as e:
            print(f"Error streaming search for {keyword}: {e}")

    print(f"\nDone. {upload_count} item(s) uploaded to group.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
