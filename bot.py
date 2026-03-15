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
        "MAX_UPLOADS_PER_SESSION": int(os.environ.get("MAX_UPLOADS_PER_SESSION", 10))
    }
    
    # 1. First, check Firebase for persistent settings
    cloud_settings = db_manager.load_settings()
    for k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "MAX_UPLOADS_PER_SESSION"]:
        if k in cloud_settings:
            try:
                cfg[k] = int(cloud_settings[k])
            except ValueError:
                pass

    # 2. Then check local file (only valid if developing locally)
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k in cfg: # File always overwrites Env Vars
                        try:
                            # If the file has a default value (like GROUP_ID=0)
                            # and env var has a real value, keep env var. Otherwise overwrite.
                            val = int(v.strip())
                            if val != 0 and val != 5 and val != 45 and val != 90 and val != 10:
                                cfg[k] = val
                            elif not os.environ.get(k): 
                                cfg[k] = val
                        except ValueError:
                            pass
    return cfg

def save_roblox_config(cfg, path="config.txt"):
    for k, v in cfg.items():
        if k in ["GROUP_ID", "PRICE", "DELAY_MIN", "DELAY_MAX", "MAX_UPLOADS_PER_SESSION"]:
            db_manager.save_setting(k, v)

    with open(path, "w") as f:
        f.write(f"GROUP_ID={cfg['GROUP_ID']}\nPRICE={cfg['PRICE']}\n"
                f"DELAY_MIN={cfg['DELAY_MIN']}\nDELAY_MAX={cfg['DELAY_MAX']}\n"
                f"MAX_UPLOADS_PER_SESSION={cfg['MAX_UPLOADS_PER_SESSION']}\n")

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
TARGET_PAIRS = 5

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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💰  Fiyat: {price} Robux",   callback_data="set_price")],
        [InlineKeyboardButton(f"🏷  Grup ID: {group}",       callback_data="set_group")],
        [InlineKeyboardButton(f"🎯  Hedef Çift: {TARGET_PAIRS}", callback_data="set_pairs")],
        [InlineKeyboardButton(f"🔑  Cookie: {cookie_str}",       callback_data="set_cookie")],
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
    await update.message.reply_text(WELCOME, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

# ─── Callback router ─────────────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return await deny(update)
    q    = update.callback_query
    data = q.data
    await q.answer()

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
            "4. `cookie.txt` dosyasına yapıştır\n\n"
            "⚠️ Cookie'nin süresi zaman zaman dolabilir. "
            "Bot hata verirse yeni cookie al ve `cookie.txt`'i güncelle.",
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
        await update.message.reply_text(f"✅ Her keyword için `{TARGET_PAIRS}` çift indirilecek.", reply_markup=settings_keyboard(), parse_mode="Markdown")

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

    else:
        # Tanımsız mesaj → Ana menüyü göster
        await update.message.reply_text("Ana menü:", reply_markup=main_menu_keyboard())

# ─── Job launcher ─────────────────────────────────────────────────────────────
async def start_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE, keyword_list: list):
    cfg    = load_roblox_config()
    cookie = load_cookie()
    loop   = asyncio.get_event_loop()

    async def send_fn(msg: str):
        await update.message.reply_text(msg, parse_mode="Markdown")

    await update.message.reply_text(
        f"🚀 *İş Başladı!*\n\n"
        f"🔍 Keyword(ler): `{'`, `'.join(keyword_list)}`\n"
        f"🎯 Hedef çift: `{TARGET_PAIRS}` / keyword\n\n"
        f"📬 Gelişmeleri buradan takip edebilirsin.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

    _job_stop.clear()
    t = threading.Thread(
        target=_job_thread_fn,
        args=(keyword_list, cfg, cookie, send_fn, loop, TARGET_PAIRS),
        daemon=True,
    )
    t.start()

# ─── Background job ──────────────────────────────────────────────────────────
def _job_thread_fn(keyword_list, cfg, cookie, send_fn, loop, target_pairs):
    def send(msg):
        asyncio.run_coroutine_threadsafe(send_fn(msg), loop)

    global _job_info
    _job_info.update({"status": "running", "keywords": keyword_list, "pairs_done": 0, "uploads": 0})

    roblox     = RobloxScraper(cookie=cookie)
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
        if _job_stop.is_set(): break
        send(f"🔍 *{keyword.title()}* için tarama başlıyor…")
        pairs_found = 0

        inner_loop = asyncio.new_event_loop()

        async def process_keyword():
            nonlocal pairs_found, upload_count
            async for asset_id, item_url in roblox.search_and_yield_assets(keyword):
                if _job_stop.is_set() or pairs_found >= target_pairs:
                    break
                try:
                    paired_pants = await roblox.get_paired_pants(asset_id)
                except Exception:
                    paired_pants = []
                if not paired_pants:
                    continue

                pairs_found += 1
                _job_info["pairs_done"] = pairs_found
                send(f"✅ Çift #{pairs_found} bulundu! (`{keyword.title()}`)")

                shirt_out = await download_and_design(asset_id, keyword, "shirt", downloader, designer)
                if not shirt_out:
                    send(f"❌ Shirt indirme başarısız: `{asset_id}`")
                    continue

                pants_id, _ = paired_pants[0]
                pants_out = await download_and_design(pants_id, keyword, "pants", downloader, designer)
                if not pants_out:
                    send(f"❌ Pants indirme başarısız: `{pants_id}`")
                    continue

                send(f"🎨 Tasarım eklendi — Shirt + Pants hazır!")

                if uploader:
                    send("☁️ Yükleniyor… _(Anti-ban bekleme başlıyor)_")
                    upload_count = await upload_pair_with_crosslink(
                        asset_id, shirt_out, pants_id, pants_out,
                        keyword, uploader, upload_count, cfg
                    )
                    _job_info["uploads"] = upload_count
                    send(f"🔗 Yüklendi + çapraz linklendi! Toplam yüklenen: `{upload_count}`")

            if pairs_found >= target_pairs:
                send(f"🏁 `{keyword.title()}` için {target_pairs} çift tamamlandı!")
            elif pairs_found == 0:
                send(f"😕 `{keyword.title()}` için eşleşen çift bulunamadı.")

        inner_loop.run_until_complete(process_keyword())
        inner_loop.close()

    _job_stop.clear()
    _job_info["status"] = "idle"
    send(
        f"✅ *İş Tamamlandı!*\n\n"
        f"📦 Toplam yüklenen: `{upload_count}` item\n\n"
        f"_Ana menüye dönmek için /start yaz._"
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

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        print("HATA: bot_config.txt içinde BOT_TOKEN bulunamadı!")
        return
        
    threading.Thread(target=run_dummy_server, daemon=True).start()

    print(f"🤖 Bot başlatılıyor… (Allowed ID: {ALLOWED_ID})")

    # job_queue'yu aktif etmek için builder yeterli, timeout artırıldı
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("✅ Bot hazır! Arkaplan takip sistemi başlatılıyor...")
    
    # Start live sale loop every 60 seconds (PTB Native JobQueue)
    if app.job_queue:
        app.job_queue.run_repeating(live_sale_notifier_job, interval=60, first=10)
    
    app.run_polling()

if __name__ == "__main__":
    main()
