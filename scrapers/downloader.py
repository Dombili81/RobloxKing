import requests
import os
import re
from scrapers.firebase_db import FirebaseManager
from scrapers.utils import Logger

class AssetDownloader:
    def __init__(self):
        # Firebase üzerinden merkezi cookie yönetimi
        self.db = FirebaseManager()

    def _normalize_cookie(self, raw: str) -> str | None:
        """Cookie stringini temizle."""
        if not raw:
            return None
        raw = str(raw).strip().strip('"').strip("'")
        if 'WARNING:"-DO' in raw or "WARNING:\"-DO" in raw:
            raw = raw.replace('WARNING:"-DO', "WARNING:-DO").replace('WARNING:\"-DO', "WARNING:-DO")
        if raw.startswith(".ROBLOSECURITY="):
            raw = raw[len(".ROBLOSECURITY="):]
        return raw if raw else None

    def _load_cookie(self) -> str | None:
        """Cookie öncelik sırası: Firebase -> Env -> cookie.txt"""
        try:
            cloud = self.db.load_settings()
        except:
            cloud = {}

        raw = cloud.get("ROBLOX_COOKIE")
        if raw:
            out = self._normalize_cookie(raw)
            if out: return out

        env_cookie = os.environ.get("ROBLOX_COOKIE")
        if env_cookie:
            out = self._normalize_cookie(env_cookie)
            if out: return out

        if os.path.exists("cookie.txt"):
            try:
                with open("cookie.txt", "r", encoding="utf-8") as f:
                    out = self._normalize_cookie(f.read())
                    if out: return out
            except: pass
        return None

    async def download_template(self, asset_id):
        """Roblox kıyafet şablonunu indirir."""
        Logger.download(f"Şablon indiriliyor: {asset_id}")
        
        path = f"downloads/{asset_id}.png"
        os.makedirs("downloads", exist_ok=True)

        cookie = self._load_cookie()
        headers = {"User-Agent": "Roblox/WinInet"}
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"
            Logger.debug("Oturum kurabiyesi kullanılıyor.")

        base_urls = [
            f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}",
            f"https://assetdelivery.roproxy.com/v1/asset/?id={asset_id}",
            f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}&version=1"
        ]

        for url in base_urls:
            try:
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    content = response.content
                    if content.startswith(b"\x89PNG"):
                        with open(path, "wb") as f:
                            f.write(content)
                        Logger.success("İndirme başarılı (Doğrudan PNG).")
                        return path
                    
                    text = content.decode("utf-8", errors="ignore")
                    match = re.search(r"rbxassetid://(\d+)", text) or re.search(r"id=(\d+)", text)
                    if match:
                        image_id = match.group(1)
                        Logger.debug(f"Görüntü ID tespit edildi: {image_id}. PNG alınıyor...")
                        img_url = f"https://assetdelivery.roblox.com/v1/asset/?id={image_id}"
                        img_resp = requests.get(img_url, headers=headers, timeout=10)
                        if img_resp.status_code == 200 and img_resp.content.startswith(b"\x89PNG"):
                            with open(path, "wb") as f:
                                f.write(img_resp.content)
                            Logger.success(f"İndirme başarılı (Resim ID: {image_id})")
                            return path
                
                elif response.status_code == 401 and cookie:
                    Logger.debug("Oturum hatası (401), oturumsuz deneniyor...")
                    resp_no_auth = requests.get(url, timeout=10)
                    if resp_no_auth.status_code == 200 and resp_no_auth.content.startswith(b"\x89PNG"):
                        with open(path, "wb") as f:
                            f.write(resp_no_auth.content)
                        Logger.success("İndirme başarılı (Fallback).")
                        return path
            except Exception as e:
                Logger.debug(f"İşlem hatası: {e}")

        Logger.error(f"Şablon indirilemedi: {asset_id}")
        return None

    async def download_ugc_asset(self, asset_id, keyword, category_name):
        """UGC Accessory indirir (Mesh ve Texture) ve ZIP dosyasının yolunu döndürür."""
        import zipfile
        Logger.download(f"UGC Asset indiriliyor: {asset_id}")
        
        cookie = self._load_cookie()
        headers = {"User-Agent": "Roblox/WinInet"}
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        # 1. Accessory XML/Binary dosyasını al
        url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}"
        try:
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                Logger.error(f"UGC Dosyası İndirme Hatası: {resp.status_code}")
                return None
        except Exception as e:
            Logger.error(f"UGC URL Hatası: {e}")
            return None
            
        content_text = resp.content.decode('utf-8', errors='ignore')
        
        # 2. MeshId ve TextureId'yi regex ile bul (daha esnek regex)
        # XML, JSON veya Binary içindeki ID'leri yakalamaya çalışır
        mesh_id_match = (
            re.search(r'MeshId.*?(\d+)', content_text, re.IGNORECASE) or 
            re.search(r'rbxassetid://(\d+)', content_text)
        )
        texture_id_match = (
            re.search(r'TextureId.*?(\d+)', content_text, re.IGNORECASE) or
            re.search(r'TextureID.*?(\d+)', content_text, re.IGNORECASE)
        )
        
        if not mesh_id_match:
            # Yedek: XML tag'leri arasında ara
            mesh_id_match = re.search(r'<url>.*?(?:id=)?(\d+)</url>', content_text)
            
        if not mesh_id_match:
            Logger.warn(f"Mesh ID bulunamadı (Asset: {asset_id}).")
            return None
            
        mesh_id = mesh_id_match.group(1)
        # TextureId bazen MeshId ile aynı yerde geçer, bazen geçmez.
        # Eğer ilk aramada bulunamadıysa MeshId sonrasına bak.
        if not texture_id_match:
            after_mesh = content_text[mesh_id_match.end():]
            texture_id_match = re.search(r'(\d+)', after_mesh) if "Texture" in after_mesh else None
            
        texture_id = texture_id_match.group(1) if texture_id_match else None
        
        os.makedirs("downloads/ugc", exist_ok=True)
        # keyword'i dosya adına uygun hale getir (boşlukları sil vb)
        safe_kw = re.sub(r'[^A-Za-z0-9]', '_', keyword)
        zip_path = f"downloads/ugc/{asset_id}_{safe_kw}_{category_name}.zip"
        
        try:
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                # İndir: Mesh
                mesh_url = f"https://assetdelivery.roblox.com/v1/asset/?id={mesh_id}"
                m_resp = requests.get(mesh_url, headers=headers, timeout=10)
                if m_resp.status_code == 200:
                    # obj ise .obj, değilse .mesh
                    ext = ".obj" if m_resp.content.startswith(b"v ") else ".mesh"
                    zipf.writestr(f"{asset_id}_mesh{ext}", m_resp.content)
                else:
                    Logger.error(f"Mesh indirilemedi: {mesh_id}")
                    return None
                    
                # İndir: Texture
                if texture_id:
                    tex_url = f"https://assetdelivery.roblox.com/v1/asset/?id={texture_id}"
                    t_resp = requests.get(tex_url, headers=headers, timeout=10)
                    if t_resp.status_code == 200:
                        zipf.writestr(f"{asset_id}_texture.png", t_resp.content)
                    else:
                        Logger.warn(f"Texture indirilemedi: {texture_id}")
            
            Logger.success(f"UGC Zip başarıyla oluşturuldu: {zip_path}")
            return zip_path
        except Exception as e:
            Logger.error(f"ZIP Oluşturma Hatası: {e}")
            return None
