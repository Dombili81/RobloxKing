"""
model3d_engine.py - 3D Model Üretim Motoru

Öncelik sırası:
  1. Tripo3D REST API  (TRIPO3D_API_KEY)
  2. Meshy REST API    (MESHY_API_KEY)
  3. HF Spaces fallback (HF_TOKEN — gradio_client)

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
import traceback
import requests


_TRIPO_BASE = "https://api.tripo3d.ai/v2/openapi"
_MESHY_BASE = "https://api.meshy.ai/openapi/v2"
_POLL_INTERVAL = 3   # seconds between status checks
_POLL_TIMEOUT  = 300 # 5 minutes max


class Model3DEngine:
    # HF Spaces fallback list (used only when no REST API key configured)
    SPACE_IDS = [
        "microsoft/TRELLIS.2",
        "stabilityai/TripoSR",
        "JeffreyXiang/TRELLIS",
        "microsoft/TRELLIS",
    ]
    TEXT_TO_IMAGE_URL = (
        "https://image.pollinations.ai/prompt/{prompt}"
        "?width=512&height=512&nologo=true&model=flux"
    )

    def __init__(self):
        cfg = self._load_config()
        self._tripo_key: str | None = cfg.get("TRIPO3D_API_KEY")
        self._meshy_key: str | None = cfg.get("MESHY_API_KEY")
        self._hf_token:  str | None = cfg.get("HF_TOKEN")

        # HF fallback state
        self._client = None
        self._active_space = None
        self._space_type = None
        self._failed_spaces: set = set()

        src = ("Tripo3D" if self._tripo_key else
               "Meshy"   if self._meshy_key else
               "HF Spaces (fallback)")
        print(f"[model3d_engine] Aktif kaynak: {src}")

    # ─── CONFIG ─────────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        keys = ("TRIPO3D_API_KEY", "MESHY_API_KEY", "HF_TOKEN")
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
                print(f"[model3d_engine] Tripo3D başarısız ({type(e).__name__}: {e}), Meshy'e geçiliyor...")
        if self._meshy_key:
            try:
                return self._meshy_text(prompt), None
            except Exception as e:
                print(f"[model3d_engine] Meshy başarısız ({type(e).__name__}: {e}), HF'e geçiliyor...")
        return self._hf_text_to_3d(prompt)

    def image_to_3d_sync(self, image_bytes: bytes) -> str:
        tmp = os.path.join(tempfile.gettempdir(), f"3d_in_{uuid.uuid4().hex[:8]}.png")
        with open(tmp, "wb") as f:
            f.write(image_bytes)
        try:
            if self._tripo_key:
                try:
                    return self._tripo_image(tmp)
                except Exception as e:
                    print(f"[model3d_engine] Tripo3D başarısız ({type(e).__name__}: {e}), Meshy'e geçiliyor...")
            if self._meshy_key:
                try:
                    return self._meshy_image(tmp)
                except Exception as e:
                    print(f"[model3d_engine] Meshy başarısız ({type(e).__name__}: {e}), HF'e geçiliyor...")
            return self._hf_image_to_3d(tmp)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

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
        print(f"[model3d_engine] Tripo3D text-to-3D: {prompt[:60]}")
        payload = {
            "type": "text_to_model",
            "prompt": prompt,
            "model_version": "v2.5-20250123",
            "texture": False,
        }
        r = requests.post(f"{_TRIPO_BASE}/task", json=payload, headers=self._tripo_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"[model3d_engine] Tripo3D task: {task_id}")
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
        print(f"[model3d_engine] Tripo3D image-to-3D: {image_path}")
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
        print(f"[model3d_engine] Tripo3D task: {task_id}")
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
        print(f"[model3d_engine] Meshy text-to-3D: {prompt[:60]}")
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
        print(f"[model3d_engine] Meshy task: {task_id}")
        url = self._meshy_poll_text(task_id)
        return self._meshy_download(url, prompt)

    def _meshy_image(self, image_path: str) -> str:
        print(f"[model3d_engine] Meshy image-to-3D: {image_path}")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        image_data_uri = f"data:image/png;base64,{b64}"
        payload = {"image_url": image_data_uri, "topology": "triangle", "target_polycount": 30000}
        r = requests.post(f"{_MESHY_BASE}/image-to-3d", json=payload, headers=self._meshy_headers(), timeout=30)
        r.raise_for_status()
        task_id = r.json()["result"]
        print(f"[model3d_engine] Meshy task: {task_id}")
        url = self._meshy_poll_image(task_id)
        return self._meshy_download(url, "3d_model")

    # ─── HF SPACES FALLBACK ─────────────────────────────────────────────────────

    def _hf_text_to_3d(self, prompt: str) -> tuple:
        last_err = None
        while True:
            try:
                client = self._get_client()
            except Exception as e:
                raise RuntimeError(f"Tüm 3D space'leri başarısız. Son hata: {last_err}") from e
            current = self._active_space
            try:
                if self._space_type == "triposr":
                    img_path = self._text_to_image(prompt)
                    glb_path = self._call_triposr(client, img_path, prompt)
                    return glb_path, img_path
                elif self._space_type == "trellis_v2":
                    img_path = self._text_to_image(prompt)
                    glb_path = self._call_trellis_v2(client, img_path, prompt)
                    return glb_path, img_path
                else:
                    img_path = self._text_to_image(prompt)
                    glb_path = self._call_trellis(client, img_path, prompt)
                    return glb_path, img_path
            except Exception as e:
                print(f"[model3d_engine] '{current}' başarısız ({type(e).__name__}), sonraki: {e}")
                self._reset_client(failed_space=current)
                last_err = e

    def _hf_image_to_3d(self, image_path: str) -> str:
        last_err = None
        while True:
            try:
                client = self._get_client()
            except Exception as e:
                raise RuntimeError(f"Tüm 3D space'leri başarısız. Son hata: {last_err}") from e
            current = self._active_space
            try:
                if self._space_type == "triposr":
                    return self._call_triposr(client, image_path, "3d_model")
                elif self._space_type == "trellis_v2":
                    return self._call_trellis_v2(client, image_path, "3d_model")
                else:
                    return self._call_trellis(client, image_path, "3d_model")
            except Exception as e:
                print(f"[model3d_engine] '{current}' başarısız ({type(e).__name__}), sonraki: {e}")
                print(traceback.format_exc())
                self._reset_client(failed_space=current)
                last_err = e

    def _load_hf_token(self) -> str | None:
        return self._hf_token

    def _detect_space_type(self, client) -> str | None:
        try:
            info = client.view_api(return_format="dict")
            endpoints = set(info.get("named_endpoints", {}).keys())
        except Exception:
            return None
        if "/start_session" in endpoints and "/image_to_3d" in endpoints:
            return "trellis_v2"
        if "/image_to_3d" in endpoints and "/extract_glb" in endpoints:
            return "trellis"
        if "/run" in endpoints or "/image-to-3d" in endpoints:
            return "triposr"
        trellis_hints = {"/preprocess_image", "/image_to_3d", "/extract_glb", "/get_seed"}
        if trellis_hints & endpoints:
            return "trellis"
        return None

    def _get_client(self):
        if self._client is not None:
            return self._client
        from gradio_client import Client
        token = self._load_hf_token()
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        last_err = None
        for space_id in self.SPACE_IDS:
            if space_id in self._failed_spaces:
                continue
            try:
                client = Client(space_id, verbose=False)
            except Exception as e:
                err_str = str(e)
                if any(k in err_str for k in ("CONFIG_ERROR", "invalid state", "SPACE_HARDWARE_ERROR")) or \
                   any(k in err_str.lower() for k in ("sleeping", "timeout", "connection")):
                    last_err = RuntimeError(f"{space_id}: {e}")
                    print(f"[model3d_engine] '{space_id}' bağlantı hatası, atlanıyor: {e}")
                    continue
                raise
            space_type = self._detect_space_type(client)
            if space_type is None:
                last_err = RuntimeError(f"{space_id}: uyumlu endpoint bulunamadı")
                continue
            self._client = client
            self._active_space = space_id
            self._space_type = space_type
            return self._client
        raise RuntimeError(
            f"Tüm 3D space'leri başarısız. Son hata: {last_err}. "
            f"Denenen: {self.SPACE_IDS}, Başarısız: {list(self._failed_spaces)}"
        )

    def _reset_client(self, failed_space: str | None = None):
        if failed_space:
            self._failed_spaces.add(failed_space)
            print(f"[model3d_engine] '{failed_space}' kara listeye alındı.")
        self._client = None
        self._active_space = None
        self._space_type = None

    def _text_to_image(self, prompt: str) -> str:
        safe_prompt = requests.utils.quote(prompt)
        url = self.TEXT_TO_IMAGE_URL.format(prompt=safe_prompt)
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=120, stream=True)
                r.raise_for_status()
                out = os.path.join(tempfile.gettempdir(), f"3d_gen_{uuid.uuid4().hex[:8]}.png")
                with open(out, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                return out
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise RuntimeError("Görsel üretimi (Pollinations) zaman aşımına uğradı.")
                time.sleep(2)
            except Exception as e:
                raise RuntimeError(f"Görsel üretim hatası: {e}")

    def _call_triposr(self, client, image_path: str, stem: str) -> str:
        from gradio_client import handle_file
        result = client.predict(
            image=handle_file(image_path),
            do_remove_background=True,
            foreground_ratio=0.85,
            api_name="/run",
        )
        model_raw = result[-1] if isinstance(result, (list, tuple)) else result
        safe = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        ext = os.path.splitext(str(model_raw))[-1].lower() or ".glb"
        out = os.path.join(tempfile.gettempdir(), f"{safe}_{uuid.uuid4().hex[:6]}{ext}")
        shutil.copy2(model_raw, out)
        return out

    def _call_trellis(self, client, image_path: str, stem: str) -> str:
        from gradio_client import handle_file
        import random

        def _missing(e):
            return any(k in str(e) for k in ("Cannot find", "api_name", "No endpoint"))

        preprocessed = image_path
        try:
            res = client.predict(image=handle_file(image_path), api_name="/preprocess_image")
            preprocessed = res if isinstance(res, str) else res[0]
        except Exception as e:
            if not _missing(e):
                raise

        try:
            client.predict(
                image=handle_file(preprocessed),
                multiimages=[],
                seed=random.randint(0, 2147483647),
                ss_guidance_strength=7.5,
                ss_sampling_steps=12,
                slat_guidance_strength=3.0,
                slat_sampling_steps=12,
                multiimage_algo="stochastic",
                api_name="/image_to_3d",
            )
        except Exception as e:
            if _missing(e):
                raise RuntimeError(f"'{self._active_space}' /image_to_3d endpoint bulunamadı.") from e
            raise

        try:
            glb_result = client.predict(mesh_simplify=0.95, texture_size=1024, api_name="/extract_glb")
        except Exception as e:
            if _missing(e):
                raise RuntimeError(f"'{self._active_space}' /extract_glb endpoint bulunamadı.") from e
            raise

        glb_raw = glb_result[0] if isinstance(glb_result, (list, tuple)) else glb_result
        safe = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        out = os.path.join(tempfile.gettempdir(), f"{safe}_{uuid.uuid4().hex[:6]}.glb")
        shutil.copy2(glb_raw, out)
        return out

    def _call_trellis_v2(self, client, image_path: str, stem: str) -> str:
        from gradio_client import handle_file
        import random

        def _missing(e):
            return any(k in str(e) for k in ("Cannot find", "api_name", "No endpoint"))

        preprocessed = image_path
        try:
            res = client.predict(input=handle_file(image_path), api_name="/preprocess_image")
            preprocessed = res if isinstance(res, str) else res.get("path", image_path) if isinstance(res, dict) else image_path
        except Exception as e:
            if not _missing(e):
                raise

        try:
            client.predict(
                image=handle_file(preprocessed),
                seed=random.randint(0, 2147483647),
                resolution="1024",
                ss_guidance_strength=7.5,
                ss_guidance_rescale=0.7,
                ss_sampling_steps=12,
                ss_rescale_t=5.0,
                shape_slat_guidance_strength=7.5,
                shape_slat_guidance_rescale=0.5,
                shape_slat_sampling_steps=12,
                shape_slat_rescale_t=3.0,
                tex_slat_guidance_strength=1.0,
                tex_slat_guidance_rescale=0.0,
                tex_slat_sampling_steps=12,
                tex_slat_rescale_t=3.0,
                api_name="/image_to_3d",
            )
        except Exception as e:
            if _missing(e):
                raise RuntimeError(f"'{self._active_space}' /image_to_3d endpoint bulunamadı.") from e
            raise

        try:
            glb_result = client.predict(decimation_target=300000, texture_size=2048, api_name="/extract_glb")
        except Exception as e:
            if _missing(e):
                raise RuntimeError(f"'{self._active_space}' /extract_glb endpoint bulunamadı.") from e
            raise

        glb_raw = glb_result[0] if isinstance(glb_result, (list, tuple)) else glb_result
        safe = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        out = os.path.join(tempfile.gettempdir(), f"{safe}_{uuid.uuid4().hex[:6]}.glb")
        shutil.copy2(glb_raw, out)
        return out
