"""
Stage 3+4 — Optimizer & Exporter (v4 — sade)
=============================================
- Raw OBJ'yi yükle + gerekirse decimate
- FINAL_DIR'e temiz OBJ yaz (elle, trimesh export yok)
- Texture'ı kopyala
- JSON rapor üret
"""

import json
import shutil
from pathlib import Path

import numpy as np

from scrapers.ugc_stages.config import OPT_DIR, FINAL_DIR, ROBLOX_LIMITS


def _read_obj(path: Path):
    """Basit OBJ okuyucu — sadece v ve f satırlarını alır."""
    verts, faces = [], []
    with open(str(path), "r", encoding="utf-8", errors="replace") as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("v "):
                parts = line.split()
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("f "):
                parts = line.split()
                # face: "1 2 3" ya da "1/x 2/x 3/x" formatı
                idx = []
                for p in parts[1:4]:
                    idx.append(int(p.split("/")[0]) - 1)  # 1-tabanlı → 0-tabanlı
                faces.append(idx)
    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32)


def _write_obj(verts, faces, path: Path):
    """Trimesh kullanmadan OBJ yazar."""
    lines = ["# ezgg optimizer output\n"]
    for v in verts:
        lines.append(f"v {v[0]:.5f} {v[1]:.5f} {v[2]:.5f}\n")
    for f in faces:
        lines.append(f"f {int(f[0])+1} {int(f[1])+1} {int(f[2])+1}\n")
    with open(str(path), "w", encoding="utf-8") as fp:
        fp.writelines(lines)
    return path.stat().st_size


def run_blender_optimizer(
    mesh_path: Path,
    texture_path,
    asset_type: str = "accessory",
    stem: str = "output",
) -> dict:
    from scrapers.ugc_stages.config import BLENDER_EXECUTABLE, SCRIPTS_DIR, OPT_DIR, FINAL_DIR, ROBLOX_LIMITS
    import subprocess
    import shutil

    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    OPT_DIR.mkdir(parents=True, exist_ok=True)

    limits  = ROBLOX_LIMITS.get(asset_type, ROBLOX_LIMITS["accessory"])
    max_tri = limits["max_triangles"]
    target  = limits["target_triangles"]

    print(f"\n[*] Stage 3-4: Optimize & Export")
    print(f"    Hedef: <{target}  |  Limit: {max_tri}")

    output_obj = FINAL_DIR / f"{stem}_roblox.obj"
    output_png = FINAL_DIR / f"{stem}_albedo.png"
    report_json = OPT_DIR / "report.json"

    # Blender script yolu
    script_path = SCRIPTS_DIR / "roblox_optimizer.py"

    blender_success = False
    
    # Blender çalıştırılabilir durumdaysa dene
    if BLENDER_EXECUTABLE and BLENDER_EXECUTABLE != "blender" and Path(BLENDER_EXECUTABLE).exists():
        cmd = [
            BLENDER_EXECUTABLE,
            "--background",
            "--python",
            str(script_path),
            "--",
            str(mesh_path),
            str(output_obj),
            str(output_png),
            asset_type,
            str(report_json)
        ]
        print(f"   [blender] Çalıştırılıyor: {' '.join(cmd)}")
        try:
            # 90 saniye zaman aşımı (baking işlemi sürebilir)
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True, timeout=90)
            print("   [blender] Başarıyla tamamlandı.")
            print(res.stdout)
            blender_success = True
        except Exception as e:
            print(f"   [blender] Hata oluştu (Yedek plana geçiliyor): {e}")
            if hasattr(e, 'stdout') and e.stdout:
                print(e.stdout)
            if hasattr(e, 'stderr') and e.stderr:
                print(e.stderr)

    # Blender başarısız olduysa veya yoksa Python yedek planını çalıştır
    if not blender_success:
        print("   [fallback] Python decimation yedek planı devrede...")
        mesh_path = Path(mesh_path)
        verts, faces = _read_obj(mesh_path)
        print(f"   [load] {len(verts)}v / {len(faces)}f")

        if len(verts) == 0 or len(faces) == 0:
            raise RuntimeError(f"Mesh boş: {mesh_path}")

        if len(faces) > max_tri:
            ratio = 1.0 - target / len(faces)
            try:
                import fast_simplification
                pts_out, faces_out = fast_simplification.simplify(
                    verts.astype(np.float64),
                    faces.astype(np.int32),
                    target_reduction=ratio,
                )
                verts = pts_out.astype(np.float32)
                faces = faces_out.astype(np.int32)
                print(f"   [decimate] → {len(verts)}v / {len(faces)}f")
            except Exception as ex:
                print(f"   [!] Decimasyon atlandı: {ex}")

        size = _write_obj(verts, faces, output_obj)
        print(f"   [export] {output_obj.name} ({size//1024} KB)")

        # Düz texture kopyala
        if texture_path and Path(texture_path).exists():
            shutil.copy2(texture_path, output_png)
            print(f"   [texture] {output_png.name}")

        # Basit Rapor yaz
        report = {
            "asset_type":       asset_type,
            "triangle_count":   int(len(faces)),
            "vertex_count":     int(len(verts)),
            "roblox_limit":     max_tri,
            "within_limit":     len(faces) <= max_tri,
            "file_size_bytes":  size,
        }
        with open(report_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    textures = []
    if output_png.exists():
        textures.append(output_png)

    return {
        "fbx_path":    output_obj,
        "textures":    textures,
        "report_path": report_json,
    }
