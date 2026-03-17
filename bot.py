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
from main import generate_metadata, download_and_design, upload_pair_with_crosslink

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
    for k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "TARGET_PAIRS"]:
        if k in cloud_settings:
            try:
                val = int(cloud_settings[k])
                # If cloud has a '0' for GROUP_ID but local has a real ID, keep the local one.
                if k == "GROUP_ID" and val == 0 and cfg[k] != 0:
                    continue
                cfg[k] = val
            except ValueError:
                pass
                
    return cfg

def save_roblox_config(cfg, path="config.txt"):
    for k, v in cfg.items():
        if k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "TARGET_PAIRS", "SORT_TYPE", "SORT_AGG"]:
            db_manager.save_setting(k, v)

    with open(path, "w") as f:
        f.write(
            f"GROUP_ID={cfg['GROUP_ID']}\n"
            f"PRICE={cfg['PRICE']}\n"
            f"DELAY_MIN={cfg['DELAY_MIN']}\n"
            f"DELAY_MAX={cfg['DELAY_MAX']}\n"
            f"TARGET_PAIRS={cfg['TARGET_PAIRS']}\n"
            f"SORT_TYPE={cfg['SORT_TYPE']}\n"
            f"SORT_AGG={cfg['SORT_AGG']}\n"
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

BOT_CFG    = load_bot_config()
BOT_TOKEN  = BOT_CFG.get("BOT_TOKEN", "")
ALLOWED_ID = int(BOT_CFG.get("ALLOWED_USER_ID", "0"))

# ─── Conversation states ──────────────────────────────────────────────────────
WAITING_KEYWORD  = 1
WAITING_GROUP    = 2
WAITING_PRICE    = 3
WAITING_PAIRS    = 4

# ─── Job state ────────────────────────────────────────────────────────────────
_job_stop  = threading.Event()
_job_info  = {"status": "idle", "keywords": [], "pairs_done": 0, "uploads": 0}
_initial_cfg = load_roblox_config()
TARGET_PAIRS = _initial_cfg.get("TARGET_PAIRS", 5)

# ─── Auth ─────────────────────────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_ID

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
    sort_label_map = {
        (2, 5): "En Çok Satan (Tüm Zamanlar)",
        (2, 3): "En Çok Satan (Son Hafta)",
        (2, 1): "En Çok Satan (Son Gün)",
        (1, 5): "En Çok Favorilenen",
        (4, 5): "Fiyat: Düşük → Yüksek",
        (5, 5): "Fiyat: Yüksek → Düşük",
    }
    sort_key = (cfg.get("SORT_TYPE", 2), cfg.get("SORT_AGG", 5))
    sort_label = sort_label_map.get(sort_key, "En Çok Satan (Tüm Zamanlar)")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💰  Fiyat: {price} Robux",   callback_data="set_price")],
        [InlineKeyboardButton(f"🏷  Grup ID: {group}",       callback_data="set_group")],
        [InlineKeyboardButton(f"🎯  Hedef Çift: {TARGET_PAIRS}", callback_data="set_pairs")],
        [InlineKeyboardButton(f"🔑  Cookie: {cookie_str}",       callback_data="set_cookie")],
        [InlineKeyboardButton(f"🧭  Sıralama: {sort_label}",      callback_data="set_sort")],
        [InlineKeyboardButton("⬅️  Ana Menü",                 callback_data="main")],
    ])

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
    
    # Wrap answer in try-except to avoid "Query too old" errors after restarts
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
        # Fetching takes a second, do it safely
        summary = await asyncio.to_thread(monitor.get_summary)
        
        if "error" in summary:
            await q.edit_message_text(f"❌ *Hata:* `{summary['error']}`", reply_markup=back_keyboard(), parse_mode="Markdown")
        else:
            pending = summary.get("pending", 0)
            sales   = summary.get("item_sales_robux", 0)
            text = (
                f"📈 *Grup Finans Özeti*\n\n"
                f"💸 Bekleyen Robux: `{pending} R$`\n"
                f"🛍️ Bugün Satışlardan Gelen: `{sales} R$`\n\n"
                f"_Anlık satış bildirimleri arkaplanda aktiftir._"
            )
            await q.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

    # ── Ayarlar ──
    elif data == "settings":
        await q.edit_message_text("⚙️ *Ayarlar*\nDeğiştirmek istediğin ayara tıkla:", reply_markup=settings_keyboard(), parse_mode="Markdown")

    # ── Ayar seçenekleri (conversation başlatıcı değil, direkt bilgi ver) ──
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
        await q.edit_message_text(
            f"🎯 *Hedef Çift Sayısı*\n\nŞu an: `{TARGET_PAIRS}`\n\nHer keyword için kaç çift (shirt+pants) indirilsin? (1–30):",
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
            "6️⃣ Fiyat: Yüksek → Düşük\n\n"
            "Seçtiğin numarayı yaz (örn: `1`).",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        ctx.user_data["awaiting"] = "sort"

    # ── İş Başlat ──
    elif data == "run":
        if _job_info["status"] == "running":
            await q.edit_message_text("⚠️ Zaten bir iş çalışıyor. Önce /stop ile durdur.", reply_markup=back_keyboard(), parse_mode="Markdown")
            return
        ctx.user_data["awaiting"] = "keyword"
        await q.edit_message_text(
            "🚀 *İş Başlat*\n\n"
            "Aramak istediğin keyword(ler)i yaz:\n\n"
            "📌 *Tek keyword:* `spiderman`\n"
            "📌 *Çoklu:* `naruto, batman, goku`\n\n"
            "Anime, oyun, sporcu… ne olursa yaz:",
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
        await q.edit_message_text(
            "⚙️ *Ayarlar Hakkında*\n\n"
            f"💰 *Fiyat* (`{cfg['PRICE']}` Robux) — Kıyafetlerin satış fiyatı\n\n"
            f"🏷 *Grup ID* (`{cfg['GROUP_ID'] or 'Ayarlanmadı'}`) — Kıyafetlerin yükleneceği Roblox grubu\n\n"
            f"🎯 *Hedef Çift* (`{TARGET_PAIRS}`) — Her keyword için kaç çift shirt+pants indirilsin\n\n"
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

# ─── Metin mesajı handler (ayar input / keyword input) ───────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    awaiting = ctx.user_data.get("awaiting")
    text     = update.message.text.strip()

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
        print(f"[Firebase] Saved TARGET_PAIRS={n}")
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
        }
        if choice not in sort_map:
            await update.message.reply_text("❌ Geçersiz seçim. 1–6 arasında bir numara yaz.", reply_markup=settings_keyboard(), parse_mode="Markdown")
            return

        sort_type, sort_agg = sort_map[choice]
        cfg = load_roblox_config()
        cfg["SORT_TYPE"] = sort_type
        cfg["SORT_AGG"]  = sort_agg
        save_roblox_config(cfg)

        await update.message.reply_text("✅ Sıralama tercihin kaydedildi. Bir sonraki aramada bu sıraya göre aranacak.", reply_markup=settings_keyboard(), parse_mode="Markdown")

    else:
        # Tanımsız mesaj → Ana menüyü göster
        await update.message.reply_text("Ana menü:", reply_markup=main_menu_keyboard())

# ─── Job launcher ─────────────────────────────────────────────────────────────
async def start_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE, keyword_list: list):
    cfg    = load_roblox_config()
    cookie = load_cookie()
    loop   = asyncio.get_event_loop()

    # Tek bir "durum" mesajı üzerinden ilerlemeyi gösterebilmek için
    status_msg = await update.message.reply_text(
        f"🚀 *İş Başladı!*\n\n"
        f"🔍 Keyword(ler): `{'`, `'.join(keyword_list)}`\n"
        f"🎯 Hedef çift: `{TARGET_PAIRS}` / keyword\n\n"
        f"⚙️ Hazırlanıyor, lütfen bekle…",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

    # Geçici görsel önizleme: output dosyalarını Telegram'a atıp 30 sn sonra sil
    async def send_preview(path: str, caption: str):
        try:
            with open(path, "rb") as f:
                msg = await update.message.reply_document(
                    document=f,
                    caption=caption,
                    parse_mode="Markdown",
                )
        except Exception as e:
            # Önizleme hatası durumunda sessizce devam et
            print(f"Preview send error for {path}: {e}")
            return

        # 30 saniye sonra mesajı sil
        try:
            await asyncio.sleep(30)
            await msg.delete()
        except Exception as e:
            print(f"Preview delete error for {path}: {e}")

    async def send_fn(msg: str, *, reply_markup=None, force_new: bool = False):
        nonlocal status_msg
        # Varsayılan: mevcut durum mesajını güncelle
        try:
            if not status_msg or force_new:
                status_msg = await update.message.reply_text(
                    msg,
                    reply_markup=reply_markup or main_menu_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                await status_msg.edit_text(
                    msg,
                    reply_markup=reply_markup or status_msg.reply_markup or main_menu_keyboard(),
                    parse_mode="Markdown"
                )
        except Exception:
            # Herhangi bir edit hatasında yedek olarak yeni mesaj gönder
            status_msg = await update.message.reply_text(
                msg,
                reply_markup=reply_markup or main_menu_keyboard(),
                parse_mode="Markdown"
            )

    _job_stop.clear()
    t = threading.Thread(
        target=_job_thread_fn,
        args=(keyword_list, cfg, cookie, send_fn, send_preview, loop, TARGET_PAIRS),
        daemon=True,
    )
    t.start()

# ─── Background job ──────────────────────────────────────────────────────────
def _job_thread_fn(keyword_list, cfg, cookie, send_fn, preview_fn, loop, target_pairs):
    def send(msg, **kwargs):
        asyncio.run_coroutine_threadsafe(send_fn(msg, **kwargs), loop)

    def preview(path: str, caption: str):
        asyncio.run_coroutine_threadsafe(preview_fn(path, caption), loop)

    try:
        global _job_info
        _job_info.update({"status": "running", "keywords": keyword_list, "pairs_done": 0, "uploads": 0})

        # Sıralama ayarlarını config'ten çek
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
                send("⚠️ Grup ID ayarlanmadı — sadece indirme yapılacak.\n_Ayarlamak için: ⚙️ Ayarlar → Grup ID_")

        upload_count = 0

        for keyword in keyword_list:
            if _job_stop.is_set():
                break

            send(
                f"🔍 *{keyword.title()}* için arama başlatıldı…\n\n"
                f"• 👕 Uygun shirt/pants çiftleri aranıyor\n"
                f"• 🎯 Hedef çift sayısı: `{target_pairs}`\n\n"
                f"⏳ İlk sonuçlar bulununca burada göreceksin."
            )
            pairs_found = 0

            async def process_keyword():
                nonlocal pairs_found, upload_count

                # Step 1: Pre-fetch a pool of pants for creator-matching fallback
                pants_pool = await roblox.search_and_get_assets(keyword, count=40, asset_type=12)
                used_pants_ids = set()

                def match_pair_fast(s_name, s_creator, pool):
                    """Matches by creator and name similarity (FAST)"""
                    import re
                    s_clean = re.sub(r'shirt', '', s_name, flags=re.IGNORECASE).strip().lower()
                    for p_id, p_url, p_creator, p_name in pool:
                        p_clean = re.sub(r'pants|pant', '', p_name, flags=re.IGNORECASE).strip().lower()
                        # If same creator and names are very similar, it's a match
                        if s_creator == p_creator and (s_clean in p_clean or p_clean in s_clean):
                            return p_id
                    return None

                search_gen = roblox.search_and_yield_assets(keyword)
                try:
                    async for asset_id, item_url, creator, current_item_name in search_gen:
                        if _job_stop.is_set() or pairs_found >= target_pairs:
                            break

                        # Step 2A: Try Fast Name Matching (No API call)
                        pants_id = match_pair_fast(current_item_name, creator, pants_pool)
                        
                        if pants_id:
                            print(f"[Match] Found via name similarity: {current_item_name} <-> {pants_id}")
                        else:
                            # Step 2B: Fallback to Direct link in description (Slow API call)
                            try:
                                paired_pants = await roblox.get_paired_pants(asset_id, keyword)
                                if paired_pants:
                                    pants_id, _ = paired_pants[0]
                                    print(f"[Match] Found via direct link: {asset_id} <-> {pants_id}")
                            except Exception:
                                pass

                        if not pants_id:
                            # Eğer açıklamada doğrudan link yoksa bu shirt'i tamamen atla,
                            # böylece rastgele/uyuşmayan pantolonlarla eşleşme yapılmaz.
                            print(f"[Match] Skipping shirt {asset_id} — no explicit paired pants link found.")
                            continue

                        used_pants_ids.add(pants_id)

                        pairs_found += 1
                        _job_info["pairs_done"] = pairs_found

                        send(
                            f"✅ *{keyword.title()}* için çift bulundu!\n\n"
                            f"• 🔢 Çift sayısı: `{pairs_found}/{target_pairs}`\n"
                            f"• 👕 Shirt ID: `{asset_id}`\n"
                            f"• 👖 Pants ID: `{pants_id}`\n\n"
                            f"🎨 Tasarım uygulanıyor…"
                        )

                        shirt_label = f"{keyword.replace(' ', '_')}_shirt{pairs_found}"
                        shirt_out = await download_and_design(
                            asset_id, keyword, "shirt", downloader, designer, custom_label=shirt_label
                        )
                        if not shirt_out:
                            send(f"❌ Shirt indirme başarısiz: `{asset_id}`")
                            continue

                        pants_label = f"{keyword.replace(' ', '_')}_pants{pairs_found}"
                        pants_out = await download_and_design(
                            pants_id, keyword, "pants", downloader, designer, custom_label=pants_label
                        )
                        if not pants_out:
                            send(f"❌ Pants indirme başarısız: `{pants_id}`")
                            continue

                        # Satışa koyarken kullanılacak başlık ve açıklama; önizlemede link yok, placeholder göster
                        shirt_name, shirt_desc = generate_metadata(keyword, "shirt", pair_url="Buraya link gelecek")
                        pants_name, pants_desc = generate_metadata(keyword, "pants", pair_url="Buraya link gelecek")
                        def _trunc(s: str, max_len: int = 480) -> str:
                            s = (s or "").strip().replace("`", "'")
                            return (s[:max_len] + "…") if len(s) > max_len else s
                        # Test amaçlı: fotoğraf + satış başlığı/açıklaması, 30 sn sonra silinecek
                        cap_shirt = (
                            f"👕 *Shirt* (Çift {pairs_found})\n\n"
                            f"*Satış başlığı:*\n`{shirt_name}`\n\n"
                            f"*Satış açıklaması:*\n`{_trunc(shirt_desc)}`"
                        )
                        cap_pants = (
                            f"👖 *Pants* (Çift {pairs_found})\n\n"
                            f"*Satış başlığı:*\n`{pants_name}`\n\n"
                            f"*Satış açıklaması:*\n`{_trunc(pants_desc)}`"
                        )
                        preview(shirt_out, cap_shirt)
                        preview(pants_out, cap_pants)

                        send(
                            f"🎨 Tasarım tamamlandı!\n\n"
                            f"• 👕 Shirt ID: `{asset_id}`\n"
                            f"• 👖 Pants ID: `{pants_id}`\n\n"
                            f"☁️ Şimdi gruba yükleniyor…"
                        )

                        if uploader:
                            send("☁️ Yükleniyor… _(Anti-ban bekleme başlıyor)_")
                            upload_count = await upload_pair_with_crosslink(
                                asset_id, shirt_out, pants_id, pants_out,
                                keyword, uploader, upload_count, cfg
                            )
                            _job_info["uploads"] = upload_count
                            
                            # Only say "searching" if we haven't reached the target yet
                            if pairs_found < target_pairs:
                                send(
                                    f"🔗 Yükleme tamamlandı ve açıklamalar çapraz linklendi!\n\n"
                                    f"• 📦 Bu oturumda yüklenen toplam item: `{upload_count}`\n"
                                    f"• 🔢 İşlenen çift: `{pairs_found}/{target_pairs}`\n\n"
                                    f"🔍 Yeni çiftler aranıyor…"
                                )
                            else:
                                send(
                                    f"🔗 Yükleme ve linkleme tamamlandı!\n\n"
                                    f"• 📦 Toplam yüklenen item: `{upload_count}`\n"
                                    f"• 🔢 Hedeflenen `{target_pairs}` çift başariyla işlendi."
                                )
                finally:
                    await search_gen.aclose()

            asyncio.run(process_keyword())

            if pairs_found >= target_pairs:
                send(f"🏁 `{keyword.title()}` için {target_pairs} çift tamamlandı!")
            elif pairs_found == 0:
                send(f"😕 `{keyword.title()}` için eşleşen çift bulunamadı.")

    except Exception as e:
        print(f"BÜYÜK HATA (Arkaplan İşi): {e}")
        send(f"⚠️ *Kritik Bir Hata Oluştu!*\n\nBot işleme durduruldu. Lütfen tekrar başlatmayı dene.\n`Hata: {e}`")
    finally:
        _job_stop.clear()
        _job_info["status"] = "idle"

    send(
        f"✅ *Yükleme Tamamlandı!*\n\n"
        f"📦 Bu oturumda toplamdaki yüklenen item sayısı: `{upload_count}`\n\n"
        f"🧭 Yeni bir arama başlatmak veya ayarları değiştirmek için ana menüye dönebilirsin.",
        reply_markup=back_keyboard()
    )

# ─── Live Sale Notifier (Background Task) ───────────────────────────────────
_last_monitor_state = {"gid": 0, "cookie": None, "monitor": None}

async def live_sale_notifier_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Sürekli arkaplanda çalışır (PTB JobQueue). Yeni satış olduğunda bota mesaj atar.
    """
    try:
        cfg = load_roblox_config()
        cookie = load_cookie()
        gid = cfg.get("GROUP_ID", 0)
        
        # config değişirse monitorü yenile
        if not _last_monitor_state["monitor"] or gid != _last_monitor_state["gid"] or cookie != _last_monitor_state["cookie"]:
            if gid and cookie:
                _last_monitor_state["monitor"] = GroupFinanceMonitor(cookie, gid)
            _last_monitor_state["gid"] = gid
            _last_monitor_state["cookie"] = cookie
            
        monitor = _last_monitor_state["monitor"]
        if monitor and ALLOWED_ID:
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
                await context.bot.send_message(chat_id=ALLOWED_ID, text=msg, parse_mode="Markdown")
                
    except Exception as e:
        print(f"Satış takip hatası: {e}")

# ─── Dummy Web Server (For Render Free Tier) ──────────────────────────────────
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
    print(f"⚠️ Bot Hatası: {context.error}")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        print("HATA: bot_config.txt içinde BOT_TOKEN bulunamadı!")
        return
        
    # Start dummy server for hosting platforms
    threading.Thread(target=run_dummy_server, daemon=True).start()

    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print("\n" + "="*50)
    print(f"🚀 ROBLOX BOT BAŞLATILDI [{now}]")
    print("="*50)
    
    status_fb = "AKTİF ✅" if db_manager.is_active else "DEVRE DIŞI ❌ (Anahtar dosyası eksik)"
    print(f"🛰 Firebase Bağlantısı: {status_fb}")
    
    if not db_manager.is_active:
        print("❗ UYARI: Firebase-key.json bulunamadı. Değişiklikler buluta işlenmeyecek!")
    
    print(f"🤖 Allowed ID: {ALLOWED_ID}")
    print("="*50 + "\n")

    # job_queue'yu aktif etmek için builder yeterli, timeout artırıldı
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .build()
    )

    # 1. Register Handlers IMMEDIATELY
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("debug_sync", cmd_debug_sync))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(error_handler)

    # 2. Sync Configuration
    print("🔄 Ayarlar yükleniyor/senkronize ediliyor...")
    current_cfg = load_roblox_config()
    print(f"✅ Ayarlar hazır (Grup: {current_cfg['GROUP_ID']}, Hedef: {current_cfg['TARGET_PAIRS']})")
    save_roblox_config(current_cfg)

    # 3. Start Background Tasks
    if app.job_queue:
        app.job_queue.run_repeating(live_sale_notifier_job, interval=60, first=10)

    print("✅ Bot hazır! Telegram üzerinden komut bekleniyor...")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n🛑 Bot kullanıcı tarafından durduruldu (Ctrl+C).")
    except Exception as e:
        print(f"\n❌ Kritik Hata: {e}")
    finally:
        print("👋 Kapanıyor...")

if __name__ == "__main__":
    main()
