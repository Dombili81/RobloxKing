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
        if _job_info["status"] != "running":
            await q.edit_message_text("ℹ️ Çalışan bir iş zaten yok.", reply_markup=back_keyboard(), parse_mode="Markdown")
        else:
            _job_stop.set()
            await q.edit_message_text("🛑 *Durdurma sinyali gönderildi.*\nMevcut adım tamamlandıktan sonra duracak.", reply_markup=back_keyboard(), parse_mode="Markdown")

    # ── Finans & Satışlar ──
    elif data == "finance":
        cfg = load_roblox_config()
        cookie = load_cookie()
        gid = cfg.get("GROUP_ID")
        if not cookie or not gid:
            await q.edit_message_text("❌ *Grup ID veya Cookie eksik!*\nSatışları görmek için önce ayarları yapmalısın.", reply_markup=back_keyboard(), parse_mode="Markdown")
            return
            
        await q.edit_message_text("⏳ *Satış verileri çekiliyor...*", parse_mode="Markdown")
        monitor = GroupFinanceMonitor(cookie, gid)
        summary = await asyncio.to_thread(monitor.get_summary)
        
        pending = summary.get("pending", 0)
        sales   = summary.get("item_sales_robux", 0)
        balance = summary.get("user_balance", 0)
        u_name  = summary.get("user_name", "Bilinmeyen")
        g_err   = summary.get("group_error")

        # Grup satışları metni
        if g_err:
            group_text = f"⚠️ *Grup Satışları:* `{g_err}`"
        else:
            group_text = (
                f"💸 Bekleyen Robux: `{pending} R$`\n"
                f"🛍️ Bugün Satışlardan Gelen: `{sales} R$`"
            )

        text = (
            f"📈 *Finans Özeti*\n\n"
            f"👤 Kullanıcı: `{u_name}`\n"
            f"💰 *Hesap Bakiyesi:* `{balance} R$`\n\n"
            f"{group_text}\n\n"
            f"_Anlık satış bildirimleri arkaplanda aktiftir._"
        )
        await q.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

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
    elif data.startswith("approve_") or data.startswith("reject_") or data.startswith("skip_") or data.startswith("stop_job_"):
        parts = data.split("_", 1)
        action = parts[0]
        if action == "stop" and "job" in parts[1]: # handle stop_job_XXX
            action = "stop"
            unique_id = parts[1].replace("job_", "")
        else:
            unique_id = parts[1]
        
        if unique_id in _pending_events:
            event = _pending_events[unique_id]
            with _pending_lock:
                _pending_status[unique_id] = action
            
            event.set()
            
            if action == "approve":
                conf_msg = "✅ *Onaylandı:* Yükleniyor..."
            elif action == "stop":
                conf_msg = "🛑 *Durduruldu:* İşlem sonlandırılıyor."
            else:
                conf_msg = "🔍 *Atlandı:* Sıradaki aranıyor..."

            try:
                if q.message.caption:
                    await q.edit_message_caption(conf_msg, parse_mode="Markdown")
                else:
                    await q.edit_message_text(conf_msg, parse_mode="Markdown")
            except Exception as e:
                Logger.error(f"Callback düzenleme hatası: {e}")

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

    elif awaiting == "group":
        ctx.user_data["awaiting"] = None
        try:
            gid = int(text)
        except ValueError:
            await update.message.reply_text("❌ Geçersiz ID. Sadece rakam gir.", reply_markup=settings_keyboard())
            return
        cfg = load_roblox_config()
        cfg["GROUP_ID"] = gid
        save_roblox_config(cfg)
        await update.message.reply_text(f"✅ Grup ID `{gid}` olarak ayarlandı.", reply_markup=settings_keyboard(), parse_mode="Markdown")

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
            await update.message.reply_text("⚠️ *Uyarı:* Girdiğin değer normal bir Roblox Cookie'sine benzemiyor. Genelde `_|WARNING:-DO-NOT-SHARE-THIS.` ile başlar. Yine de kaydediyorum.", parse_mode="Markdown")
        
        # Save to Firebase AND local file
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
    
    await update.message.reply_text(
        f"🚀 *İş Başladı!*\n\n"
        f"🔍 Keyword(ler): `{'`, `'.join(keyword_list)}`\n"
        f"🎯 Hedef {target_label}: `{TARGET_PAIRS}` / keyword\n\n"
        f"⚙️ Hazırlanıyor, lütfen bekle…",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

    _job_stop.clear()
    _active_task = asyncio.create_task(job_task(update, ctx, keyword_list, cfg, cookie, ugc_cat))

# ─── Background job (Async Task) ──────────────────────────────────────────────
async def job_task(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword_list, cfg, cookie, ugc_cat=None):
    async def send(msg, **kwargs):
        try:
            return await update.message.reply_text(msg, parse_mode="Markdown", **kwargs)
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
                pants_pool = await roblox.search_and_get_assets(keyword, count=40, asset_type=12)
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
                    await send(f"✅ *{keyword.title()}* için {items_found}. çift bulundu!")

                    shirt_path = await download_and_design(asset_id, keyword, "shirt", downloader, designer)
                    pants_path = await download_and_design(pants_id, keyword, "pants", downloader, designer)
                    if not shirt_path or not pants_path: continue

                    shirt_name, shirt_desc = generate_metadata(keyword, "shirt")
                    pants_name, pants_desc = generate_metadata(keyword, "pants")
                    
                    do_upload = True
                    if require_approval:
                        unique_id = f"{asset_id}_pair"
                        event = asyncio.Event()
                        with _pending_lock:
                            _pending_events[unique_id] = event
                            _pending_items[unique_id] = {"shirt_path": shirt_path, "pants_path": pants_path, "shirt_id": asset_id, "pants_id": pants_id}
                        
                        # Çift modda iki resmi bir grup olarak gönderip altına onay mesajı atıyoruz
                        from telegram import InputMediaPhoto
                        try:
                            # We open files synchronously but send asynchronously
                            with open(shirt_path, "rb") as s_img, open(pants_path, "rb") as p_img:
                                await update.message.reply_media_group([
                                    InputMediaPhoto(s_img, caption=f"👕 *Shirt:* {shirt_name}"),
                                    InputMediaPhoto(p_img, caption=f"👖 *Pants:* {pants_name}")
                                ])
                        except Exception as e:
                            Logger.error(f"Önizleme (Media Group) hatası: {e}")

                        dup_warn = "⚠️ *DİKKAT: Bu çift daha önce yüklendi!*\n\n" if is_duplicate else ""
                        await send(
                            f"{dup_warn}⏳ *Yukarıdaki {items_found}. Çift İçin Onay Bekleniyor*\n\n"
                            f"👕 S: `{shirt_name}`\n"
                            f"👖 P: `{pants_name}`\n\n"
                            f"📜 *Shirt Açıklama:*\n`{shirt_desc}`\n\n"
                            f"📜 *Pants Açıklama:*\n`{pants_desc}`\n\n"
                            f"Yüklensin mi?",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}")],
                                [InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}"),
                                 InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}")],
                                [InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                            ])
                        )
                        
                        try:
                            await asyncio.wait_for(event.wait(), timeout=360)
                            with _pending_lock:
                                status = _pending_status.pop(unique_id, "skip")
                                _pending_events.pop(unique_id, None)
                                item_data = _pending_items.pop(unique_id, None)
                            
                            if status == "approve" and item_data:
                                do_upload = True
                            elif status == "stop":
                                _job_stop.set(); do_upload = False; break
                            elif status == "skip":
                                items_found -= 1; do_upload = False; continue # Slotu boş bırakma, yenisini bul
                            else: # status == "reject"
                                do_upload = False; continue # Slotu boş say, sıradakine geç (items_found zaten artmıştı)
                        except asyncio.TimeoutError:
                            items_found -= 1; do_upload = False; continue

                    if do_upload and uploader:
                        await send("☁️ Yükleniyor…")
                        upload_count = await upload_pair_with_crosslink(asset_id, shirt_path, pants_id, pants_path, keyword, uploader, upload_count, cfg)
                        _job_info["uploads"] = upload_count

            elif pair_mode == "single":
                single_type = cfg.get("SINGLE_TYPE", 11)
                type_name = "shirt" if single_type == 11 else "pants"
                async for asset_id, item_url, creator, current_item_name in roblox.search_and_yield_assets(keyword, asset_type=single_type):
                    if _job_stop.is_set() or items_found >= target_pairs: break
                    
                    # ── Duplicate Check ──
                    is_duplicate = db_manager.is_item_uploaded(asset_id)
                    if is_duplicate:
                        Logger.warn(f"Bu item ({asset_id}) daha önce yüklendi! Kullanıcıya sorulacak.")

                    items_found += 1
                    _job_info["pairs_done"] = items_found
                    
                    await send(f"✅ *{keyword.title()}* için {items_found}. {type_name} bulundu!")
                    out_path = await download_and_design(asset_id, keyword, type_name, downloader, designer)
                    if not out_path: continue

                    name, desc = generate_metadata(keyword, type_name, use_suffix=False)
                    
                    do_upload = True
                    if require_approval:
                        unique_id = f"{asset_id}_{single_type}"
                        event = asyncio.Event()
                        with _pending_lock:
                            _pending_events[unique_id] = event
                            _pending_items[unique_id] = {"asset_path": out_path, "asset_id": asset_id}

                        # Single modda resmin altına butonları koyabiliyoruz
                        try:
                            dup_warn = "⚠️ *DİKKAT: Bu ürün daha önce yüklendi!*\n\n" if is_duplicate else ""
                            with open(out_path, "rb") as f:
                                await update.message.reply_photo(
                                    photo=f,
                                    caption=f"{dup_warn}⏳ *İtem {items_found} Onay Bekliyor*\n\n"
                                            f"👔 Tip: `{type_name.title()}`\n"
                                            f"📝 Ad: `{name}`\n"
                                            f"📜 Açıklama: `{desc}`\n\n"
                                            f"Yüklensin mi?",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}")],
                                        [InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}"),
                                         InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}")],
                                        [InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                                    ]),
                                    parse_mode="Markdown"
                                )
                        except Exception as e:
                            Logger.error(f"Önizleme (Photo) hatası: {e}")
                            await send("⚠️ Önizleme gönderilemedi ama onay bekleniyor...", reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{unique_id}")],
                                        [InlineKeyboardButton("🔍 Yenisini Bul", callback_data=f"skip_{unique_id}"),
                                         InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{unique_id}")],
                                        [InlineKeyboardButton("🛑 İşlemi Bitir", callback_data=f"stop_job_{unique_id}")]
                                    ]))
                        
                        try:
                            await asyncio.wait_for(event.wait(), timeout=360)
                            with _pending_lock:
                                status = _pending_status.pop(unique_id, "skip")
                                _pending_events.pop(unique_id, None)
                                item_data = _pending_items.pop(unique_id, None)
                            
                            if status == "approve" and item_data:
                                do_upload = True
                            elif status == "stop":
                                _job_stop.set(); await send("🛑 *İş sonlandırıldı.*", reply_markup=back_keyboard()); do_upload = False; break
                            elif status == "skip":
                                items_found -= 1; do_upload = False; continue # Slotu boş bırakma, yenisini bul
                            else: # status == "reject"
                                do_upload = False; continue # Slotu boş say, sıradakine geç
                        except asyncio.TimeoutError:
                            items_found -= 1; await send(f"❌ Onay zaman aşımı, atlandı."); do_upload = False; continue

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
                                await update.message.reply_photo(
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
                                        await update.message.reply_document(
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
                                await update.message.reply_photo(
                                    photo=thumb_url,
                                    caption=f"🖼️ *Görsel Önizleme:* `{current_item_name}`",
                                    parse_mode="Markdown"
                                )
                            with open(zip_path, "rb") as f_zip:
                                await update.message.reply_document(
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
        await send(f"⚠️ Kritik Hata: {e}")
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