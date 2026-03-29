"""
firebase_db.py - Firebase Firestore entegrasyonu (Ayarların kalıcı depolanması için)
"""
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

class FirebaseManager:
    """
    Render gibi sunucularda her restartta dosyaların silinmesini önlemek için 
    ayarları (cookie, group_id vb.) Firebase Firestore'a kaydeder.
    """
    def __init__(self, key_path="firebase-key.json"):
        self.db = None
        self.is_active = False
        
        # Sadece key dosyası varsa veya ortam değişkeni olarak JSON verilmişse aktif olur
        env_json = os.environ.get("FIREBASE_JSON")
        
        try:
            if not firebase_admin._apps:
                if env_json:
                    cred_dict = json.loads(env_json)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                elif os.path.exists(key_path):
                    cred = credentials.Certificate(key_path)
                    firebase_admin.initialize_app(cred)
                else:
                    return 

            self.db = firestore.client()
            self.is_active = True
            self.doc_ref = self.db.collection("roblox_bot").document("settings")
            
            # Get project ID safely even if cred wasn't defined in this specific call
            project_id = "Bilinmiyor"
            if firebase_admin._apps:
                main_app = firebase_admin.get_app()
                if main_app.project_id:
                    project_id = main_app.project_id
            
            print(f"☁️  Firebase Firestore bağlantısı başarılı (Proje: {project_id})")
        except Exception as e:
            print(f"⚠️ Firebase başlatılamadı: {e}")
            print("💡 İPUCU: firebase-key.json dosyası mevcut mu?")

    def save_setting(self, key: str, value):
        """ Tek bir ayarı Firebase'e kaydet """
        if not self.is_active: return
        try:
            self.doc_ref.set({key: value}, merge=True)
        except Exception as e:
            print(f"Firebase yazma hatası ({key}): {e}")

    def save_cookie(self, cookie: str):
        self.save_setting("ROBLOX_COOKIE", cookie)

    def is_item_uploaded(self, source_id: str) -> bool:
        """Item daha önce yüklendi mi kontrol et."""
        if not self.is_active: return False
        try:
            # uploaded_items koleksiyonunda bu source_id var mı bak
            doc = self.db.collection("uploaded_items").document(str(source_id)).get()
            return doc.exists
        except Exception as e:
            print(f"Firebase duplicate check hatası: {e}")
            return False

    def mark_item_as_uploaded(self, source_id: str, roblox_id: str, is_pair: bool = False):
        """Yüklenen itemi kaydederek tekrarını önleriz."""
        if not self.is_active: return
        try:
            self.db.collection("uploaded_items").document(str(source_id)).set({
                "original_id": str(source_id),
                "roblox_id": str(roblox_id),
                "is_pair": is_pair,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"Firebase save uploaded hatası: {e}")

    def load_settings(self) -> dict:
        """ Tüm ayarları Firebase'den çek """
        if not self.is_active: return {}
        try:
            doc = self.doc_ref.get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"Firebase okuma hatası: {e}")
        return {}

    def get_recent_uploads(self, limit: int = 5, offset: int = 0) -> list:
        """Son eklenen ürünleri Firestore'dan liste formatında getirir."""
        if not self.is_active: return []
        try:
            query = self.db.collection("uploaded_items").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit)
            if offset > 0:
                query = query.offset(offset)
            results = []
            for doc in query.stream():
                results.append(doc.to_dict())
            return results
        except Exception as e:
            print(f"Firebase recent_uploads okuma hatası: {e}")
            return []

    def increment_trend_click(self, keyword: str):
        """Kullanıcının üretime başlattığı trendin tıklama sayısını artırır."""
        if not self.is_active: return
        try:
            doc_ref = self.db.collection("trend_analytics").document(str(keyword))
            doc_ref.set({
                "keyword": keyword,
                "click_count": firestore.Increment(1),
                "last_clicked": firestore.SERVER_TIMESTAMP
            }, merge=True)
        except Exception as e:
            print(f"Firebase trend click kaydı hatası: {e}")
