# 🤖 Roblox Clothing Automation Bot

Bu proje, Roblox Marketplace üzerinden popüler kıyafetleri otomatik olarak bulan, üzerlerine özel tasarımlar/filigranlar ekleyen ve kendi Roblox grubunuzda satışa sunan profesyonel bir otomasyon sistemidir. 

**Persistency & Cloud Ready:** Firebase entegrasyonu sayesinde Render gibi geçici depolama kullanan servislerde bile ayarlarınız asla kaybolmaz.

---

## ✨ Özellikler

- 🔍 **Akıllı Arama:** Verilen keyword (anahtar kelime) ile Marketplace'te en çok satan Shirt + Pants takımlarını bulur.
- 🔗 **Eşleşme Motoru:** Sadece tekli ürünleri değil, takım (set) halindeki kıyafetleri bulmak için açıklama linklerini ve tasarımcı portföylerini tarar.
- 🎨 **Otomatik Tasarım:** İndirilen şablonların üzerine belirlenen şeffaf logoları veya tasarım katmanlarını otomatik olarak işler.
- ☁️ **Bulut Entegrasyonu:** Firebase Realtime Database ile ayarlarınızı (Cookie, Fiyat, Grup ID vb.) bulutta saklar.
- 🛡️ **Anti-Ban Korunumu:** İnsan benzeri başlıklar (headers) ve rastgele gecikmeler (random delays) ile Roblox güvenlik sistemlerine takılmadan işlem yapar.
- 📊 **Finans Takibi:** Grubunuzdaki anlık satışları ve bekleyen (pending) Robux miktarını Telegram üzerinden raporlar.

---

## 🛠️ Kurulum (Local / Kendi Bilgisayarın)

1. **Python Yükleyin:** Bilgisayarınızda Python 3.10+ yüklü olduğundan emin olun.
2. **Kütüphaneleri Kurun:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Konfigürasyon:**
   - `bot_config.txt` içine `BOT_TOKEN` ve `ALLOWED_USER_ID` bilgilerinizi girin.
   - `cookie.txt` içine Roblox `.ROBLOSECURITY` cookie'nizi yapıştırın.
4. **Çalıştırın:**
   ```bash
   python bot.py
   ```

---

## ☁️ Cloud Deployment (Render Entegrasyonu)

Bu bot, **Render.com** üzerinde 7/24 çalışacak şekilde optimize edilmiştir:

1. **GitHub:** Projeyi GitHub hesabınıza private (özel) olarak yükleyin.
2. **Render Web Service:** Render'da yeni bir "Web Service" oluşturun (Ücretsiz planı seçin).
3. **Environment Variables:**
   - `BOT_TOKEN`: Telegram bot tokenınız.
   - `ALLOWED_USER_ID`: Botu sadece sizin kullanabilmeniz için Telegram ID'niz.
   - `FIREBASE_JSON`: Firebase'den aldığınız servis hesabı JSON içeriği.
4. **Keep-Alive:** Botun uyumaması için `cron-job.org` gibi bir servis üzerinden Render URL'nizi her 10 dakikada bir pingleyebilirsiniz.

---

## 📂 Dosya Yapısı

- `bot.py`: Telegram arayüzü ve işlem yönetimi.
- `main.py`: Arama ve tasarım motoru.
- `scrapers/`: Scraper (Arama), Downloader (İndirme), Designer (Tasarım), Uploader (Yükleme) ve Firebase modülleri.
- `template.png`: Temel kıyafet şablonu.
- `config.txt`: Operasyonel ayarlar (Fiyat, Gecikme süreleri vb.).

---

## ⚠️ Dikkat ve Sorumluluk
Bu araç eğitim amaçlı geliştirilmiştir. Roblox kullanım şartlarına (TOS) uyulması tamamen kullanıcının sorumluluğundadır.

---
*Geliştirici: Antigravity AI*
