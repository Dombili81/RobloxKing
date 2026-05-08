import os
import sys
from curl_cffi import requests as cffi_requests

def _read_proxy() -> str | None:
    proxy = os.environ.get("ROBLOX_PROXY", "").strip()
    if not proxy:
        cfg = os.path.join(os.path.dirname(__file__), "..", "config.txt")
        try:
            with open(cfg) as f:
                for line in f:
                    if line.startswith("PROXY="):
                        proxy = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    return proxy or None

def make_session(cookie: str = None) -> cffi_requests.Session:
    """Chrome TLS parmak iziyle hazır bir session döner (CDN fingerprint bypass)."""
    proxy = _read_proxy()
    s = cffi_requests.Session(impersonate="chrome124", proxy=proxy)
    if cookie:
        s.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
    return s


class Logger:
    @staticmethod
    def header(title):
        print("\n" + "═" * 60)
        print(f"🚀 {title.upper()}")
        print("═" * 60)

    @staticmethod
    def info(msg):
        print(f"ℹ️  [BİLGİ] {msg}")

    @staticmethod
    def success(msg):
        print(f"✅ [BAŞARILI] {msg}")

    @staticmethod
    def warn(msg):
        print(f"⚠️  [UYARI] {msg}")

    @staticmethod
    def error(msg):
        print(f"❌ [HATA] {msg}")

    @staticmethod
    def search(msg):
        print(f"🔍 [ARAMA] {msg}")

    @staticmethod
    def found(msg):
        print(f"✨ [BULUNDU] {msg}")

    @staticmethod
    def download(msg):
        print(f"📥 [İNDİR] {msg}")

    @staticmethod
    def design(msg):
        print(f"🎨 [TASARIM] {msg}")

    @staticmethod
    def upload(msg):
        print(f"☁️  [YÜKLE] {msg}")

    @staticmethod
    def debug(msg):
        if os.environ.get("DEBUG"):
            print(f"🔧 [DEBUG] {msg}")

def md_escape(text: str) -> str:
    """Telegram Markdown V1 için özel karakterleri escape et. [+] ve [-] etiketlerini koru."""
    # Önce genel escape yap
    for ch in ['*', '_', '`', '[', ']']:
        text = text.replace(ch, '\\' + ch)
    
    # Karışan [+] ve [-] etiketlerini geri düzelt
    text = text.replace('\\[+\\]', '[+]')
    text = text.replace('\\[-\\]', '[-]')
    return text
