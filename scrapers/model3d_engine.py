"""
model3d_engine.py - 3D Model Üretim Motoru
HuggingFace TRELLIS (microsoft/TRELLIS) Space kullanılarak ücretsiz çalışır.
Akış:
  Text → Pollinations.ai PNG → TRELLIS → GLB
  Image → TRELLIS → GLB
"""
import os
import uuid
import time
import shutil
import tempfile
import requests


class Model3DEngine:
    SPACE_ID = "microsoft/TRELLIS"
    TEXT_TO_IMAGE_URL = "https://image.pollinations.ai/prompt/{prompt}?width=512&height=512&nologo=true&model=flux"

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Lazy-initialize the gradio client."""
        if self._client is None:
            from gradio_client import Client
            hf_token = os.environ.get("HF_TOKEN")
            if not hf_token:
                try:
                    with open("bot_config.txt", "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("HF_TOKEN="):
                                hf_token = line.strip().split("=", 1)[1].strip()
                except Exception:
                    pass
            if hf_token:
                os.environ["HF_TOKEN"] = hf_token
                os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
            self._client = Client(self.SPACE_ID, verbose=False)
        return self._client

    # ─── PUBLIC API ─────────────────────────────────────────────────────────────

    def text_to_3d_sync(self, prompt: str) -> str:
        """
        Text → PNG (Pollinations) → GLB (TRELLIS)
        Returns: path to the downloaded GLB file in /tmp/
        """
        # Step 1: Text → Image
        img_path = self._text_to_image(prompt)

        # Step 2: Image → 3D
        glb_path = self._image_to_3d_from_path(img_path, prompt)

        # Cleanup intermediate image
        try:
            os.remove(img_path)
        except Exception:
            pass

        return glb_path

    def image_to_3d_sync(self, image_bytes: bytes) -> str:
        """
        Raw image bytes → GLB (TRELLIS)
        Returns: path to the downloaded GLB file in /tmp/
        """
        # Save bytes to a temp file
        tmp_img = os.path.join(tempfile.gettempdir(), f"3d_input_{uuid.uuid4().hex[:8]}.png")
        with open(tmp_img, "wb") as f:
            f.write(image_bytes)

        try:
            glb_path = self._image_to_3d_from_path(tmp_img, "3d_model")
        finally:
            try:
                os.remove(tmp_img)
            except Exception:
                pass

        return glb_path

    # ─── PRIVATE ────────────────────────────────────────────────────────────────

    def _text_to_image(self, prompt: str) -> str:
        """
        Pollinations.ai free text→image.
        Returns path to saved PNG.
        """
        safe_prompt = requests.utils.quote(prompt)
        url = self.TEXT_TO_IMAGE_URL.format(prompt=safe_prompt)
        
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=120, stream=True)
                r.raise_for_status()
        
                out = os.path.join(tempfile.gettempdir(), f"3d_gen_{uuid.uuid4().hex[:8]}.png")
                with open(out, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                return out
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise RuntimeError("Görsel üretimi (Pollinations) zaman aşımına uğradı. Lütfen daha sonra tekrar deneyin.")
                time.sleep(2)
            except Exception as e:
                raise RuntimeError(f"Görsel üretim hatası: {e}")

    def _image_to_3d_from_path(self, image_path: str, stem: str) -> str:
        """
        Send image to TRELLIS. Returns path to a /tmp/*.glb file.
        Raises RuntimeError on failure.
        """
        from gradio_client import Client, handle_file

        client = self._get_client()

        # ── Step A: preprocess image ─────────────────────────────────────────
        preprocess_result = client.predict(
            image=handle_file(image_path),
            api_name="/preprocess_image"
        )
        # result is path-like (gradio returns a local temp path)
        preprocessed_img = preprocess_result if isinstance(preprocess_result, str) else preprocess_result[0]

        # ── Step B: image → 3D ───────────────────────────────────────────────
        import random
        gen_result = client.predict(
            image=handle_file(preprocessed_img),
            multiimages=[],
            seed=random.randint(0, 2147483647),
            ss_guidance_strength=7.5,
            ss_sampling_steps=12,
            slat_guidance_strength=3.0,
            slat_sampling_steps=12,
            multiimage_algo="stochastic",
            api_name="/image_to_3d"
        )
        # gen_result is the "trial" output dict/path needed for extract_glb

        # ── Step C: extract GLB ──────────────────────────────────────────────
        glb_result = client.predict(
            mesh_simplify=0.95,
            texture_size=1024,
            api_name="/extract_glb"
        )
        # glb_result is typically (model_path, video_path) tuple
        glb_raw = glb_result[0] if isinstance(glb_result, (list, tuple)) else glb_result

        # ── Copy to stable /tmp path ──────────────────────────────────────────
        safe_stem = "".join(c for c in stem[:20] if c.isalnum() or c in " _-").strip().replace(" ", "_")
        out_path = os.path.join(tempfile.gettempdir(), f"{safe_stem}_{uuid.uuid4().hex[:6]}.glb")
        shutil.copy2(glb_raw, out_path)
        return out_path
