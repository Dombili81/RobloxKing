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
