"""
bot.py – Butonlu Telegram Botu (Roblox Otomasyon)
"""

import asyncio
import os
import threading
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)

from scrapers.roblox     import RobloxScraper
from scrapers.downloader import AssetDownloader
from scrapers.designer   import TemplateDesigner
from scrapers.uploader   import AssetUploader
from scrapers.finance    import GroupFinanceMonitor
from scrapers.firebase_db import FirebaseManager
from scrapers.utils import Logger, md_escape
from scrapers.ugc_mesh_processor import process_ugc_catalog_zip
from main import generate_metadata, download_and_design, upload_pair_with_crosslink, upload_single_asset

# ─── Firebase Init ───────────────────────────────────────────────────────────
db_manager = FirebaseManager()

# ─── Config ──────────────────────────────────────────────────────────────────
def load_bot_config(path="bot_config.txt"):
    cfg = {
        "BOT_TOKEN": os.environ.get("BOT_TOKEN", ""),
        "ALLOWED_USER_ID": os.environ.get("ALLOWED_USER_ID", "0")
    }
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k_clean, v_clean = k.strip(), v.strip()
                    if v_clean: # File values overwrite Env Vars
                        cfg[k_clean] = v_clean
    return cfg

def load_roblox_config(path="config.txt"):
    cfg = {
        "GROUP_ID": int(os.environ.get("GROUP_ID", 0)),
        "PRICE": int(os.environ.get("PRICE", 5)),
        "DELAY_MIN": int(os.environ.get("DELAY_MIN", 45)),
        "DELAY_MAX": int(os.environ.get("DELAY_MAX", 90)),
        "MAX_UPLOADS_PER_SESSION": int(os.environ.get("MAX_UPLOADS_PER_SESSION", 10)),
        "TARGET_PAIRS": int(os.environ.get("TARGET_PAIRS", 5)),
        "SORT_TYPE": int(os.environ.get("SORT_TYPE", 2)),
        "SORT_AGG": int(os.environ.get("SORT_AGG", 5)),
        "REQUIRE_APPROVAL": int(os.environ.get("REQUIRE_APPROVAL", 0)),
        "PAIR_MODE": os.environ.get("PAIR_MODE", "pair"),
        "SINGLE_TYPE": int(os.environ.get("SINGLE_TYPE", 11)),
    }
    
    # 1. Local file (overwrites Env Vars)
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k in cfg:
                        try:
                            cfg[k] = int(v.strip())
                        except ValueError:
                            pass

    # 2. Cloud Settings (Overwrites EVERYTHING except if cloud value is 0 for critical IDs)
    cloud_settings = db_manager.load_settings()
    for k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "TARGET_PAIRS", "REQUIRE_APPROVAL"]:
        if k in cloud_settings:
            try:
                if k == "REQUIRE_APPROVAL":
                    cfg[k] = int(cloud_settings[k])
                else:
                    val = int(cloud_settings[k])
                    # If cloud has a '0' for GROUP_ID but local has a real ID, keep the local one.
                    if k == "GROUP_ID" and val == 0 and cfg[k] != 0:
                        continue
                    cfg[k] = val
            except ValueError:
                pass
    # PAIR_MODE from cloud (string)
    if "PAIR_MODE" in cloud_settings:
        val = cloud_settings["PAIR_MODE"]
        if val in ["pair", "single", "ugc"]:
            cfg["PAIR_MODE"] = val
    if "SINGLE_TYPE" in cloud_settings:
        try:
            cfg["SINGLE_TYPE"] = int(cloud_settings["SINGLE_TYPE"])
        except ValueError:
            pass
            
    global TARGET_PAIRS
    if "TARGET_PAIRS" in cfg:
        TARGET_PAIRS = cfg["TARGET_PAIRS"]
        
    return cfg

def save_roblox_config(cfg, path="config.txt"):
    for k, v in cfg.items():
        if k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "TARGET_PAIRS", "SORT_TYPE", "SORT_AGG", "REQUIRE_APPROVAL"]:
            db_manager.save_setting(k, v)
    # PAIR_MODE'u da kaydet (string)
    if "PAIR_MODE" in cfg:
        db_manager.save_setting("PAIR_MODE", cfg["PAIR_MODE"])
    if "SINGLE_TYPE" in cfg:
        db_manager.save_setting("SINGLE_TYPE", cfg["SINGLE_TYPE"])

    with open(path, "w") as f:
        f.write(
            f"GROUP_ID={cfg['GROUP_ID']}\n"
            f"PRICE={cfg['PRICE']}\n"
            f"DELAY_MIN={cfg['DELAY_MIN']}\n"
            f"DELAY_MAX={cfg['DELAY_MAX']}\n"
            f"TARGET_PAIRS={cfg['TARGET_PAIRS']}\n"
            f"SORT_TYPE={cfg['SORT_TYPE']}\n"
            f"SORT_AGG={cfg['SORT_AGG']}\n"
            f"REQUIRE_APPROVAL={cfg['REQUIRE_APPROVAL']}\n"
            f"PAIR_MODE={cfg['PAIR_MODE']}\n"
            f"SINGLE_TYPE={cfg['SINGLE_TYPE']}\n"
        )

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
        with open(path, encoding="utf-8") as f:
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

BOT_CFG     = load_bot_config()
BOT_TOKEN   = BOT_CFG.get("BOT_TOKEN", "")
# ALLOWED_IDS can be a comma-separated string: "123, 456, 789"
raw_ids     = str(BOT_CFG.get("ALLOWED_USER_ID", "0"))
ALLOWED_IDS = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]

# ─── Conversation states ──────────────────────────────────────────────────────
WAITING_KEYWORD  = 1
WAITING_GROUP    = 2
WAITING_PRICE    = 3
WAITING_PAIRS    = 4

# ─── Job state ────────────────────────────────────────────────────────────────
_job_stop  = threading.Event()
_job_info  = {"status": "idle", "keywords": [], "pairs_done": 0, "uploads": 0}
# Global Ayarlar
TARGET_PAIRS = 5  # Varsayılan

_initial_cfg = load_roblox_config()
# load_roblox_config içinde TARGET_PAIRS güncelleniyor

# Onay sistemi için global değişkenler
_pending_events = {}   # unique_id -> asyncio.Event
_pending_status = {}   # unique_id -> "approve" | "reject" | "skip"
_pending_items = {}    # unique_id -> item data (dict)
_pending_lock = threading.Lock()  # thread-safe erişim için

# ─── Auth ─────────────────────────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_IDS

async def deny(update: Update):
    if update.message:
        await update.message.reply_text("⛔ Erişim reddedildi.")
    elif update.callback_query:
        await update.callback_query.answer("⛔ Erişim reddedildi.", show_alert=True)

# ─── Keyboards ───────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀  İş Başlat",  callback_data="run"),
         InlineKeyboardButton("📊  Durum",       callback_data="status")],
        [InlineKeyboardButton("⚙️  Ayarlar",     callback_data="settings"),
         InlineKeyboardButton("📈  Satışlar",    callback_data="finance")],
        [InlineKeyboardButton("📦  Son Yüklemeler", callback_data="recent_uploads"),
         InlineKeyboardButton("💡  Öneriler", callback_data="trends_suggestions")],
        [InlineKeyboardButton("🎲  3D Model Oluştur", callback_data="model3d_menu")],
        [InlineKeyboardButton("🛑  Durdur",      callback_data="stop"),
         InlineKeyboardButton("❓  Yardım",      callback_data="help")],
    ])

def settings_keyboard():
    cfg = load_roblox_config()
    price   = cfg["PRICE"]
    group   = cfg["GROUP_ID"] if cfg["GROUP_ID"] else "Ayarlanmadı"
    cookie_str = "Ayarlı ✅" if load_cookie() else "Yok ❌"
    approval_str = "Açık ✅" if cfg.get("REQUIRE_APPROVAL", 0) == 1 else "Kapalı ❌"
    pair_mode = cfg.get("PAIR_MODE", "pair")
    if pair_mode == "pair":
        mode_str = "Çift Mod"
        target_label = "Hedef Çift"
    elif pair_mode == "single":
        mode_str = "Tekli Mod"
        target_label = "Hedef Item"
    else:
        mode_str = "3D UGC Mod"
        target_label = "Hedef 3D Asset"
    sort_label_map = {
        (2, 5): "En Çok Satan (Tüm Zamanlar)",
        (2, 3): "En Çok Satan (Son Hafta)",
        (2, 1): "En Çok Satan (Son Gün)",
        (1, 5): "En Çok Favorilenen",
        (4, 5): "Fiyat: Düşük ➡ Yüksek",
        (5, 5): "Fiyat: Yüksek ➡ Düşük",
        (0, 5): "En Alakalı (By Relevance)"
    }
    sort_key = (cfg.get("SORT_TYPE", 2), cfg.get("SORT_AGG", 5))
    sort_label = sort_label_map.get(sort_key, "En Çok Satan (Tüm Zamanlar)")
    
    kb = [
        [InlineKeyboardButton(f"💰  Fiyat: {price} Robux",   callback_data="set_price")],
        [InlineKeyboardButton(f"🏷  Grup ID: {group}",       callback_data="set_group")],
        [InlineKeyboardButton(f"🎯  {target_label}: {TARGET_PAIRS}", callback_data="set_pairs")],
        [InlineKeyboardButton(f"🔑  Cookie: {cookie_str}",       callback_data="set_cookie")],
        [InlineKeyboardButton(f"🔐  Onay Gerekli: {approval_str}", callback_data="toggle_approval")],
        [InlineKeyboardButton(f"👕  Mod: {mode_str}",           callback_data="set_pair_mode")],
    ]
    
    if pair_mode == "single":
        single_type = cfg.get("SINGLE_TYPE", 11)
        type_str = "Shirt" if single_type == 11 else "Pants"
        kb.append([InlineKeyboardButton(f"👔  Tekli Tip: {type_str}", callback_data="toggle_single_type")])
    elif pair_mode == "ugc":
        kb.append([InlineKeyboardButton(f"📦  3D UGC İndirme Aktif (Upload Yapılmaz)", callback_data="none")])
        
    kb.append([InlineKeyboardButton(f"🧭  Sıralama: {sort_label}",      callback_data="set_sort")])
    kb.append([InlineKeyboardButton("⬅️  Ana Menü",                 callback_data="main")])

    return InlineKeyboardMarkup(kb)

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️  Ana Menü", callback_data="main")]
    ])

def help_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀  İş Başlatma",   callback_data="help_run"),
         InlineKeyboardButton("⚙️  Ayarlar",       callback_data="help_settings")],
        [InlineKeyboardButton("📊  Durum & Durdur", callback_data="help_status"),
         InlineKeyboardButton("🔑  Cookie",        callback_data="help_cookie")],
        [InlineKeyboardButton("⬅️  Ana Menü",      callback_data="main")],
    ])

# ─── Welcome text ─────────────────────────────────────────────────────────────
WELCOME = (
    "👋 *Hoş Geldin!*\n\n"
    "Bu bot Roblox kıyafetlerini otomatik olarak bulur, tasarım ekler ve grubuna satışa koyar.\n\n"
    "Aşağıdan bir işlem seç:"
)

# ─── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    status = "AKTİF ✅" if db_manager.is_active else "DEVRE DIŞI ❌ (Anahtar Eksik)"
    msg = f"{WELCOME}\n\n🛰 **Firebase Durumu:** {status}"
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

async def cmd_debug_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    cfg = load_roblox_config()
    save_roblox_config(cfg)
    status = "BAŞARILI ✅" if db_manager.is_active else "BAŞARISIZ ❌ (Firebase Bağlı Değil)"
    await update.message.reply_text(f"🔄 **Manuel Senkronizasyon:** {status}\n\nFirebase'e itilen değerler:\n`GROUP_ID: {cfg['GROUP_ID']}`\n`TARGET_PAIRS: {cfg['TARGET_PAIRS']}`", parse_mode="Markdown")

# ─── Callback router ─────────────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    q    = update.callback_query
    data = q.data
    cfg  = load_roblox_config()
    
    try:
        await q.answer()
    except Exception:
        pass

    # ── Ana Menü ──
    if data == "main":
        await q.edit_message_text(WELCOME, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END

    # ── Son Yüklemeler ──
    elif data.startswith("recent_uploads"):
        try:
            parts = data.split("_")
            page = int(parts[2]) if len(parts) > 2 else 0
            offset = page * 5
            
            await q.edit_message_text(f"📦 *Son yüklemeler getiriliyor (Sayfa {page+1})...*", parse_mode="Markdown")
            
            import requests
            # Fetch 6 items to see if there's a next page
            recent_items_all = await asyncio.to_thread(db_manager.get_recent_uploads, 6, offset)
            
            if not recent_items_all and page == 0:
                await q.edit_message_text("❌ Henüz yüklenen hiçbir ürün bulunamadı.", reply_markup=back_keyboard(), parse_mode="Markdown")
                return
            elif not recent_items_all:
                await q.edit_message_text("❌ Bu sayfada sonuç bulunamadı.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Önceki", callback_data=f"recent_uploads_{page-1}")]]), parse_mode="Markdown")
                return
            
            has_next = len(recent_items_all) == 6
            recent_items = recent_items_all[:5]
            
            kb_rows = []
            valid_count = 0
            
            def fetch_names(items, current_cookie):
                sess = requests.Session()
                if current_cookie:
                    sess.cookies.set(".ROBLOSECURITY", current_cookie, domain=".roblox.com")
                results = []
                for item in items:
                    r_id = item.get("roblox_id", "")
                    if not r_id or str(r_id) in ("None", "0"):
                        continue
                    name = f"Ürün ({r_id})" # Default
                    try:
                        # Economy API is better for off-sale/private group items
                        r = sess.get(f"https://economy.roblox.com/v2/assets/{r_id}/details", timeout=4)
                        if r.status_code == 200:
                            name = r.json().get("Name", name)
                        else:
                            # Fallback to catalog API
                            r2 = sess.get(f"https://catalog.roblox.com/v1/assets/{r_id}/details", timeout=4)
                            if r2.status_code == 200:
                                name = r2.json().get("Name", name)
                    except Exception:
                        pass
                    
                    results.append({"id": r_id, "name": name, "is_pair": item.get("is_pair", False)})
                return results

            fetched_items = await asyncio.to_thread(fetch_names, recent_items, load_cookie())
            
            for item in fetched_items:
                r_id = item["id"]
                name = item["name"]
                
                if item.get("is_pair"):
                    name += " (Çift)"
                
                # Telegram inline button sınırı
                btn_name = f"📦 {name[:40]}"
                kb_rows.append([InlineKeyboardButton(btn_name, callback_data=f"preview_{r_id}_{page}")])
                valid_count += 1
                
            if valid_count == 0:
                await q.edit_message_text("❌ Geçerli bir yükleme ID'si bulunamadı.", reply_markup=back_keyboard(), parse_mode="Markdown")
                return
                
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("⬅️ Önceki Sayfa", callback_data=f"recent_uploads_{page-1}"))
            if has_next:
                nav_row.append(InlineKeyboardButton("Sonraki Sayfa ➡️", callback_data=f"recent_uploads_{page+1}"))
            
            if nav_row:
                kb_rows.append(nav_row)
            kb_rows.append([InlineKeyboardButton("🏠 Ana Menü", callback_data="main")])
            
            await q.edit_message_text(
                f"📦 *Son Yüklenen Ürünler (Sayfa {page+1})*\n\nÖnizlemesini görmek istediğin ürüne tıkla:",
                reply_markup=InlineKeyboardMarkup(kb_rows),
                parse_mode="Markdown"
            )
            
        except Exception as e:
            Logger.error(f"Recent uploads err: {e}")
            await q.edit_message_text(f"❌ Hata: `{md_escape(str(e))}`", reply_markup=back_keyboard(), parse_mode="Markdown")

    # ── Önizleme (Preview) ──
    elif data.startswith("preview_"):
        parts = data.split("_")
        r_id = parts[1]
        page = parts[2] if len(parts) > 2 else "0"
        
        await q.edit_message_text(f"⏳ *Önizleme getiriliyor ({r_id})...*", parse_mode="Markdown")
        
        try:
            import requests
            cookie = load_cookie()
            
            title = "Bilinmeyen Ürün"
            desc = "Açıklama bulunmuyor."
            created_str = "Bilinmiyor"
            
            def get_details():
                sess = requests.Session()
                if cookie:
                    sess.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
                try:
                    d = sess.get(f"https://economy.roblox.com/v2/assets/{r_id}/details", timeout=5)
                    if d.status_code == 200:
                        return d.json()
                    d2 = sess.get(f"https://catalog.roblox.com/v1/assets/{r_id}/details", timeout=5)
                    if d2.status_code == 200:
                        return d2.json()
                except Exception:
                    pass
                return {}
            
            details = await asyncio.to_thread(get_details)
            if details:
                title = details.get("Name", title)
                raw_desc = details.get("Description", "")
                if raw_desc:
                    desc = raw_desc
                
                raw_date = details.get("Created", "")
                if raw_date and "T" in raw_date:
                    date_part, time_part = raw_date.split("T")
                    time_part = time_part.split(".")[0]
                    created_str = f"{date_part} {time_part}"
                elif raw_date:
                    created_str = raw_date
            
            async with RobloxScraper(cookie) as roblox:
                thumb_url = await roblox.get_thumbnail(r_id)
                
            item_link = f"https://www.roblox.com/catalog/{r_id}"
            
            # Telegram caption limiti ~1024 karakterdir. Çökmemesi için 900'de kesilir.
            desc_cut = desc[:900] + ("..." if len(desc) > 900 else "")
            caption = (
                f"🏷️ *{md_escape(title)}*\n\n"
                f"📝 _{md_escape(desc_cut)}_\n\n"
                f"📅 *Yüklenme:* `{created_str}`\n\n"
                f"🔗 **[Satın Alma Linki İçin Tıklayın]({item_link})**"
            )
            
            if thumb_url:
                await update.effective_chat.send_photo(
                    photo=thumb_url,
                    caption=caption,
                    parse_mode="Markdown"
                )
                await q.message.delete()
                await update.effective_chat.send_message(
                    "⬅️ Listeye Geri Dön",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri Dön", callback_data=f"recent_uploads_{page}")]])
                )
            else:
                await q.edit_message_text(
                    f"❌ *Görsel alınamadı!*\n\n{caption}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri Dön", callback_data=f"recent_uploads_{page}")]])
                    , parse_mode="Markdown", disable_web_page_preview=True
                )
                
        except Exception as e:
            Logger.error(f"Preview err: {e}")
            await q.edit_message_text(
                f"❌ Önizleme Hatası: `{md_escape(str(e))}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri Dön", callback_data=f"recent_uploads_{page}")]])
                , parse_mode="Markdown"
            )

    # ── 3D Model Menüsü ──
    elif data == "model3d_menu":
        await q.edit_message_text(
            "🎲 *3D Model Oluşturma Aracı*\n\n"
            "Ücretsiz AI teknolojisi ile 3D model üret ve GLB dosyası olarak al.\n\n"
            "*Text ile:* Modeli kelimelerle açıkla\n"
            "*Görsel ile:* Fotoğraf yükle, 3D'ye dönüştür\n\n"
            "⏱ Ortalama süre: 2-5 dakika",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️  Metin ile Oluştur", callback_data="model3d_text")],
                [InlineKeyboardButton("🖼️  Görsel ile Oluştur", callback_data="model3d_image")],
                [InlineKeyboardButton("⬅️  Ana Menü", callback_data="main")],
            ]),
            parse_mode="Markdown"
        )

    elif data == "model3d_text":
        ctx.user_data["awaiting"] = "model3d_prompt"
        await q.edit_message_text(
            "✍️ *3D Model — Metin Açıklaması*\n\n"
            "Oluşturmak istediğin modeli Türkçe veya İngilizce yaz:\n\n"
            "💡 *Örnek:*\n"
            "`a red samurai armor`\n"
            "`anime katana sword glowing blue`\n"
            "`cute robot character white and orange`\n\n"
            "Şimdi mesajını yaz:",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "model3d_image":
        ctx.user_data["awaiting"] = "model3d_image_wait"
        await q.edit_message_text(
            "🖼️ *3D Model — Görsel ile Oluştur*\n\n"
            "Şimdi bir fotoğraf gönder, AI 3D modele dönüştürsün.\n\n"
            "📌 *İpuçları:*\n"
            "• Tek nesne içeren fotoğraflar daha iyi sonuç verir\n"
            "• Sade / beyaz arka plan tercih et\n"
            "• Nesne net ve ortada olsun\n\n"
            "Fotoğrafı gönder:",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )

    # ── Öneriler / Trendler ──
    elif data == "trends_suggestions":
        await q.edit_message_text(
            "💡 *Akıllı Trend Motoru Devrede*\n\n"
            "1️⃣ Google Trends ve Roblox Catalog verileri toplanıyor...\n"
            "2️⃣ Potansiyel stiller filtreleniyor...\n"
            "3️⃣ Piyasada test ediliyor...\n\n"
            "⏳ _Lütfen 5-15 saniye bekleyin, gerçek satış odaklı anahtar kelimeler oluşturuluyor..._",
            parse_mode="Markdown"
        )
        try:
            from scrapers.trend_engine import TrendEngine
            
            engine = TrendEngine(db_manager)
            trends = await engine.get_suggestions()
            
            if not trends:
                await q.edit_message_text(
                    "❌ *Roblox'ta kanıtlanmış satış hacmi olan yeni bir konu bulunamadı.*\n\n"
                    "_Biraz sonra tekrar dene._",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Tekrar Tara", callback_data="trends_suggestions")],
                        [InlineKeyboardButton("🏠 Ana Menü", callback_data="main")]
                    ]),
                    parse_mode="Markdown"
                )
                return

            def fmt(n):
                if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
                if n >= 1_000: return f"{n/1_000:.1f}K"
                return str(n)

            msg = "🔥 *ROBLOX SATIŞ KANITLI EN POPÜLER 5 TREND*\n"
            msg += "_Akıllı Motor: Veriler filtrelendi, dönüştürüldü ve hacimleri doğrulandı:_\n\n"
            kb_rows = []

            for i, item in enumerate(trends, 1):
                kw = item["kw"]
                favs = fmt(item["favorites"])
                sample = item["sample_item"]
                clicks = item.get("clicks", 0)
                click_warn = f" (🔥 {clicks} Kez Üretildi)" if clicks > 0 else ""
                
                msg += f"*{i}. {md_escape(kw)}{click_warn}*\n"
                msg += f"↳ 🌟 Hacim: `{favs} Favori`\n"
                msg += f"↳ 👕 Örnek ürün: _{md_escape(sample)}_\n\n"
                kb_rows.append([InlineKeyboardButton(f"🚀 Üret: {kw}", callback_data=f"run_kw_{kw[:30]}")])

            kb_rows.append([InlineKeyboardButton("↩️ Tekrar Tara (Anlık Yeni)", callback_data="trends_suggestions")])
            kb_rows.append([InlineKeyboardButton("🏠 Ana Menü", callback_data="main")])

            await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")

        except Exception as e:
            Logger.error(f"Trends error: {e}")
            await q.edit_message_text(f"❌ Hata: `{md_escape(str(e))}`", reply_markup=back_keyboard(), parse_mode="Markdown")

    elif data.startswith("run_kw_"):
        # Direct keyword run from popular keywords
        keyword = data[7:]  # strip 'run_kw_'
        
        # Track click
        try: db_manager.increment_trend_click(keyword)
        except Exception as e: print(f"Trend click error: {e}")
        if _job_info["status"] == "running":
            await q.edit_message_text("⚠️ Zaten bir iş çalışıyor.", reply_markup=back_keyboard())
            return
        await q.edit_message_text(f"🚀 *{md_escape(keyword.title())}* için iş başlatılıyor...", parse_mode="Markdown")
        await start_job(update, ctx, [keyword])

    # ── Durum ──
    elif data == "status":
        info = _job_info
        if info["status"] == "idle":
            text = "💤 *Şu an çalışan bir iş yok.*"
        else:
            kws  = ", ".join(info["keywords"])
            text = (
                f"⚙️ *İş Çalışıyor*\n\n"
                f"🔍 Keyword(ler): `{kws}`\n"
                f"✅ Bulunan çift: `{info['pairs_done']}`\n"
                f"☁️ Yüklenen: `{info['uploads']}`"
            )
        await q.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

    # ── Durdur ──
    elif data == "stop":
        if _job_info["status"] != "running" or _active_task is None:
            await q.edit_message_text("ℹ️ Çalışan bir iş zaten yok.", reply_markup=back_keyboard(), parse_mode="Markdown")
        else:
            _job_stop.set()
            if _active_task and not _active_task.done():
                _active_task.cancel()
            _job_info["status"] = "idle"
            await q.edit_message_text("🛑 *İş anında durduruldu.*", reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    # ── Finans & Satışlar ──
    elif data == "finance":
        cfg = load_roblox_config()
        cookie = load_cookie()
        gid = cfg.get("GROUP_ID")
        if not cookie or not gid:
            await q.edit_message_text("❌ *Grup ID veya Cookie eksik!*\nSatışları görmek için önce ayarları yapmalısın.", reply_markup=back_keyboard(), parse_mode="Markdown")
            return
            
        await q.edit_message_text("⏳ *Satış verileri çekiliyor...*", parse_mode="Markdown")
        
        try:
            monitor = GroupFinanceMonitor(cookie, gid)
            summary = await asyncio.to_thread(monitor.get_summary)
            
            pending = summary.get("pending", 0)
            sales   = summary.get("item_sales_robux", 0)
            balance = summary.get("user_balance", 0)
            u_name  = summary.get("user_name", "Bilinmeyen")
            g_err   = summary.get("group_error")

            # Grup satışları metni
            if g_err:
                group_text = f"⚠️ *Grup Satışları:* `{md_escape(str(g_err))}`"
            else:
                group_text = (
                    f"💸 Bekleyen Robux: `{pending} R$`\n"
                    f"🛍️ Bugün Satışlardan Gelen: `{sales} R$`"
                )

            text = (
                f"📈 *Finans Özeti*\n\n"
                f"👤 Kullanıcı: `{md_escape(u_name)}`\n"
                f"💰 *Hesap Bakiyesi:* `{balance} R$`\n\n"
                f"{group_text}\n\n"
                f"_Anlık satış bildirimleri arkaplanda aktiftir._"
            )
            await q.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        except Exception as e:
            Logger.error(f"Finans Hata: {e}")
            await q.edit_message_text(f"❌ *Bağlantı Hatası:*\n`{md_escape(str(e))}`\n_Cookie güncellemeyi dene._", reply_markup=back_keyboard(), parse_mode="Markdown")

    # ── Ayarlar ──
    elif data == "settings":
        await q.edit_message_text("⚙️ *Ayarlar*\nDeğiştirmek istediğin ayara tıkla:", reply_markup=settings_keyboard(), parse_mode="Markdown")

    # ── Ayar seçenekleri ──
    elif data == "set_price":
        ctx.user_data["awaiting"] = "price"
        await q.edit_message_text(
            "💰 *Fiyat Ayarla*\n\nYeni fiyatı Robux olarak yaz (örn: `5`):",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )

    elif data == "set_group":
        ctx.user_data["awaiting"] = "group"
        await q.edit_message_text(
            "🏷 *Grup ID Ayarla*\n\nRoblox grup ID numaranı yaz:\n_(Örn: `12345678`)_\n\n"
            "Grup ID'ni bulmak için: roblox.com/groups/**12345678**/...",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )

    elif data == "set_pairs":
        ctx.user_data["awaiting"] = "pairs"
        cfg = load_roblox_config()
        pair_mode = cfg.get("PAIR_MODE", "pair")
        target_label = "çift" if pair_mode == "pair" else "item"
        await q.edit_message_text(
            f"🎯 *Hedef {target_label.title()} Sayısı*\n\nŞu an: `{TARGET_PAIRS}`\n\nHer keyword için kaç {target_label} indirilsin? (1–30):",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )

    elif data == "set_cookie":
        ctx.user_data["awaiting"] = "cookie"
        await q.edit_message_text(
            "🔑 *Cookie Ayarla*\n\nYeni `.ROBLOSECURITY` cookie değerini buraya yapıştır:\n"
            "_(Sadece başına ve sonuna tırnak koymadan, değerin kendisini yapıştır)_",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )

    elif data == "set_sort":
        await q.edit_message_text(
            "🧭 *Sıralama Şekli*\n\n"
            "Sonraki indirmelerde hangi sıraya göre arama yapılacağını seç:\n\n"
            "1️⃣ En Çok Satan (Tüm Zamanlar)\n"
            "2️⃣ En Çok Satan (Son Hafta)\n"
            "3️⃣ En Çok Satan (Son Gün)\n"
            "4️⃣ En Çok Favorilenen (Tüm Zamanlar)\n"
            "5️⃣ Fiyat: Düşük → Yüksek\n"
            "6️⃣ Fiyat: Yüksek → Düşük\n"
            "7️⃣ En Alakalı (By Relevance)\n\n"
            "Seçtiğin numarayı yaz (örn: `1`).",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        ctx.user_data["awaiting"] = "sort"

    elif data == "toggle_single_type":
        cfg = load_roblox_config()
        current = cfg.get("SINGLE_TYPE", 11)
        new_type = 12 if current == 11 else 11
        cfg["SINGLE_TYPE"] = new_type
        save_roblox_config(cfg)
        
        # UI'yı hemen güncellemek için settings_keyboard'u tekrar gönderiyoruz
        type_str = "Pants (Alt)" if new_type == 12 else "Shirt (Üst)"
        await q.answer(f"Mod Değişti: {type_str}")
        await q.edit_message_reply_markup(reply_markup=settings_keyboard())

    elif data == "toggle_approval":
        cfg = load_roblox_config()
        current = cfg.get("REQUIRE_APPROVAL", 0)
        new_val = 0 if current == 1 else 1
        cfg["REQUIRE_APPROVAL"] = new_val
        save_roblox_config(cfg)
        status = "AÇIK ✅" if new_val == 1 else "KAPALI ❌"
        await q.edit_message_text(
            f"🔐 *Onay Zorunluluğu*\n\n"
            f"Durum: **{status}**\n\n"
            f"{'✅ Onay aktif: Bot bulduğu kıyafetleri önce gösterip onay isteyecek.' if new_val == 1 else '❌ Onay kapalı: Bulunan kıyafetler otomatik yüklenecek.'}\n\n"
            f"Ayarlar kaydedildi. Ana menüye dönüyorsunuz…",
            reply_markup=settings_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "set_pair_mode":
        cfg = load_roblox_config()
        current = cfg.get("PAIR_MODE", "pair")
        modes = ["pair", "single", "ugc"]
        next_idx = (modes.index(current) + 1) % len(modes) if current in modes else 0
        new_mode = modes[next_idx]
        cfg["PAIR_MODE"] = new_mode
        save_roblox_config(cfg)
        
        if new_mode == "pair":
            mode_desc = "Çift Mod (Shirt+Pants)"
        elif new_mode == "single":
            mode_desc = "Tekli Mod (Sadece Shirt/Pants)"
        else:
            mode_desc = "3D UGC Mod (3D Asset İndirme)"
            
        await q.edit_message_text(
            f"👕 *Yükleme Modu*\n\n"
            f"Yeni mod: **{mode_desc}**\n\n"
            f"• *Çift Mod:* Shirt bulduktan sonra eşleşen pants'ı arar ve ikisini birlikte yükler.\n"
            f"• *Tekli Mod:* Sadece seçilen tipteki kıyafetleri bulur ve tek tek yükler.\n"
            f"• *3D UGC Mod:* Aksesuar 3D modellerini (.obj ve texture) indirip .zip olarak verir. Yükleme YAPMAZ.\n\n"
            f"Ayarlar kaydedildi. Ana menüye dönüyorsunuz…",
            reply_markup=settings_keyboard(),
            parse_mode="Markdown"
        )

    # ── Onay callbacks ──
    elif data.startswith("edit_menu_"):
        # edit_menu_[unique_id] — detects current mode and shows the right sub-menu
        unique_id = data[10:]
        cfg = load_roblox_config()
        pair_mode = cfg.get("PAIR_MODE", "pair")

        if pair_mode == "pair":
            # Pair mode: choose Shirt or Pants first
            with _pending_lock:
                meta = _pending_items.get(unique_id, {}).get("metadata", {})
                s_name = meta.get("shirt_name", "")
                p_name = meta.get("pants_name", "")
            kb_buttons = [
                [InlineKeyboardButton(f"👕 Shirt", callback_data=f"edit_sel_s_{unique_id}"),
                 InlineKeyboardButton(f"👖 Pants", callback_data=f"edit_sel_p_{unique_id}")],
                [InlineKeyboardButton("⬅️ Vazgeç", callback_data=f"refresh_{unique_id}")]
            ]
            msg_text = (
                f"✏️ *Düzenleme Menüsü*\n\n"
                f"👕 Shirt Adı: `{md_escape(s_name) or 'Boş'}`\n"
                f"👖 Pants Adı: `{md_escape(p_name) or 'Boş'}`\n\n"
                "Hangi ürünü düzenlemek istiyorsun?"
            )
            kb = InlineKeyboardMarkup(kb_buttons)
            if q.message.caption is not None:
                await q.edit_message_caption(msg_text, reply_markup=kb, parse_mode="Markdown")
            else:
                await q.edit_message_text(msg_text, reply_markup=kb, parse_mode="Markdown")
        else:
            # Single / UGC mode: show Name and Desc buttons directly
            with _pending_lock:
                meta = _pending_items.get(unique_id, {}).get("metadata", {})
                cur_name = meta.get("name", "")
                cur_desc = meta.get("desc", "")
            kb_buttons = [
                [InlineKeyboardButton("✏️ Başlığı Düzenle", callback_data=f"edit_name_{unique_id}")],
                [InlineKeyboardButton("📜 Açıklamayı Düzenle", callback_data=f"edit_desc_{unique_id}")],
                [InlineKeyboardButton("⬅️ Vazgeç", callback_data=f"refresh_{unique_id}")]
            ]
            msg_text = (
                f"✏️ *Düzenleme Menüsü*\n\n"
                f"📌 *Mevcut Başlık:* `{md_escape(cur_name) or 'Boş'}`\n"
                f"📜 *Mevcut Açıklama:* `{md_escape(cur_desc[:80]) + '...' if len(cur_desc) > 80 else md_escape(cur_desc) or 'Boş'}`\n\n"
                "Neyi değiştirmek istersin?"
            )
            kb = InlineKeyboardMarkup(kb_buttons)
            if q.message.caption is not None:
                await q.edit_message_caption(msg_text, reply_markup=kb, parse_mode="Markdown")
            else:
                await q.edit_message_text(msg_text, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("edit_sel_"):
        asset_prefix = "s" if "_sel_s_" in data else "p"
        unique_id = data.replace(f"edit_sel_{asset_prefix}_", "")
        Logger.info(f"DEBUG: edit_sel asset={asset_prefix} unique_id='{unique_id}'")
        
        with _pending_lock:
            meta = _pending_items[unique_id]["metadata"] if unique_id in _pending_items else {}
            if asset_prefix == "s":
                name, desc = meta.get("shirt_name", ""), meta.get("shirt_desc", "")
            else:
                name, desc = meta.get("pants_name", ""), meta.get("pants_desc", "")

        kb_buttons = [
            [InlineKeyboardButton("✏️ Adı Düzenle", callback_data=f"edit_{asset_prefix}_name_{unique_id}"),
             InlineKeyboardButton("📜 Açıklamayı Düzenle", callback_data=f"edit_{asset_prefix}_desc_{unique_id}")],
            [InlineKeyboardButton("⬅️ Geri", callback_data=f"edit_menu_{unique_id}")]
        ]
        
        label = "Shirt" if asset_prefix == "s" else "Pants"
        msg_text = (
            f"✏️ *{label} Düzenleniyor*\n\n"
            f"📌 *Mevcut Ad:* `{md_escape(name) or 'Boş'}`\n"
            f"📜 *Mevcut Açıklama:* `{md_escape(desc[:80]) + '...' if len(desc) > 80 else md_escape(desc) or 'Boş'}`\n\n"
            "Neyi değiştirmek istersin?"
        )
        kb = InlineKeyboardMarkup(kb_buttons)
        if q.message.caption is not None:
            await q.edit_message_caption(msg_text, reply_markup=kb, parse_mode="Markdown")
        else:
            await q.edit_message_text(msg_text, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("refresh_"):
        unique_id = data.replace("refresh_", "")
        event = _pending_events.get(unique_id)
        if event:
            _pending_status[unique_id] = "edit"
            event.set()
            await q.answer("Geri dönülüyor...")

    elif data.startswith("edit_") and not data.startswith("edit_menu_") and not data.startswith("edit_sel_"):
        # Formats:
        #   Pair mode:   edit_s_name_{unique_id}  /  edit_s_desc_...  /  edit_p_name_...  /  edit_p_desc_...
        #   Single mode: edit_{unique_id}  (direct, no sub-menu)
        # We detect the kind by checking known prefixes AFTER 'edit_'
        rest = data[5:]  # strip 'edit_'

        KIND_PREFIXES = [
            ("s_name_", "s_name"),
            ("s_desc_", "s_desc"),
            ("p_name_", "p_name"),
            ("p_desc_", "p_desc"),
            ("name_",   "name"),
            ("desc_",   "desc"),
        ]
        kind = None
        unique_id = None
        for prefix, k in KIND_PREFIXES:
            if rest.startswith(prefix):
                kind = k
                unique_id = rest[len(prefix):]
                break
        if kind is None:
            # Single mode: no sub-kind, rest IS the unique_id
            kind = "name"
            unique_id = rest



        with _pending_lock:
            item = _pending_items.get(unique_id, {})
            meta = item.get("metadata", {})
            META_KEY_MAP = {
                "s_name": "shirt_name", "s_desc": "shirt_desc",
                "p_name": "pants_name", "p_desc": "pants_desc",
                "name":   "name",       "desc":   "desc"
            }
            current_val = meta.get(META_KEY_MAP.get(kind, kind), "")

        ctx.user_data["awaiting"] = f"edit_{kind}_{unique_id}"
        await q.answer("Düzenleme başlatıldı...")

        PROMPTS = {
            "s_name": "👕 Yeni Shirt Adını yazın:",
            "s_desc": "📜 Yeni Shirt Açıklamasını yazın:",
            "p_name": "👖 Yeni Pants Adını yazın:",
            "p_desc": "📜 Yeni Pants Açıklamasını yazın:",
            "name":   "✏️ Yeni ürün adını yazın:",
            "desc":   "📜 Yeni ürün açıklamasını yazın:",
        }
        await q.message.reply_text(
            f"✏️ *Mevcut Değer:*\n`{md_escape(current_val) if current_val else 'Boş'}`\n\n"
            f"{PROMPTS.get(kind, 'Lütfen yeni değeri yazın:')}",
            parse_mode="Markdown"
        )

    elif data.startswith("back_"):
        unique_id = data[5:]  # strip 'back_'
        event = None
        with _pending_lock:
            if unique_id in _pending_items:
                _pending_status[unique_id] = "back"
                event = _pending_events.get(unique_id)

        if event:
            event.set()
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.answer("⬅️ Geri dönülüyor...")
        else:
            await q.answer("⚠️ Geri dönecek ürün bulunamadı.", show_alert=True)

    elif data.startswith("approve_") or data.startswith("reject_") or data.startswith("skip_") or data.startswith("stop_job_"):
        # Parse action and unique_id
        if data.startswith("stop_job_"):
            action = "stop"
            unique_id = data[9:]  # strip 'stop_job_'
        else:
            idx = data.index("_")
            action = data[:idx]  # 'approve', 'reject', 'skip'
            unique_id = data[idx+1:]

        event = None
        with _pending_lock:
            if unique_id in _pending_events:
                event = _pending_events[unique_id]
                _pending_status[unique_id] = action

        if event:
            event.set()
            # Delete the preview message to keep chat clean
            try:
                await q.message.delete()
            except Exception:
                # If delete fails, just remove the keyboard
                try:
                    await q.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
            # Confirm to user via answer popup
            ACTION_LABELS = {
                "approve": "✅ Onaylandı, yükleniyor...",
                "stop":    "🛑 İşlem durduruluyor...",
                "skip":    "🔍 Sıradaki aranayıyor...",
                "reject":  "❌ Reddedildi.",
            }
            await q.answer(ACTION_LABELS.get(action, "..."))
        else:
            await q.answer("⚠️ Ürün bulunamadı ya da süre doldu.", show_alert=True)

    # ── İş Başlat ──
    elif data == "run":
        if _job_info["status"] == "running":
            await q.edit_message_text("⚠️ Zaten bir iş çalışıyor. Önce /stop ile durdur.", reply_markup=back_keyboard(), parse_mode="Markdown")
            return
            
        cfg = load_roblox_config()
        if cfg.get("PAIR_MODE", "pair") == "ugc":
            kb = [
                [InlineKeyboardButton("🎩  Hair (Saç)", callback_data="ugc_cat_41"), InlineKeyboardButton("🧢  Hat (Şapka)", callback_data="ugc_cat_8")],
                [InlineKeyboardButton("😎  Face (Yüz)", callback_data="ugc_cat_42"), InlineKeyboardButton("🧣  Neck (Boyun)", callback_data="ugc_cat_43")],
                [InlineKeyboardButton("💪  Shoulder (Omuz)", callback_data="ugc_cat_44"), InlineKeyboardButton("👕  Front (Ön)", callback_data="ugc_cat_45")],
                [InlineKeyboardButton("🎒  Back (Sırt)", callback_data="ugc_cat_46"), InlineKeyboardButton("👖  Waist (Bel)", callback_data="ugc_cat_47")],
                [InlineKeyboardButton("⬅️  İptal", callback_data="main")]
            ]
            await q.edit_message_text("📦 *3D UGC İndirme Aktif*\n\nAramak istediğin aksesuar kategorisini seç:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            ctx.user_data["awaiting"] = "keyword"
            await q.edit_message_text(
                "🚀 *İş Başlat*\n\n"
                "Aramak istediğin keyword(ler)i yaz:\n\n"
                "📌 *Tek keyword:* `spiderman`\n"
                "📌 *Çoklu:* `naruto, batman, goku`\n\n"
                "Anime, oyun, sporcu… ne olursa yaz:",
                reply_markup=back_keyboard(), parse_mode="Markdown"
            )

    elif data.startswith("ugc_cat_"):
        cat_id = int(data.split("_")[2])
        ctx.user_data["ugc_category"] = cat_id
        ctx.user_data["awaiting"] = "keyword"
        
        cat_names = {8: "Hat (Şapka)", 41: "Hair (Saç)", 42: "Face (Yüz)", 43: "Neck (Boyun)", 44: "Shoulder (Omuz)", 45: "Front (Ön)", 46: "Back (Sırt)", 47: "Waist (Bel)"}
        c_name = cat_names.get(cat_id, "Bilinmeyen")
        
        await q.edit_message_text(
            f"📦 *Kategori Seçildi:* {c_name}\n\n"
            "Aramak istediğin keyword(ler)i yaz (Örn: `spiderman` veya `naruto, anime`):",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )

    # ── Yardım Menüsü ──
    elif data == "help":
        await q.edit_message_text(
            "❓ *Yardım Merkezi*\n\nHangi konuda yardım istiyorsun?",
            reply_markup=help_keyboard(), parse_mode="Markdown"
        )

    elif data == "help_run":
        await q.edit_message_text(
            "🚀 *İş Başlatma*\n\n"
            "1. Ana menüden *İş Başlat*'a bas\n"
            "2. Arama kelimesini yaz (örn: `spiderman`)\n"
            "3. Bot otomatik olarak:\n"
            "   • Kıyafetleri Roblox'ta arar\n"
            "   • Eşleşen shirt+pants çiftlerini bulur\n"
            "   • Tasarım şablonu ekler\n"
            "   • Grubuna yükler ve satışa koyar\n"
            "   • Shirt'in açıklamasına pantolon linkini, pantolonun açıklamasına da shirt linkini ekler\n\n"
            "🎯 *Hedef çift sayısını* /pairs ile değiştirebilirsin.",
            reply_markup=help_keyboard(), parse_mode="Markdown"
        )

    elif data == "help_settings":
        cfg = load_roblox_config()
        pair_mode = cfg.get("PAIR_MODE", "pair")
        target_label = "çift" if pair_mode == "pair" else "item"
        target_desc = "shirt+pants çift" if pair_mode == "pair" else "shirt item"
        await q.edit_message_text(
            "⚙️ *Ayarlar Hakkında*\n\n"
            f"💰 *Fiyat* (`{cfg['PRICE']}` Robux) — Kıyafetlerin satış fiyatı\n\n"
            f"🏷 *Grup ID* (`{cfg['GROUP_ID'] or 'Ayarlanmadı'}`) — Kıyafetlerin yükleneceği Roblox grubu\n\n"
            f"🎯 *Hedef {target_label.title()}* (`{TARGET_PAIRS}`) — Her keyword için kaç {target_desc} indirilsin\n\n"
            f"⏰ *Gecikme* `{cfg['DELAY_MIN']}`–`{cfg['DELAY_MAX']}` sn — Yüklemeler arası bekleme süresi _(anti-ban için)_\n\n"
            "Ayarları değiştirmek için *Ayarlar* menüsüne git.",
            reply_markup=help_keyboard(), parse_mode="Markdown"
        )

    elif data == "help_status":
        await q.edit_message_text(
            "📊 *Durum & Durdur*\n\n"
            "• *Durum* butonu çalışan işin ilerlemesini gösterir:\n"
            "  – Kaç çift bulundu\n"
            "  – Kaç item yüklendi\n\n"
            "• *Durdur* butonu çalışan işe sinyal gönderir. "
            "Mevcut adım (indirme/yükleme) bittikten sonra iş durur.\n\n"
            "✅ *İş bittikten sonra* özet mesajı gelir.",
            reply_markup=help_keyboard(), parse_mode="Markdown"
        )

    elif data == "help_cookie":
        await q.edit_message_text(
            "🔑 *Cookie Hakkında*\n\n"
            "Cookie, Roblox hesabına giriş yapmak için kullanılan oturum token'ı.\n\n"
            "📌 *Nasıl alınır?*\n"
            "1. Roblox'a giriş yap\n"
            "2. Tarayıcıda `F12` → `Application` sekmesi\n"
            "3. `Cookies` → `.ROBLOSECURITY` değerini kopyala\n"
            "4. Bu bottan Ayarlar → Cookie'ye yapıştır\n\n"
            "🕐 *Ne zaman yenilemem lazım?*\n"
            "Sabit bir süre yok. Cookie şu durumlarda düşer:\n"
            "• Şifre değiştirdiğinde\n"
            "• \"Tüm cihazlardan çıkış\" yaptığında\n"
            "• Roblox uzun süre kullanılmayınca oturumu sonlandırırsa\n"
            "• Bot \"indirilemedi\" / 401 hatası verince\n\n"
            "Yani sadece _hata aldığında_ veya güvenlik işlemi yaptığında yenilemen yeterli.",
            reply_markup=help_keyboard(), parse_mode="Markdown"
        )

# ─── Metin mesajı handler ────────────────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    awaiting = ctx.user_data.get("awaiting")
    text     = update.message.text.strip()
    cfg      = load_roblox_config()

    if awaiting == "keyword":
        ctx.user_data["awaiting"] = None
        if _job_info["status"] == "running":
            await update.message.reply_text("⚠️ Zaten bir iş çalışıyor.", reply_markup=main_menu_keyboard())
            return
        keyword_list = [k.strip() for k in text.split(",") if k.strip()]
        await start_job(update, ctx, keyword_list)

    elif awaiting == "price":
        ctx.user_data["awaiting"] = None
        try:
            price = int(text)
            if price < 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Geçersiz fiyat. Tekrar dene.", reply_markup=settings_keyboard())
            return
        cfg = load_roblox_config()
        cfg["PRICE"] = price
        save_roblox_config(cfg)
        await update.message.reply_text(f"✅ Fiyat `{price}` Robux olarak ayarlandı.", reply_markup=settings_keyboard(), parse_mode="Markdown")

    elif awaiting and awaiting.startswith("edit_"):
        # awaiting format: edit_{kind}_{unique_id}
        # kind can be: s_name, s_desc, p_name, p_desc, name, desc
        # We extract kind by matching known multi-part prefixes first
        rest = awaiting[5:]  # strip 'edit_'
        KIND_PREFIXES = [
            ("s_name_", "s_name"),
            ("s_desc_", "s_desc"),
            ("p_name_", "p_name"),
            ("p_desc_", "p_desc"),
            ("name_",   "name"),
            ("desc_",   "desc"),
        ]
        kind = None
        unique_id = None
        for prefix, k in KIND_PREFIXES:
            if rest.startswith(prefix):
                kind = k
                unique_id = rest[len(prefix):]
                break
        if kind is None:
            kind = "name"
            unique_id = rest

        ctx.user_data["awaiting"] = None

        META_KEY_MAP = {
            "s_name": "shirt_name", "s_desc": "shirt_desc",
            "p_name": "pants_name", "p_desc": "pants_desc",
            "name": "name",         "desc": "desc"
        }
        meta_key = META_KEY_MAP.get(kind, kind)

        with _pending_lock:
            # Exact match first, then partial
            found_id = unique_id if unique_id in _pending_items else None
            if not found_id:
                for k in _pending_items.keys():
                    if unique_id in k or k in unique_id:
                        found_id = k; break

            if found_id:
                _pending_items[found_id]["metadata"][meta_key] = text
                _pending_status[found_id] = "edit"
                event = _pending_events.get(found_id)
                if event: event.set()
        # ── await calls OUTSIDE the lock (threading.Lock blocks event loop if awaited inside) ──
        if found_id:
            await update.message.reply_text(
                f"✅ *{meta_key}* güncellendi. Önizleme yenileniyor...",
                reply_markup=main_menu_keyboard(), parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ Ürün bulunamadı veya oturum süresi doldu.",
                reply_markup=main_menu_keyboard()
            )

    elif awaiting == "pairs":
        ctx.user_data["awaiting"] = None
        global TARGET_PAIRS
        try:
            n = int(text)
            if not 1 <= n <= 30: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ 1–30 arasında bir sayı gir.", reply_markup=settings_keyboard())
            return
        TARGET_PAIRS = n
        cfg = load_roblox_config()
        cfg["TARGET_PAIRS"] = n
        save_roblox_config(cfg)
        Logger.success(f"Hedef sayısı Firebase'e kaydedildi: {n}")
        await update.message.reply_text(f"✅ Her keyword için `{TARGET_PAIRS}` çift indirilecek.\n(Ayarlar Firebase'e kaydedildi: {n})", reply_markup=settings_keyboard(), parse_mode="Markdown")

    elif awaiting == "cookie":
        ctx.user_data["awaiting"] = None
        cookie_val = text.strip()
        if not cookie_val.startswith("_|WARNING:-DO-NOT-SHARE-THIS."):
            await update.message.reply_text("⚠️ *Uyarı:* Girdiğin değer normal bir Roblox Cookie'sine benzemiyor.", parse_mode="Markdown")
        
        db_manager.save_cookie(cookie_val)
        with open("cookie.txt", "w", encoding="utf-8") as f:
            f.write(cookie_val)
        await update.message.reply_text("✅ *Cookie başarıyla kaydedildi!*\n(Bulut veritabanlarına da işlendi)", reply_markup=settings_keyboard(), parse_mode="Markdown")

    elif awaiting == "sort":
        ctx.user_data["awaiting"] = None
        choice = text
        sort_map = {
            "1": (2, 5),  # Best Selling, All Time
            "2": (2, 3),  # Best Selling, Past Week
            "3": (2, 1),  # Best Selling, Past Day
            "4": (1, 5),  # Most Favorited, All Time
            "5": (4, 5),  # Price Asc
            "6": (5, 5),  # Price Desc
            "7": (0, 5),  # Relevance
        }
        if choice not in sort_map:
            await update.message.reply_text("❌ Geçersiz seçim. 1–7 arasında bir numara yaz.", reply_markup=settings_keyboard(), parse_mode="Markdown")
            return

        sort_type, sort_agg = sort_map[choice]
        cfg = load_roblox_config()
        cfg["SORT_TYPE"] = sort_type
        cfg["SORT_AGG"]  = sort_agg
        save_roblox_config(cfg)

        await update.message.reply_text("✅ Sıralama tercihin kaydedildi. Bir sonraki aramada bu sıraya göre aranacak.", reply_markup=settings_keyboard(), parse_mode="Markdown")

    elif awaiting == "model3d_prompt":
        ctx.user_data["awaiting"] = None
        prompt = text
        status_msg = await update.message.reply_text(
            f"⏳ *3D Model üretiliyor...*\n\n"
            f"📝 Prompt: `{md_escape(prompt)}`\n\n"
            f"1️⃣ AI görsel oluşturuluyor...\n"
            f"_Bu işlem 2-5 dakika sürebilir. Hazır olduğunda GLB dosyasını göndereceğim._",
            parse_mode="Markdown"
        )
        try:
            from scrapers.model3d_engine import Model3DEngine
            engine = Model3DEngine()
            glb_path = await asyncio.to_thread(engine.text_to_3d_sync, prompt)

            await status_msg.edit_text(
                f"✅ *3D Model hazır!*\n\n"
                f"📝 Prompt: `{md_escape(prompt)}`\n\n"
                f"👇 GLB dosyası aşağıda:",
                parse_mode="Markdown"
            )
            filename = os.path.basename(glb_path)
            with open(glb_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"🎲 3D Model: `{md_escape(prompt)}`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎲 Yeni Model", callback_data="model3d_menu"),
                         InlineKeyboardButton("🏠 Ana Menü", callback_data="main")]
                    ])
                )
            try:
                os.remove(glb_path)
            except Exception:
                pass
        except Exception as e:
            Logger.error(f"3D Model hatası: {e}")
            err_str = str(e)
            if "ZeroGPU quotas" in err_str:
                err_text = (
                    "❌ *Hugging Face ZeroGPU Limitine Takıldınız!*\n\n"
                    "Bu servisi çok fazla kullanan anonim kullanıcılardan biri olduğunuz için geçici sınırlandırmaya girdiniz.\n\n"
                    "🛠️ *Nasıl Çözülür?*\n"
                    "1. [huggingface.co](https://huggingface.co) adresinden ücretsiz üye olun\n"
                    "2. Ayarlardan bir 'Access Token' (Read/Write) alın\n"
                    "3. `bot_config.txt` dosyanıza `HF_TOKEN=hf_...` satırını ekleyin\n"
                    "4. Botu yeniden başlatın."
                )
            else:
                err_text = (
                    f"❌ *3D Model üretimi başarısız.*\n\n"
                    f"Hata: `{err_str[:200].replace('`', '')}`\n\n"
                    f"TRELLIS Space meşgul olabilir, biraz sonra tekrar dene."
                )
            await status_msg.edit_text(
                err_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="model3d_text"),
                     InlineKeyboardButton("🏠 Ana Menü", callback_data="main")]
                ]),
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

    else:
        await update.message.reply_text("Ana menü:", reply_markup=main_menu_keyboard())

# ─── Job launcher ─────────────────────────────────────────────────────────────
async def start_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE, keyword_list: list):
    global _active_task
    cfg    = load_roblox_config()
    cookie = load_cookie()
    
    ugc_cat = ctx.user_data.get("ugc_category")

    target_label = "çift" if cfg.get('PAIR_MODE', 'pair') == 'pair' else "item"
    if cfg.get('PAIR_MODE') == 'ugc': target_label = "3D asset"
    
    start_msg = await update.effective_message.reply_text(
        f"🚀 *İş Başladı!*\n\n"
        f"🔍 Keyword(ler): `{'`, `'.join(keyword_list)}`\n"
        f"🎯 Hedef {target_label}: `{TARGET_PAIRS}` / keyword\n\n"
        f"⚙️ Hazırlanıyor, lütfen bekle…",
        parse_mode="Markdown"
    )
    # Store the message so job_task can delete it when first status arrives
    ctx.user_data["last_status_msg_id"] = start_msg.message_id

    _job_stop.clear()
    _active_task = asyncio.create_task(job_task(update, ctx, keyword_list, cfg, cookie, ugc_cat))

# ─── Background job (Async Task) ──────────────────────────────────────────────
async def job_task(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword_list, cfg, cookie, ugc_cat=None):
    # Rolling status message — deletes previous before sending new one
    _last_status_msg = [None]  # list so inner function can mutate it

    async def send(msg, **kwargs):
        try:
            # Delete previous status message if it exists
            if _last_status_msg[0] is not None:
                try:
                    await _last_status_msg[0].delete()
                except Exception:
                    pass
                _last_status_msg[0] = None
            # Also delete the start_job message on first send
            prev_id = context.user_data.pop("last_status_msg_id", None)
            if prev_id:
                try:
                    await update.get_bot().delete_message(update.effective_chat.id, prev_id)
                except Exception:
                    pass
            sent = await update.effective_message.reply_text(msg, parse_mode="Markdown", **kwargs)
            _last_status_msg[0] = sent
            return sent
        except Exception as e:
            Logger.error(f"Mesaj gönderme hatası: {e}")

    try:
        global _job_info
        _job_info.update({"status": "running", "keywords": keyword_list, "pairs_done": 0, "uploads": 0})

        sort_type = cfg.get("SORT_TYPE", 2)
        sort_agg  = cfg.get("SORT_AGG", 5)

        roblox     = RobloxScraper(cookie=cookie, sort_type=sort_type, sort_agg=sort_agg)
        downloader = AssetDownloader()
        designer   = TemplateDesigner()

        group_id = cfg.get("GROUP_ID", 0)
        uploader = None
        if cookie and group_id:
            uploader = AssetUploader(
                cookie=cookie, group_id=group_id, price=cfg["PRICE"],
                delay_min=cfg["DELAY_MIN"], delay_max=cfg["DELAY_MAX"],
                max_uploads=cfg["MAX_UPLOADS_PER_SESSION"],
            )
        else:
            if not group_id:
                await send("⚠️ Grup ID ayarlanmadı — sadece indirme yapılacak.\n_Ayarlamak için: ⚙️ Ayarlar → Grup ID_")

        upload_count = 0
        require_approval = cfg.get("REQUIRE_APPROVAL", 0) == 1
        pair_mode = cfg.get("PAIR_MODE", "pair")
        target_pairs = cfg.get("TARGET_PAIRS", 5)

        for keyword in keyword_list:
            if _job_stop.is_set(): break
            await send(
                f"🔍 *{keyword.title()}* için arama başlatıldı…\n\n"
                f"• 🎯 Hedef {'çift' if pair_mode == 'pair' else 'item'} sayısı: `{target_pairs}`\n"
                f"⏳ Sonuçlar bekleniyor..."
            )
            items_found = 0

            if pair_mode == "pair":
                pants_pool = await roblox.search_and_get_assets(keyword, limit=40, asset_type=12)
                used_pants_ids = set()

                async for asset_id, item_url, creator, current_item_name in roblox.search_and_yield_assets(keyword):
                    if _job_stop.is_set() or items_found >= target_pairs: break
                    
                    import re
                    s_clean = re.sub(r'shirt', '', current_item_name, flags=re.IGNORECASE).strip().lower()
                    pants_id = None
                    for p_id, p_url, p_creator, p_name in (pants_pool or []):
                        p_clean = re.sub(r'pants|pant', '', p_name, flags=re.IGNORECASE).strip().lower()
                        if creator == p_creator and (s_clean in p_clean or p_clean in s_clean):
                            pants_id = p_id; break
                    
                    if not pants_id:
                        try:
                            paired_pants = await roblox.get_paired_pants(asset_id, keyword)
                            if paired_pants:
                                pants_id, _ = paired_pants[0]
                        except Exception: pass
                    
                    if not pants_id or pants_id in used_pants_ids: continue
                    used_pants_ids.add(pants_id)
                    
                    # ── Duplicate Check ──
                    is_duplicate = db_manager.is_item_uploaded(asset_id) or db_manager.is_item_uploaded(pants_id)
                    if is_duplicate:
                        Logger.warn(f"Bu çift ({asset_id}/{pants_id}) daha önce yüklendi! Kullanıcıya sorulacak.")

                    items_found += 1
                    _job_info["pairs_done"] = items_found
                    await send(f"✅ *{md_escape(keyword.title())}* için {items_found}. çift bulundu!")

                    shirt_path = await download_and_design(asset_id, keyword, "shirt", downloader, designer)
                    pants_path = await download_and_design(pants_id, keyword, "pants", downloader, designer)
                    if not shirt_path or not pants_path:
                        items_found -= 1
                        _job_info["pairs_done"] = items_found
                        continue

                    shirt_name, shirt_desc = generate_metadata(keyword, "shirt")
                    pants_name, pants_desc = generate_metadata(keyword, "pants")
                    
                    do_upload = True
                    if require_approval:
                        unique_id = f"{asset_id}_pair"
                        event = asyncio.Event()
                        _meta = {
                            "shirt_name": shirt_name, "shirt_desc": shirt_desc,
                            "pants_name": pants_name, "pants_desc": pants_desc
                        }
                        with _pending_lock:
                            _pending_events[unique_id] = event
                            _pending_items[unique_id] = {
                                "shirt_path": shirt_path, "pants_path": pants_path, 
                                "shirt_id": asset_id, "pants_id": pants_id,
                                "metadata": _meta,
                                "history": context.user_data.get(f"last_pair_{keyword}")
                            }
                        
                        # Preview Images
                        from telegram import InputMediaPhoto
                        try:
                            with open(shirt_path, "rb") as s_img, open(pants_path, "rb") as p_img:
                                await update.effective_message.reply_media_group([
                                    InputMediaPhoto(s_img, caption=f"👕 *Shirt*"),
                                    InputMediaPhoto(p_img, caption=f"👖 *Pants*")
                                ])
                        except Exception as e:
                            Logger.error(f"Önizleme hatası: {e}")

                        preview_msg = None
                        while not _job_stop.is_set():
                            with _pending_lock:
                                m = _pending_items[unique_id]["metadata"]
                                has_hist = bool(_pending_items[unique_id]["history"] or context.user_data.get(f"last_pair_{keyword}"))

                            dup_warn = "⚠️ *DİKKAT: Bu çift daha önce yüklendi!*\n\n" if is_duplicate else ""
                            caption = (
                                f"{dup_warn}⏳ *{items_found}. Çift Onay Bekliyor*\n\n"
                                f"👕 S: `{md_escape(m['shirt_name'])}`\n"
                                f"👖 P: `{md_escape(m['pants_name'])}`\n\n"
                                f"📜 *Shirt Açıklama:*\n`{md_escape(m['shirt_desc'])}`\n\n"
                                f"📜 *Pants Açıklama:*\n`{md_escape(m['pants_desc'])}`\n\n"
                                f"Yüklensin mi?"
                            )
                            kb_buttons = [
                                [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}"),
                                 InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}")],
                                [InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}")],
                                [InlineKeyboardButton("✏️ Düzenle", callback_data=f"edit_menu_{unique_id}")]
                            ]
                            if has_hist:
                                kb_buttons.append([InlineKeyboardButton("⬅️ Geri Dön (Set)", callback_data=f"back_{unique_id}")])
                            
                            kb_buttons.append([InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")])
                            
                            kb = InlineKeyboardMarkup(kb_buttons)

                            if not preview_msg:
                                preview_msg = await send(caption, reply_markup=kb)
                            else:
                                try: await preview_msg.edit_text(caption, reply_markup=kb, parse_mode="Markdown")
                                except: pass

                            try:
                                await asyncio.wait_for(event.wait(), timeout=600)
                                with _pending_lock:
                                    status = _pending_status.pop(unique_id, "skip")
                                    event.clear()
                                
                                if status == "edit": continue
                                elif status == "back":
                                    with _pending_lock: prev = _pending_items[unique_id].get("history")
                                    if prev:
                                        curr_data = {
                                            "shirt_path": shirt_path, "pants_path": pants_path, 
                                            "shirt_id": asset_id, "pants_id": pants_id, "metadata": _pending_items[unique_id]["metadata"]
                                        }
                                        asset_id, pants_id = prev["shirt_id"], prev["pants_id"]
                                        shirt_path, pants_path = prev["shirt_path"], prev["pants_path"]
                                        with _pending_lock:
                                            _pending_items[unique_id].update({
                                                "shirt_id": asset_id, "pants_id": pants_id,
                                                "shirt_path": shirt_path, "pants_path": pants_path,
                                                "metadata": prev["metadata"], "history": curr_data
                                            })
                                        await send("⬅️ *Önceki çift geri yüklendi.*")
                                        # Reset preview_msg so it re-sends photos
                                        preview_msg = None
                                        
                                        # Re-send media group
                                        try:
                                            with open(shirt_path, "rb") as s_img, open(pants_path, "rb") as p_img:
                                                await update.effective_message.reply_media_group([
                                                    InputMediaPhoto(s_img, caption=f"👕 *Shirt* (Geri Yüklendi)"),
                                                    InputMediaPhoto(p_img, caption=f"👖 *Pants* (Geri Yüklendi)")
                                                ])
                                        except Exception as e:
                                            Logger.error(f"Geri yükleme görsel hatası: {e}")
                                        continue
                                    else:
                                        await send("⚠️ Geri dönecek ürün bulunamadı."); continue
                                elif status == "approve":
                                    with _pending_lock:
                                        context.user_data[f"last_pair_{keyword}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    do_upload = True; break
                                elif status == "stop":
                                    with _pending_lock: _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    _job_stop.set(); do_upload = False; break
                                elif status == "skip":
                                    with _pending_lock:
                                        context.user_data[f"last_pair_{keyword}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    items_found -= 1; do_upload = False; break
                                else: # reject
                                    with _pending_lock:
                                        context.user_data[f"last_pair_{keyword}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    do_upload = False; break
                            except asyncio.TimeoutError:
                                with _pending_lock: _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                items_found -= 1; do_upload = False; break
                        
                        if not do_upload: continue

                    if do_upload and uploader:
                        await send("☁️ Yükleniyor…")
                        upload_count = await upload_pair_with_crosslink(asset_id, shirt_path, pants_id, pants_path, keyword, uploader, upload_count, cfg)
                        _job_info["uploads"] = upload_count

            elif pair_mode == "single":
                single_type = cfg.get("SINGLE_TYPE", 11)
                type_name = "shirt" if single_type == 11 else "pants"
                async for asset_id, item_url, creator, current_item_name in roblox.search_and_yield_assets(keyword, asset_type=single_type):
                    if _job_stop.is_set() or items_found >= target_pairs: break
                    
                    is_duplicate = db_manager.is_item_uploaded(asset_id)
                    items_found += 1
                    _job_info["pairs_done"] = items_found
                    
                    await send(f"✅ *{md_escape(keyword.title())}* için {items_found}. {type_name} bulundu!")
                    out_path = await download_and_design(asset_id, keyword, type_name, downloader, designer)
                    if not out_path:
                        items_found -= 1
                        _job_info["pairs_done"] = items_found
                        continue

                    name, desc = generate_metadata(keyword, type_name, use_suffix=False)
                    
                    do_upload = True
                    if require_approval:
                        unique_id = f"{asset_id}_{single_type}"
                        event = asyncio.Event()
                        
                        _meta = {"name": name, "desc": desc}
                        with _pending_lock:
                            _pending_events[unique_id] = event
                            _pending_items[unique_id] = {
                                "path": out_path, "asset_id": asset_id, "type": type_name,
                                "metadata": _meta,
                                "history": context.user_data.get(f"last_item_{keyword}_{single_type}")
                            }
                        
                        # Send initial preview
                        dup_warn = "⚠️ *DİKKAT: Bu ürün daha önce yüklendi!*\n\n" if is_duplicate else ""
                        caption = (
                            f"{dup_warn}⏳ *{items_found}. {type_name.title()} Onay Bekliyor*\n\n"
                            f"📝 Ad: `{md_escape(_meta['name'])}`\n"
                            f"📜 Açıklama: `{md_escape(_meta['desc'])}`\n\n"
                            f"Yüklensin mi?"
                        )
                        
                        preview_msg = None
                        try:
                            with open(out_path, "rb") as f_img:
                                preview_msg = await update.effective_message.reply_photo(
                                    photo=f_img, caption=caption, 
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}"),
                                         InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}")],
                                        [InlineKeyboardButton("✏️ Düzenle", callback_data=f"edit_menu_{unique_id}")] +
                                        ([InlineKeyboardButton("⬅️ Geri Dön", callback_data=f"back_{unique_id}")] if _pending_items[unique_id]["history"] else []),
                                        [InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}"),
                                         InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                                    ]),
                                    parse_mode="Markdown"
                                )
                        except Exception as e:
                            preview_msg = await send(f"⚠️ Önizleme hatası: {e}\n\n{caption}", reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}"),
                                 InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}")],
                                [InlineKeyboardButton("✏️ Düzenle", callback_data=f"edit_menu_{unique_id}")],
                                [InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}"),
                                 InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                            ]))

                        while not _job_stop.is_set():
                            try:
                                Logger.info(f"⏳ Waiting for approval event: {unique_id}")
                                await asyncio.wait_for(event.wait(), timeout=360)
                                with _pending_lock:
                                    status = _pending_status.pop(unique_id, "skip")
                                    event.clear()
                                Logger.info(f"🛎 Status received: {status} for {unique_id}")

                                if status == "edit" or status == "back":
                                    if status == "back":
                                        with _pending_lock:
                                            prev = _pending_items[unique_id].get("history")
                                        if prev:
                                            curr_data = {"path": out_path, "asset_id": asset_id, "metadata": _pending_items[unique_id]["metadata"]}
                                            # Restore previous
                                            asset_id, out_path = prev["asset_id"], prev["path"]
                                            with _pending_lock:
                                                _pending_items[unique_id].update({
                                                    "asset_id": asset_id, "path": out_path, 
                                                    "metadata": prev["metadata"], "history": curr_data
                                                })
                                            await send("⬅️ *Önceki ürün geri yüklendi.*")
                                        else:
                                            await send("⚠️ Geri dönecek ürün bulunamadı."); continue
                                    
                                    # Update UI
                                    with _pending_lock:
                                        m = _pending_items[unique_id]["metadata"]
                                        has_hist = bool(_pending_items[unique_id].get("history") or context.user_data.get(f"last_item_{keyword}_{single_type}"))
                                    
                                    caption = (
                                        f"{dup_warn}⏳ *{items_found}. {type_name.title()} Onay Bekliyor*\n\n"
                                        f"📝 Ad: `{md_escape(m['name'])}`\n"
                                        f"📜 Açıklama: `{md_escape(m['desc'])}`\n\n"
                                        f"Yüklensin mi?"
                                    )
                                    kb = InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}"),
                                         InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}")],
                                        [InlineKeyboardButton("✏️ Düzenle", callback_data=f"edit_{unique_id}")] +
                                        ([InlineKeyboardButton("⬅️ Geri Dön", callback_data=f"back_{unique_id}")] if has_hist else []),
                                        [InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}"),
                                         InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                                    ])
                                    
                                    try:
                                        if status == "back" and preview_msg: # If item changed, edit media
                                            from telegram import InputMediaPhoto
                                            with open(out_path, "rb") as f_img:
                                                await preview_msg.edit_media(InputMediaPhoto(f_img, caption=caption, parse_mode="Markdown"), reply_markup=kb)
                                        elif preview_msg:
                                            await preview_msg.edit_caption(caption, reply_markup=kb, parse_mode="Markdown")
                                    except Exception as e:
                                        Logger.error(f"UI Update error: {e}")
                                    continue


                                elif status == "approve":
                                    with _pending_lock:
                                        context.user_data[f"last_item_{keyword}_{single_type}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    do_upload = True; break
                                elif status == "stop":
                                    with _pending_lock: _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    _job_stop.set(); do_upload = False; break
                                elif status == "skip":
                                    with _pending_lock:
                                        context.user_data[f"last_item_{keyword}_{single_type}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    items_found -= 1; do_upload = False; break
                                else: # reject
                                    with _pending_lock:
                                        context.user_data[f"last_item_{keyword}_{single_type}"] = _pending_items[unique_id]
                                        _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                    do_upload = False; break
                            except asyncio.TimeoutError:
                                with _pending_lock: _pending_items.pop(unique_id, None); _pending_events.pop(unique_id, None)
                                items_found -= 1; do_upload = False; break
                        
                        if not do_upload: continue

                    if do_upload and uploader:
                        await send("☁️ Yükleniyor…")
                        upload_count = await upload_single_asset(asset_id, out_path, keyword, uploader, upload_count, cfg, item_type=single_type)
                        _job_info["uploads"] = upload_count
                        
            elif pair_mode == "ugc":
                if not ugc_cat:
                    await send("❌ Hata: UGC kategorisi seçilmemiş.")
                    break
                
                cat_names = {8: "Hat", 41: "Hair", 42: "Face", 43: "Neck", 44: "Shoulder", 45: "Front", 46: "Back", 47: "Waist"}
                c_name = cat_names.get(ugc_cat, "UGC")
                    
                async for asset_id, item_url, creator, current_item_name in roblox.search_and_yield_assets(keyword, asset_type=ugc_cat):
                    if _job_stop.is_set() or items_found >= target_pairs: break
                    
                    items_found += 1
                    _job_info["pairs_done"] = items_found
                    safe_name = md_escape(current_item_name)
                    await send(f"⏳ *{md_escape(keyword.title())}* için {items_found}. 3D Asset Hazırlanıyor: `{safe_name}`...")
                    
                    zip_path = await downloader.download_ugc_asset(asset_id, keyword, c_name)
                    if not zip_path: 
                        items_found -= 1
                        _job_info["pairs_done"] = items_found
                        await send(f"❌ *{md_escape(current_item_name)}* içeriği indirilemedi. Geçiliyor...")
                        continue

                    # İndirilen mesh/texture üzerinde sunucu tarafı dönüşüm (Blender yok; bkz. ugc_mesh_processor)
                    try:
                        processed_zip = await asyncio.to_thread(process_ugc_catalog_zip, zip_path, keyword)
                        if processed_zip:
                            zip_path = processed_zip
                    except Exception as proc_err:
                        Logger.warn(f"UGC mesh işleme atlandı: {proc_err}")

                    ugc_pack_label = (
                        "işlenmiş paket (original + processed)"
                        if "_processed" in os.path.basename(zip_path)
                        else "ham indirme"
                    )
                    
                    thumb_url = await roblox.get_thumbnail(asset_id)
                    
                    if require_approval:
                        # ── Approval flow for UGC ──
                        unique_id = f"{asset_id}_ugc"
                        event = asyncio.Event()
                        with _pending_lock:
                            _pending_events[unique_id] = event
                            _pending_items[unique_id] = {"zip_path": zip_path, "asset_id": asset_id, "name": current_item_name, "url": item_url}
                        
                        approval_kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}")],
                            [InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}"),
                             InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}")],
                            [InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                        ])
                        
                        try:
                            if thumb_url:
                                await update.effective_message.reply_photo(
                                    photo=thumb_url,
                                    caption=(
                                        f"⏳ *{items_found}. 3D Asset Onay Bekliyor*\n\n"
                                        f"📦 Tip: `{md_escape(c_name)}`\n"
                                        f"📝 Ad: `{md_escape(current_item_name)}`\n"
                                        f"🔗 Roblox: {item_url}\n\n"
                                        f"İndirilsin mi?"
                                    ),
                                    reply_markup=approval_kb,
                                    parse_mode="Markdown"
                                )
                            else:
                                await send(
                                    f"⏳ *{items_found}. 3D Asset Onay Bekliyor*\n\n"
                                    f"📦 Tip: `{md_escape(c_name)}`\n"
                                    f"📝 Ad: `{md_escape(current_item_name)}`\n"
                                    f"🔗 Roblox: {item_url}\n\n"
                                    f"İndirilsin mi?",
                                    reply_markup=approval_kb
                                )
                        except Exception as e:
                            Logger.error(f"UGC Önizleme hatası: {e}")
                            await send(f"⚠️ Önizleme gönderilemeçdi ama onay bekleniyor...", reply_markup=approval_kb)
                        
                        try:
                            await asyncio.wait_for(event.wait(), timeout=360)
                            with _pending_lock:
                                status = _pending_status.pop(unique_id, "skip")
                                _pending_events.pop(unique_id, None)
                                item_data = _pending_items.pop(unique_id, None)
                            
                            if status == "approve" and item_data:
                                # Send the ZIP
                                try:
                                    with open(zip_path, "rb") as f_zip:
                                        await update.effective_message.reply_document(
                                            document=f_zip,
                                            caption=(
                                                f"📦 *3D UGC ({ugc_pack_label}):* `{md_escape(current_item_name)}`\n"
                                                f"`processed/` klasörü + `README_LEGAL.txt` (yükleme/ToS)\n"
                                                f"🔗 {item_url}"
                                            ),
                                            parse_mode="Markdown"
                                        )
                                    upload_count += 1
                                    _job_info["uploads"] = upload_count
                                    Logger.success(f"{current_item_name} başarıyla gönderildi.")
                                except Exception as e:
                                    Logger.error(f"ZIP Gönderme hatası: {e}")
                                    await send(f"⚠️ `{current_item_name}` gönderilemedi: {e}")
                            elif status == "stop":
                                _job_stop.set()
                                await send("🛑 *İş sonlandırıldı.*", reply_markup=back_keyboard())
                                break
                            elif status == "skip":
                                items_found -= 1  # Yenisini bul — aynı slotu tekrar doldur
                            # reject → items_found değişmez, sıradakine geç
                        except asyncio.TimeoutError:
                            items_found -= 1
                            await send("❌ Onay zaman aşımı, atlandı.")
                    
                    else:
                        # No approval needed — send immediately
                        try:
                            if thumb_url:
                                await update.effective_message.reply_photo(
                                    photo=thumb_url,
                                    caption=f"🖼️ *Görsel Önizleme:* `{current_item_name}`",
                                    parse_mode="Markdown"
                                )
                            with open(zip_path, "rb") as f_zip:
                                await update.effective_message.reply_document(
                                    document=f_zip,
                                    caption=(
                                        f"📦 *3D UGC ({ugc_pack_label}):* `{md_escape(current_item_name)}`\n"
                                        f"`processed/` + yasal uyarılar\n"
                                        f"🔗 {item_url}"
                                    ),
                                    parse_mode="Markdown"
                                )
                            upload_count += 1
                            _job_info["uploads"] = upload_count
                            Logger.success(f"{current_item_name} başarıyla gönderildi.")
                        except Exception as e:
                            Logger.error(f"ZIP Gönderme hatası: {e}")
                            await send(f"⚠️ `{current_item_name}` gönderilemedi: {e}")

        # Final count message logic
        finish_label = "yüklenen" if pair_mode != "ugc" else "gönderilen"
        await send(f"🏁 İş tamamlandı! Toplam {finish_label}: `{upload_count}`", reply_markup=back_keyboard())
    except Exception as e:
        Logger.error(f"İŞ SIRASINDA KRİTİK HATA: {e}")
        await send(f"⚠️ Kritik Hata: {md_escape(str(e))}")
    finally:
        _job_info["status"] = "idle"
        _job_stop.clear()

# ─── Live Sale Notifier ───────────────────────────────────────────────────────
_last_monitor_state = {"gid": 0, "cookie": None, "monitor": None}

async def live_sale_notifier_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        cfg = load_roblox_config()
        cookie = load_cookie()
        gid = cfg.get("GROUP_ID", 0)
        
        if not _last_monitor_state["monitor"] or gid != _last_monitor_state["gid"] or cookie != _last_monitor_state["cookie"]:
            if gid and cookie:
                _last_monitor_state["monitor"] = GroupFinanceMonitor(cookie, gid)
            _last_monitor_state["gid"] = gid
            _last_monitor_state["cookie"] = cookie
            
        monitor = _last_monitor_state["monitor"]
        if monitor and ALLOWED_IDS:
            sales = await asyncio.to_thread(monitor.check_new_sales)
            for sale in sales:
                item_name = sale.get("details", {}).get("name", "Bilinmeyen Ürün")
                robux = sale.get("currency", {}).get("amount", 0)
                user  = sale.get("agent", {}).get("name", "Bilinmeyen Oyuncu")
                
                msg = (
                    f"🎉 *YENİ SATIŞ!*\n\n"
                    f"👕 Ürün: `{item_name}`\n"
                    f"👤 Alıcı: `{user}`\n"
                    f"💰 Kazanılan: `+{robux} R$`"
                )
                # Tüm yetkili kullanıcılara bildirim gönder
                for user_id in ALLOWED_IDS:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                
    except Exception as e:
        Logger.error(f"Satış takip hatası: {e}")

# ─── Photo handler (Image → 3D) ───────────────────────────────────────────────
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    awaiting = ctx.user_data.get("awaiting")
    if awaiting != "model3d_image_wait":
        # Not in 3D mode — ignore silently
        return

    ctx.user_data["awaiting"] = None

    # Get highest quality photo
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
    elif update.message.document:
        photo_file = await update.message.document.get_file()
    else:
        await update.message.reply_text("❌ Geçersiz dosya. Lütfen bir fotoğraf gönder.")
        return

    status_msg = await update.message.reply_text(
        "⏳ *Görsel alındı, 3D model üretiliyor...*\n\n"
        "2️⃣ TRELLIS AI görselinizi 3D'ye dönüştürüyor...\n"
        "_Bu işlem 2-5 dakika sürebilir._",
        parse_mode="Markdown"
    )

    try:
        # Download image bytes
        import io
        buf = io.BytesIO()
        await photo_file.download_to_memory(buf)
        image_bytes = buf.getvalue()

        from scrapers.model3d_engine import Model3DEngine
        engine = Model3DEngine()
        glb_path = await asyncio.to_thread(engine.image_to_3d_sync, image_bytes)

        await status_msg.edit_text(
            "✅ *3D Model hazır!*\n\n"
            "👇 GLB dosyası aşağıda:",
            parse_mode="Markdown"
        )
        filename = os.path.basename(glb_path)
        with open(glb_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="🎲 Görselinden üretilen 3D Model",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎲 Yeni Model", callback_data="model3d_menu"),
                     InlineKeyboardButton("🏠 Ana Menü", callback_data="main")]
                ])
            )
        try:
            os.remove(glb_path)
        except Exception:
            pass

    except Exception as e:
        Logger.error(f"3D Image Model hatası: {e}")
        err_str = str(e)
        if "ZeroGPU quotas" in err_str:
            err_text = (
                "❌ *Hugging Face ZeroGPU Limitine Takıldınız!*\n\n"
                "Bu servisi çok fazla kullanan anonim kullanıcılardan biri olduğunuz için geçici sınırlandırmaya girdiniz.\n\n"
                "🛠️ *Nasıl Çözülür?*\n"
                "1. [huggingface.co](https://huggingface.co) adresinden ücretsiz üye olun\n"
                "2. Ayarlardan bir 'Access Token' (Read/Write) alın\n"
                "3. `bot_config.txt` dosyanıza `HF_TOKEN=hf_...` satırını ekleyin\n"
                "4. Botu yeniden başlatın."
            )
        else:
            err_text = (
                f"❌ *3D Model üretimi başarısız.*\n\n"
                f"Hata: `{err_str[:200].replace('`', '')}`\n\n"
                f"TRELLIS Space meşgul olabilir, biraz sonra tekrar dene."
            )
        await status_msg.edit_text(
            err_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="model3d_image"),
                 InlineKeyboardButton("🏠 Ana Menü", callback_data="main")]
            ]),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

# ─── Dummy Web Server ─────────────────────────────────────────────────────────
from http.server import BaseHTTPRequestHandler, HTTPServer

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Roblox Bot is running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    Logger.error(f"Bot Hatası: {context.error}")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        Logger.error("bot_config.txt içinde BOT_TOKEN eksik!")
        return
        
    threading.Thread(target=run_dummy_server, daemon=True).start()

    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    Logger.header(f"ROBLOX BOT BAŞLATILDI [{now}]")
    
    status_fb = "AKTİF ✅" if db_manager.is_active else "DEVRE DIŞI ❌"
    Logger.info(f"Firebase Bağlantısı: {status_fb}")
    
    if not db_manager.is_active:
        Logger.warn("Firebase-key.json bulunamadı! Ayarlar buluta senkronize edilmeyecek.")
    
    Logger.info(f"Yetkili ID'ler: {ALLOWED_IDS}")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("debug_sync", cmd_debug_sync))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_error_handler(error_handler)

    Logger.info("Ayarlar yükleniyor...")
    current_cfg = load_roblox_config()
    Logger.success(f"Ayarlar Hazır: Grup {current_cfg['GROUP_ID']} | Hedef {current_cfg['TARGET_PAIRS']} | Mod {current_cfg['PAIR_MODE']}")
    save_roblox_config(current_cfg)

    if app.job_queue:
        app.job_queue.run_repeating(live_sale_notifier_job, interval=60, first=10)

    Logger.header("BOT AKTİF - KOMUT BEKLENİYOR")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        Logger.info("Bot durduruldu (Ctrl+C).")
    except Exception as e:
        Logger.error(f"Kritik Hata: {e}")
    finally:
        print("👋 Kapanıyor...")

if __name__ == "__main__":
    main()