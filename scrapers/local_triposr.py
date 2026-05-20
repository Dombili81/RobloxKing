"""
local_triposr.py — Lokal TripoSR tabanlı 3D motor wrapper'ı.
API anahtarı olmadığında model3d_engine tarafından kullanılır.
Pipeline: rembg arka plan kaldırma → TripoSR mesh → trimesh GLB dönüşümü.
"""
import os
import uuid
import shutil
import tempfile
import requests
from pathlib import Path


def is_available() -> bool:
    """torch ve rembg kurulu mu kontrol et. Ağırlık yüklemiyor."""
    try:
        import torch   # noqa: F401
        import rembg   # noqa: F401
        return True
    except ImportError:
        return False


class LocalTripoSREngine:
    TEXT_TO_IMAGE_URL = (
        "https://image.pollinations.ai/prompt/{prompt}"
        "?width=1024&height=1024&nologo=true&model=flux"
    )

    def __init__(self):
        self._preprocess_mod = None
        self._generate_mod   = None

    def _ensure_loaded(self):
        """İlk kullanımda stage modüllerini import et (ağır; ~10-15s CUDA'da)."""
        if self._generate_mod is not None:
            return
        from scrapers.ugc_stages import preprocess as _pre
        from scrapers.ugc_stages import generate_3d as _gen
        self._preprocess_mod = _pre
        self._generate_mod   = _gen

    def image_to_3d(self, image_bytes: bytes) -> str:
        """Ham PNG bytes → GLB dosyası. Geçici giriş dizini temizlenir."""
        self._ensure_loaded()
        work_dir = tempfile.mkdtemp(prefix="triposr_in_")
        mesh_dir = None
        try:
            in_png = Path(work_dir) / "input.png"
            in_png.write_bytes(image_bytes)

            # Stage 1: arka plan kaldır → RGBA 1024x1024
            rgba_png = self._preprocess_mod.preprocess(in_png, Path(work_dir))

            # Stage 2: TripoSR → doğrudan GLB (OBJ roundtrip yok)
            result   = self._generate_mod.generate_3d_local(rgba_png)
            src_glb  = result["glb_path"]
            mesh_dir = Path(src_glb).parent

            # Temp dizinine kopyala; mesh_dir cleanup'tan önce
            out = os.path.join(tempfile.gettempdir(), f"triposr_{uuid.uuid4().hex[:8]}.glb")
            shutil.copy2(str(src_glb), out)
            return out
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            if mesh_dir and mesh_dir.exists():
                shutil.rmtree(mesh_dir, ignore_errors=True)

    def text_to_3d(self, prompt: str) -> str:
        """Metin → Pollinations görsel → TripoSR GLB."""
        image_bytes = self._fetch_image(prompt)
        return self.image_to_3d(image_bytes)

    def _fetch_image(self, prompt: str) -> bytes:
        safe = requests.utils.quote(prompt)
        url  = self.TEXT_TO_IMAGE_URL.format(prompt=safe)
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=120, stream=True)
                r.raise_for_status()
                return r.content
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise RuntimeError("Pollinations görsel üretimi zaman aşımına uğradı.")
            except Exception as e:
                raise RuntimeError(f"Pollinations hatası: {e}")

    def _obj_to_glb(self, obj_path: str) -> str:
        """OBJ (vertex colors) → GLB via trimesh."""
        import trimesh

        mesh = trimesh.load(obj_path, force="mesh", process=False)
        if isinstance(mesh, trimesh.Scene):
            geoms = list(mesh.geometry.values())
            mesh  = trimesh.util.concatenate(geoms) if geoms else trimesh.Trimesh()

        out = os.path.join(tempfile.gettempdir(), f"triposr_{uuid.uuid4().hex[:8]}.glb")
        mesh.export(out, file_type="glb")
        return out
