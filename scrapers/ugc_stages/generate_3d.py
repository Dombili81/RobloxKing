"""
Stage 2 — Yüksek Kalite AI 3D Mesh (TripoSR)
==============================================
TripoSR modeli ile gerçek, kaliteli 3D dönüşümü.
"""

import sys
import time
from pathlib import Path
from PIL import Image
import torch
import numpy as np
import trimesh

from scrapers.ugc_stages.config import (
    RAW_DIR,
    TRIPOSR_MC_RESOLUTION,
    TRIPOSR_MODEL_ID,
    TRIPOSR_CHUNK_SIZE,
)

_stages_dir = str(Path(__file__).parent)
if _stages_dir not in sys.path:
    sys.path.insert(0, _stages_dir)

_TSR_READY = False
_tsr_model = None
_tsr_device = "cpu"


def _try_load_tsr():
    global _TSR_READY, _tsr_model, _tsr_device
    if _TSR_READY:
        return True
    try:
        from tsr.system import TSR
        print("  → TripoSR modeli yükleniyor...")
        _tsr_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        _tsr_model = TSR.from_pretrained(
            TRIPOSR_MODEL_ID, config_name="config.yaml", weight_name="model.ckpt"
        )
        chunk_size = TRIPOSR_CHUNK_SIZE if _tsr_device.startswith("cuda") else 8192
        _tsr_model.renderer.set_chunk_size(chunk_size)
        _tsr_model.to(_tsr_device)
        _TSR_READY = True
        print(f"  → Cihaz  : {_tsr_device}  |  chunk={chunk_size}")
        return True
    except Exception as e:
        print(f"  ✖ TripoSR yüklenemedi: {e}")
        return False


def _bake_and_export(mesh, scene_code, glb_path: Path, texture_resolution: int = 1024):
    """UV atlas bake → GLB. Başarısız olursa exception fırlatır."""
    from tsr.bake_texture import bake_texture

    result = bake_texture(mesh, _tsr_model, scene_code, texture_resolution)

    new_verts = mesh.vertices[result["vmapping"]]
    new_faces = result["indices"]
    uvs       = result["uvs"]

    colors_np   = np.clip(result["colors"], 0.0, 1.0)
    colors_u8   = (colors_np * 255).astype(np.uint8)
    tex_img     = Image.fromarray(colors_u8, "RGBA")

    new_mesh = trimesh.Trimesh(vertices=new_verts, faces=new_faces, process=False)
    new_mesh.visual = trimesh.visual.TextureVisuals(
        uv=uvs,
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex_img),
    )
    new_mesh.export(str(glb_path))


def generate_3d_local(image_path: Path) -> dict:
    t0 = time.time()
    image_path = Path(image_path)
    print(f"\n┌─ Stage 2: TripoSR 3D Mesh Üretimi")
    print(f"│  Girdi  : {image_path.name}")

    stem    = image_path.stem.replace("_processed", "")
    out_dir = RAW_DIR / f"mesh_{stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not _try_load_tsr():
        raise RuntimeError("TripoSR AI modeli yüklenemedi. Pipeline durduruldu.")

    img = Image.open(str(image_path)).convert("RGBA")
    try:
        from tsr.utils import resize_foreground
        img = resize_foreground(img, 0.85)
    except Exception as e:
        print(f"│  ! resize_foreground atlandı: {e}")

    img_np      = np.array(img).astype(np.float32) / 255.0
    img_rgb_np  = img_np[:, :, :3] * img_np[:, :, 3:4] + (1.0 - img_np[:, :, 3:4]) * 0.5
    img_rgb     = Image.fromarray((img_rgb_np * 255.0).astype(np.uint8))

    print(f"│  Çözünürlük: {TRIPOSR_MC_RESOLUTION}  |  Cihaz: {_tsr_device}")

    with torch.no_grad():
        scene_codes = _tsr_model.forward([img_rgb], device=_tsr_device)
        meshes = _tsr_model.extract_mesh(
            scene_codes, has_vertex_color=True, resolution=TRIPOSR_MC_RESOLUTION
        )

    mesh = meshes[0]
    print(f"│  Mesh   : {len(mesh.vertices):,} vertex  /  {len(mesh.faces):,} yüz")

    glb_path = out_dir / f"{stem}.glb"

    try:
        _bake_and_export(mesh, scene_codes[0], glb_path, texture_resolution=1024)
        print(f"│  Texture: UV atlas bake ✔")
    except Exception as e:
        print(f"│  Texture: vertex renk (bake atlandı — {type(e).__name__})")
        mesh.export(str(glb_path))

    size = glb_path.stat().st_size
    elapsed = time.time() - t0
    print(f"│  GLB    : {size // 1024} KB  |  Süre: {elapsed:.1f}s")
    print(f"└─ ✔ Stage 2 tamamlandı")

    return {
        "glb_path": glb_path,
        "provider": "triposr",
        "device":   _tsr_device,
    }


async def generate_3d(image_path: Path, provider_chain=None) -> dict:
    return generate_3d_local(image_path)


if __name__ == "__main__":
    import asyncio
    img = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("input/test_sword_processed.png")
    r   = asyncio.run(generate_3d(img))
    s   = r["glb_path"].stat().st_size
    print(f"\n[DONE] {r['glb_path'].name}  |  {s} bayt  |  {s // 1024} KB")
