"""
model3d_engine.py - 3D Model Üretim Motoru

Öncelik sırası:
  1. Tripo3D REST API  (TRIPO3D_API_KEY)
  2. Meshy REST API    (MESHY_API_KEY)
  3. Lokal TripoSR     (torch + rembg kuruluysa — GPU önerilir)

Public API (değişmez):
  text_to_3d_sync(prompt)         -> GLB path
  text_to_3d_with_preview(prompt) -> (GLB path, None)
  image_to_3d_sync(image_bytes)   -> GLB path
"""
import os
import uuid
import time
import base64
import shutil
import tempfile
import requests


_TRIPO_BASE = "https://api.tripo3d.ai/v2/openapi"
_MESHY_BASE = "https://api.meshy.ai/openapi/v2"
_POLL_INTERVAL = 3   # seconds between status checks
_POLL_TIMEOUT  = 300 # 5 minutes max


class Model3DEngine:

    def __init__(self):
        cfg = self._load_config()
        self._tripo_key: str | None = cfg.get("TRIPO3D_API_KEY")
        self._meshy_key: str | None = cfg.get("MESHY_API_KEY")

        # Lokal TripoSR motoru (lazy init)
        self._local_engine = None
        self._local_available: bool | None = None

        src = ("Tripo3D" if self._tripo_key else
               "Meshy"   if self._meshy_key else
               "Lokal TripoSR")
        print(f"[3D Motor] Aktif kaynak: {src}")

    # ─── CONFIG ─────────────────────────────────────────────────────────────────

    def _get_local_engine(self):
        """Lokal TripoSR motorunu lazy başlat. Kurulu değilse RuntimeError."""
        if self._local_available is None:
            from scrapers.local_triposr import is_available
            self._local_available = is_available()
        if not self._local_available:
            raise RuntimeError(
                "Lokal TripoSR kullanılamıyor: torch veya rembg kurulu değil. "
                "Kurmak için: pip install torch torchvision rembg"
            )
        if self._local_engine is None:
            from scrapers.local_triposr import LocalTripoSREngine
            self._local_engine = LocalTripoSREngine()
        return self._local_engine

    def _load_config(self) -> dict:
        keys = ("TRIPO3D_API_KEY", "MESHY_API_KEY")
        cfg = {k: os.environ.get(k) for k in keys}
        try:
            with open("bot_config.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        if k in keys and not cfg.get(k):
                            cfg[k] = v.strip()
        except Exception:
            pass
        return cfg

    # ─── PUBLIC API ─────────────────────────────────────────────────────────────

    def text_to_3d_sync(self, prompt: str) -> str:
        glb_path, preview = self.text_to_3d_with_preview(prompt)
        if preview:
            try:
                os.remove(preview)
            except Exception:
                pass
        return glb_path

    def text_to_3d_with_preview(self, prompt: str) -> tuple:
        if self._tripo_key:
            try:
                return self._tripo_text(prompt), None
            except Exception as e:
                print(f"[3D Motor] Tripo3D başarısız → Meshy deneniyor... ({type(e).__name__}: {e})")
        if self._meshy_key:
            try:
                return self._meshy_text(prompt), None
            except Exception as e:
                print(f"[3D Motor] Meshy başarısız → Lokal TripoSR deneniyor... ({type(e).__name__}: {e})")
        local = self._get_local_engine()
        return local.text_to_3d(prompt), None

    def image_to_3d_sync(self, image_bytes: bytes) -> str:
        if self._tripo_key:
            tmp = os.path.join(tempfile.gettempdir(), f"3d_in_{uuid.uuid4().hex[:8]}.png")
            with open(tmp, "wb") as f:
                f.write(image_bytes)
            try:
                return self._tripo_image(tmp)
            except Exception as e:
                print(f"[3D Motor] Tripo3D başarısız → Meshy deneniyor... ({type(e).__name__}: {e})")
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        if self._meshy_key:
            tmp = os.path.join(tempfile.gettempdir(), f"3d_in_{uuid.uuid4().hex[:8]}.png")
            with open(tmp, "wb") as f:
                f.write(image_bytes)
            try:
                return self._meshy_image(tmp)
            except Exception as e:
                print(f"[3D Motor] Meshy başarısız → Lokal TripoSR deneniyor... ({type(e).__name__}: {e})")
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        local = self._get_local_engine()
        return local.image_to_3d(image_bytes)

    # ─── TRIPO3D ────────────────────────────────────────────────────────────────

    def _tripo_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._tripo_key}", "Content-Type": "application/json"}

    def _tripo_poll(self, task_id: str) -> str:
        """Poll until success; return GLB download URL."""
        deadline = time.time() + _POLL_TIMEOUT
        while time.time() < deadline:
            r = requests.get(f"{_TRIPO_BASE}/task/{task_id}", headers=self._tripo_headers(), timeout=30)
            r.raise_for_status()
            data = r.json().get("data", {})
            status = data.get("status", "")
            if status == "success":
                url = data.get("result", {}).get("model", {}).get("url")
                if not url:
                    raise RuntimeError(f"Tripo3D task {task_id} başarılı ama model URL yok: {data}")
                return url
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"Tripo3D task {task_id} başarısız: {status} — {data}")
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError(f"Tripo3D task {task_id} zaman aşımına uğradı ({_POLL_TIMEOUT}s)")

    def _tripo_download(self, url: str, stem: str) -> str:
        safe = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        out = os.path.join(tempfile.gettempdir(), f"{safe}_{uuid.uuid4().hex[:6]}.glb")
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out

    def _tripo_text(self, prompt: str) -> str:
        print(f"[3D Motor] Tripo3D — metin: {prompt[:60]}")
        payload = {
            "type": "text_to_model",
            "prompt": prompt,
            "model_version": "v2.5-20250123",
            "texture": False,
        }
        r = requests.post(f"{_TRIPO_BASE}/task", json=payload, headers=self._tripo_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"[3D Motor] Tripo3D task: {task_id}")
        url = self._tripo_poll(task_id)
        return self._tripo_download(url, prompt)

    def _tripo_upload_image(self, image_path: str) -> str:
        """Upload image to Tripo3D, return file_token."""
        headers = {"Authorization": f"Bearer {self._tripo_key}"}
        with open(image_path, "rb") as f:
            r = requests.post(
                f"{_TRIPO_BASE}/upload",
                headers=headers,
                files={"file": ("image.png", f, "image/png")},
                timeout=60,
            )
        r.raise_for_status()
        return r.json()["data"]["image_token"]

    def _tripo_image(self, image_path: str) -> str:
        print(f"[3D Motor] Tripo3D — görsel: {image_path}")
        file_token = self._tripo_upload_image(image_path)
        payload = {
            "type": "image_to_model",
            "file": {"type": "png", "file_token": file_token},
            "model_version": "v2.5-20250123",
            "texture": False,
        }
        r = requests.post(f"{_TRIPO_BASE}/task", json=payload, headers=self._tripo_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"[3D Motor] Tripo3D task: {task_id}")
        url = self._tripo_poll(task_id)
        return self._tripo_download(url, "3d_model")

    # ─── MESHY ──────────────────────────────────────────────────────────────────

    def _meshy_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._meshy_key}", "Content-Type": "application/json"}

    def _meshy_poll_text(self, task_id: str) -> str:
        deadline = time.time() + _POLL_TIMEOUT
        while time.time() < deadline:
            r = requests.get(f"{_MESHY_BASE}/text-to-3d/{task_id}", headers=self._meshy_headers(), timeout=30)
            r.raise_for_status()
            data = r.json()
            status = data.get("status", "")
            if status == "SUCCEEDED":
                url = data.get("model_urls", {}).get("glb")
                if not url:
                    raise RuntimeError(f"Meshy task {task_id} başarılı ama GLB URL yok: {data}")
                return url
            if status in ("FAILED", "EXPIRED"):
                raise RuntimeError(f"Meshy task {task_id} başarısız: {status}")
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError(f"Meshy task {task_id} zaman aşımına uğradı ({_POLL_TIMEOUT}s)")

    def _meshy_poll_image(self, task_id: str) -> str:
        deadline = time.time() + _POLL_TIMEOUT
        while time.time() < deadline:
            r = requests.get(f"{_MESHY_BASE}/image-to-3d/{task_id}", headers=self._meshy_headers(), timeout=30)
            r.raise_for_status()
            data = r.json()
            status = data.get("status", "")
            if status == "SUCCEEDED":
                url = data.get("model_urls", {}).get("glb")
                if not url:
                    raise RuntimeError(f"Meshy task {task_id} başarılı ama GLB URL yok: {data}")
                return url
            if status in ("FAILED", "EXPIRED"):
                raise RuntimeError(f"Meshy task {task_id} başarısız: {status}")
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError(f"Meshy task {task_id} zaman aşımına uğradı ({_POLL_TIMEOUT}s)")

    def _meshy_download(self, url: str, stem: str) -> str:
        safe = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        out = os.path.join(tempfile.gettempdir(), f"{safe}_{uuid.uuid4().hex[:6]}.glb")
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out

    def _meshy_text(self, prompt: str) -> str:
        print(f"[3D Motor] Meshy — metin: {prompt[:60]}")
        payload = {
            "mode": "preview",
            "prompt": prompt,
            "art_style": "realistic",
            "topology": "triangle",
            "target_polycount": 30000,
        }
        r = requests.post(f"{_MESHY_BASE}/text-to-3d", json=payload, headers=self._meshy_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["result"]
        print(f"[3D Motor] Meshy task: {task_id}")
        url = self._meshy_poll_text(task_id)
        return self._meshy_download(url, prompt)

    def _meshy_image(self, image_path: str) -> str:
        print(f"[3D Motor] Meshy — görsel: {image_path}")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        image_data_uri = f"data:image/png;base64,{b64}"
        payload = {"image_url": image_data_uri, "topology": "triangle", "target_polycount": 30000}
        r = requests.post(f"{_MESHY_BASE}/image-to-3d", json=payload, headers=self._meshy_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["result"]
        print(f"[3D Motor] Meshy task: {task_id}")
        url = self._meshy_poll_image(task_id)
        return self._meshy_download(url, "3d_model")

