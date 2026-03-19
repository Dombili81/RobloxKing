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
from scrapers.utils import Logger

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
        "TARGET_PAIRS": int(os.environ.get("TARGET_PAIRS", 5)),
        "REQUIRE_APPROVAL": int(os.environ.get("REQUIRE_APPROVAL", 0)),
        "PAIR_MODE": os.environ.get("PAIR_MODE", "pair"),
    }
    cloud_settings = db_manager.load_settings()
    for k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "MAX_UPLOADS_PER_SESSION", "TARGET_PAIRS", "REQUIRE_APPROVAL"]:
        if k in cloud_settings:
            try:
                config[k] = int(cloud_settings[k])
            except ValueError:
                pass
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in config:
                    try:
                        if key == "PAIR_MODE": config[key] = val.strip()
                        else: config[key] = int(val.strip())
                    except ValueError:
                        pass
    return config

# --- Load Cookie ---
def load_cookie(path="cookie.txt"):
    cloud_settings = db_manager.load_settings()
    if cloud_settings.get("ROBLOX_COOKIE"):
        env_cookie = cloud_settings["ROBLOX_COOKIE"]
        if env_cookie.startswith(".ROBLOSECURITY="):
            return env_cookie[len(".ROBLOSECURITY="):]
        return env_cookie
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip().strip('"').strip("'")
            if raw: return raw[15:] if raw.startswith(".ROBLOSECURITY=") else raw
    env_cookie = os.environ.get("ROBLOX_COOKIE")
    if env_cookie:
        if env_cookie.startswith(".ROBLOSECURITY="):
            return env_cookie[len(".ROBLOSECURITY="):]
        return env_cookie
    return None

# --- Metadata Generator ---
def generate_metadata(keyword: str, item_type: str, pair_url: str = "", use_suffix: bool = True) -> tuple[str, str]:
    kw_title = keyword.title()
    if use_suffix:
        name = f"{kw_title} [{'+' if item_type=='shirt' else '-'}]"
    else:
        name = kw_title
    
    if pair_url:
        pair_line = f"\nMatching {'Pants' if item_type=='shirt' else 'Shirt'}:\n{pair_url}\n"
    else:
        pair_line = ""

    description = (
        "⭐️Don't forget to favorite our shirt for more cool clothes! "
        f"{pair_line}\n"
        "🔥𝐎𝐑𝐈𝐆𝐈𝐍𝐀𝐋🔥 \n"
        "~~~\n"
        f"Tags: {keyword} {BASE_TAGS} {get_tags(keyword)}"
    )
    Logger.debug(f"{item_type.upper()} açıklama uzunluğu: {len(description)}")
    return name, description

# --- Download + Design ---
async def download_and_design(asset_id, search_tag, item_type, downloader, designer, custom_label=None):
    path = await downloader.download_template(asset_id)
    if not path:
        return None
    label = custom_label or f"{search_tag.replace(' ','_')}_{item_type}_{asset_id}.png"
    return await designer.process_image(path, "template.png", custom_filename=label)

# --- Upload Pair ---
async def upload_pair_with_crosslink(shirt_id, shirt_path, pants_id, pants_path, keyword, uploader, upload_count, cfg):
    max_uploads = cfg["MAX_UPLOADS_PER_SESSION"]
    if max_uploads > 0 and upload_count >= max_uploads:
        Logger.warn("Oturum yükleme limiti doldu.")
        return upload_count

    def _anti_ban():
        wait = random.uniform(cfg["DELAY_MIN"], cfg["DELAY_MAX"])
        Logger.debug(f"Yükleme arası gecikme: {wait:.1f}s ...")
        time.sleep(wait)

    # 1. Pants
    p_name, p_desc_temp = generate_metadata(keyword, "pants")
    if upload_count > 0: _anti_ban()
    p_asset_id = uploader.upload_asset(pants_path, p_name, p_desc_temp, item_type=12)
    if not p_asset_id:
        return upload_count
    upload_count += 1
    p_url = f"https://www.roblox.com/catalog/{p_asset_id}/"
    Logger.success(f"'{p_name}' yüklendi! ID: {p_asset_id}")

    # 2. Shirt
    s_name, s_desc_linked = generate_metadata(keyword, "shirt", pair_url=p_url)
    _anti_ban()
    s_asset_id = uploader.upload_asset(shirt_path, s_name, s_desc_linked, item_type=11)
    if not s_asset_id:
        return upload_count
    
    # ── Duplicate Check Mark ──
    db_manager.mark_item_as_uploaded(shirt_id, s_asset_id)
    db_manager.mark_item_as_uploaded(pants_id, p_asset_id)

    upload_count += 1
    s_url = f"https://www.roblox.com/catalog/{s_asset_id}/"
    Logger.success(f"'{s_name}' yüklendi! ID: {s_asset_id}")

    # 3. Crosslink
    Logger.debug("Açıklamalar çapraz bağlanıyor...")
    time.sleep(3)
    _, p_desc_linked = generate_metadata(keyword, "pants", pair_url=s_url)
    uploader.update_description(p_asset_id, p_name, p_desc_linked, item_type=12)
    
    return upload_count

# --- Upload Single ---
async def upload_single_asset(asset_id, asset_path, keyword, uploader, upload_count, cfg, item_type=11):
    max_uploads = cfg["MAX_UPLOADS_PER_SESSION"]
    if max_uploads > 0 and upload_count >= max_uploads:
        Logger.warn("Oturum yükleme limiti doldu.")
        return upload_count

    if upload_count > 0:
        wait = random.uniform(cfg["DELAY_MIN"], cfg["DELAY_MAX"])
        Logger.debug(f"Yükleme arası gecikme: {wait:.1f}s ...")
        time.sleep(wait)

    name, desc = generate_metadata(keyword, "shirt" if item_type == 11 else "pants", use_suffix=False)
    new_id = uploader.upload_asset(asset_path, name, desc, item_type=item_type)
    if new_id:
        db_manager.mark_item_as_uploaded(asset_id, new_id)
        upload_count += 1
        Logger.success(f"'{name}' yüklendi! ID: {new_id}")
    return upload_count