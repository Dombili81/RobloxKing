import sys

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
        # Silenced by default. Change to print(f"DEBUG: {msg}") if needed.
        pass
