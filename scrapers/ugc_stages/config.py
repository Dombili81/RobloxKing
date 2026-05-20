"""
ezgg Pipeline — Global Configuration (Lokal Mod)
==================================================
API anahtarı YOKTUR. Her şey lokalda çalışır.
"""

import os
from pathlib import Path

# ─── Proje Yolları ────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent  # scrapers/ugc_stages/
INPUT_DIR   = BASE_DIR / "input"
OUTPUT_DIR  = BASE_DIR / "output"
RAW_DIR     = OUTPUT_DIR / "raw_mesh"
OPT_DIR     = OUTPUT_DIR / "optimized"
FINAL_DIR   = OUTPUT_DIR / "final"
SCRIPTS_DIR = BASE_DIR / "blender_scripts"
MODELS_DIR  = BASE_DIR / "models"         # İndirilen AI model ağırlıkları

for d in [INPUT_DIR, RAW_DIR, OPT_DIR, FINAL_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# GPU otomatik algilama — yoksa CPU kullanilir
import torch
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ─── MiDaS Depth Model Ayarlari ──────────────────────────────────────────────
# MiDaS DPT-Small: ~100 MB, CPU'da ~3-8 saniye, ilk seferinde indirilir
MIDAS_MODEL_TYPE = "DPT_Small"  # DPT_Large (daha iyi) veya MiDaS (kucuk)

# ─── (Opsiyonel) TripoSR Ayarlari ────────────────────────────────────────────
# GPU varsa daha iyi kalite icin kullanilabilir (~1.5 GB model)
TRIPOSR_MODEL_ID      = "stabilityai/TripoSR"
TRIPOSR_MC_RESOLUTION = 256
TRIPOSR_CHUNK_SIZE    = 131072

# ─── Blender Kurulum Yolu ─────────────────────────────────────────────────────
# Blender PATH'te değilse tam yolu gir:
BLENDER_EXECUTABLE = os.getenv("BLENDER_PATH")
if not BLENDER_EXECUTABLE:
    # Windows'ta Blender 4.3 varsayılan yolu
    default_path = r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
    if os.path.exists(default_path):
        BLENDER_EXECUTABLE = default_path
    else:
        BLENDER_EXECUTABLE = "blender"

# ─── rembg Modeli ────────────────────────────────────────────────────────────
REMBG_MODEL = "isnet-general-use"

# ─── Roblox UGC Limitleri ────────────────────────────────────────────────────
ROBLOX_LIMITS = {
    "accessory": {
        "max_triangles":    4_000,
        "max_vertices":     4_000,
        "target_triangles": 3_200,
        "texture_max_size": 1024,
        "max_file_size_mb": 50,
    },
    "mesh_part": {
        "max_triangles":    20_000,
        "max_vertices":     20_000,
        "target_triangles": 15_000,
        "texture_max_size": 1024,
        "max_file_size_mb": 50,
    },
    "bundle": {
        "max_triangles":    10_000,
        "max_vertices":     10_000,
        "target_triangles": 8_000,
        "texture_max_size": 1024,
        "max_file_size_mb": 50,
    },
}
