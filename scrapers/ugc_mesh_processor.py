"""
Sunucu tarafında Blender olmadan UGC mesh/texture işleme (trimesh + Pillow).

Amaç: Katalogdan indirilen mesh + texture üzerinde özgün görünüm için
prosedürel değişiklikler (ölçek, gürültü, ek geometri, basitleştirme, renk).

UYARI — Yükleme / ban riski:
- Başkasının UGC'sini değiştirip yeniden yüklemek Roblox ToS ve telif ihlali riski taşır.
- Pazara yüklemeden önce tamamen özgün içerik üretin; bu pipeline sadece teknik dönüşüm sağlar.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import tempfile
import zipfile
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from scrapers.utils import Logger

try:
    import trimesh

    _HAS_TRIMESH = True
except ImportError:
    trimesh = None  # type: ignore
    _HAS_TRIMESH = False


def _keyword_seed(keyword: str) -> int:
    return int(hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:8], 16)


def _detect_visual_style(keyword: str) -> str:
    k = keyword.lower()
    if any(x in k for x in ("cyber", "neon", "future", "sci", "tech", "holo")):
        return "futuristic"
    if any(x in k for x in ("anime", "kawaii", "manga", "chibi")):
        return "anime"
    if any(x in k for x in ("pastel", "soft", "aesthetic", "dream")):
        return "aesthetic"
    if any(x in k for x in ("dark", "goth", "shadow", "void")):
        return "dark"
    return "balanced"


def _style_texture_params(style: str) -> dict[str, float]:
    """Hue/sat/brightness çarpanları (Pillow ile)."""
    presets = {
        "futuristic": {"hue": 0.08, "sat": 1.25, "bright": 1.05, "contrast": 1.12},
        "anime": {"hue": 0.02, "sat": 1.35, "bright": 1.08, "contrast": 1.05},
        "aesthetic": {"hue": -0.03, "sat": 1.15, "bright": 1.06, "contrast": 1.0},
        "dark": {"hue": 0.0, "sat": 0.85, "bright": 0.88, "contrast": 1.15},
        "balanced": {"hue": 0.0, "sat": 1.1, "bright": 1.0, "contrast": 1.05},
    }
    return presets.get(style, presets["balanced"])


def _process_texture_png(src_path: str, dst_path: str, keyword: str, style: str) -> None:
    """Gradient + HSV + kontrast ile texture'ı belirgin şekilde farklılaştır."""
    img = Image.open(src_path).convert("RGBA")
    rng = random.Random(_keyword_seed(keyword + style))
    w, h = img.size

    grad = Image.new("RGBA", (w, h))
    dr = ImageDraw.Draw(grad)
    c1 = (rng.randint(30, 220), rng.randint(30, 220), rng.randint(30, 220), 140)
    c2 = (rng.randint(30, 220), rng.randint(30, 220), rng.randint(30, 220), 140)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        gc = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        dr.line([(0, y), (w, y)], fill=(r, gc, b, 210))

    grad = grad.filter(ImageFilter.GaussianBlur(radius=max(1, min(w, h) // 90)))
    base = Image.alpha_composite(grad, img)

    params = _style_texture_params(style)
    rgb = base.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(params["sat"])
    rgb = ImageEnhance.Brightness(rgb).enhance(params["bright"])
    rgb = ImageEnhance.Contrast(rgb).enhance(params["contrast"])

    hsv = rgb.convert("HSV")
    h_ch, s_ch, v_ch = hsv.split()
    shift = int(params["hue"] * 255) % 256
    h_ch = h_ch.point(lambda x: (x + shift) % 256)
    rgb_out = Image.merge("HSV", (h_ch, s_ch, v_ch)).convert("RGB")
    r, g, b = rgb_out.split()
    a = base.split()[3]
    Image.merge("RGBA", (r, g, b, a)).save(dst_path, format="PNG")


def _parse_roblox_ascii_mesh(text: str) -> Any | None:
    """Roblox mesh ASCII (version 1.xx) — yüz satırlarını tamsayı üçlü olarak arar."""
    if not _HAS_TRIMESH:
        return None
    stripped = text.strip()
    if not stripped.lower().startswith("version"):
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    i = 1
    try:
        num_faces = int(lines[1].split()[0])
        num_vertices = int(lines[2].split()[0])
        i = 3
    except (IndexError, ValueError):
        try:
            num_vertices = int(lines[1].split()[0])
            num_faces = int(lines[2].split()[0])
            i = 3
        except (IndexError, ValueError):
            return None

    verts: list[list[float]] = []
    for _ in range(num_vertices):
        parts = re.split(r"[\s,]+", lines[i].strip())
        verts.append([float(parts[0]), float(parts[1]), float(parts[2])])
        i += 1

    rest = lines[i:]
    face_triplets: list[tuple[int, int, int]] = []
    for line in rest:
        m = re.match(r"^(\d+)\s+(\d+)\s+(\d+)\s*$", line.strip())
        if not m:
            continue
        face_triplets.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))

    if len(face_triplets) < num_faces:
        return None
    face_triplets = face_triplets[-num_faces:]

    faces: list[list[int]] = []
    for a, b, c in face_triplets:
        if min(a, b, c) >= 1:
            a, b, c = a - 1, b - 1, c - 1
        faces.append([a, b, c])

    return trimesh.Trimesh(
        vertices=np.array(verts, dtype=np.float64),
        faces=np.array(faces, dtype=np.int64),
        process=True,
    )


def _load_trimesh_from_path(mesh_path: str) -> Any | None:
    if not _HAS_TRIMESH:
        return None
    try:
        m = trimesh.load(mesh_path, force="mesh", process=True)
        if isinstance(m, trimesh.Scene):
            geoms = [g for g in m.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not geoms:
                return None
            m = trimesh.util.concatenate(geoms)
        if not isinstance(m, trimesh.Trimesh):
            return None
        return m
    except Exception as e:
        Logger.debug(f"trimesh.load başarısız: {e}")
        return None


def _load_mesh_any(mesh_path: str) -> Any | None:
    """Önce trimesh, sonra raw OBJ bytes, sonra Roblox ASCII."""
    m = _load_trimesh_from_path(mesh_path)
    if m is not None and len(m.faces) > 0:
        return m

    with open(mesh_path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"v "):
        try:
            buf = io.BytesIO(raw)
            m = trimesh.load(buf, file_type="obj", force="mesh", process=True)
            if isinstance(m, trimesh.Trimesh) and len(m.faces) > 0:
                return m
        except Exception:
            pass

    text = raw.decode("utf-8", errors="ignore")
    return _parse_roblox_ascii_mesh(text)


def _target_face_count(seed: int, current: int) -> int:
    """1000–3000 bandına indir (üçgen sayısı artırılamaz)."""
    rng = random.Random(seed)
    if current <= 1000:
        return current
    if current <= 3000:
        return rng.randint(1000, current)
    return rng.randint(1000, 3000)


def _apply_mesh_transforms(mesh: Any, keyword: str, style: str) -> Any:
    """Non-uniform scale, vertex jitter, küyük ek parçalar."""
    rng = random.Random(_keyword_seed(keyword + "_mesh"))
    m = mesh.copy()

    # Merkezle
    m.vertices -= m.vertices.mean(axis=0)

    # Non-uniform scale (silueti değiştir)
    sx = 1.0 + rng.uniform(-0.12, 0.12) + (0.05 if style == "futuristic" else 0)
    sy = 1.0 + rng.uniform(-0.10, 0.14)
    sz = 1.0 + rng.uniform(-0.12, 0.12)
    m.vertices[:, 0] *= sx
    m.vertices[:, 1] *= sy
    m.vertices[:, 2] *= sz

    # Vertex gürültüsü
    noise = rng.uniform(-0.012, 0.012, size=m.vertices.shape)
    m.vertices += noise

    # Küçük dikenler (icosphere)
    n_spikes = rng.randint(3, 7)
    extras = []
    for _ in range(n_spikes):
        idx = rng.randrange(len(m.vertices))
        center = m.vertices[idx].copy()
        nvec = center / (np.linalg.norm(center) + 1e-8)
        center = center + nvec * rng.uniform(0.02, 0.06)
        r = rng.uniform(0.015, 0.04)
        spike = trimesh.creation.icosphere(subdivisions=1, radius=r)
        spike.vertices += center
        extras.append(spike)

    if extras:
        m = trimesh.util.concatenate([m] + extras)

    m.remove_duplicate_faces()
    m.remove_degenerate_faces()
    m.remove_unreferenced_vertices()
    try:
        m.fill_holes()
    except Exception:
        pass

    # Hedef üçgen sayısı
    target = _target_face_count(_keyword_seed(keyword), len(m.faces))
    if len(m.faces) > target:
        try:
            m = m.simplify_quadric_decimation(target)
        except Exception as e:
            Logger.warn(f"Quadric simplify atlandı: {e}")

    m.remove_duplicate_faces()
    m.remove_degenerate_faces()
    m.remove_unreferenced_vertices()
    try:
        m.fix_normals()
    except Exception:
        pass

    # Roblox ölçeği: bounding box max kenar ~ 2.0
    extents = m.extents
    max_e = float(np.max(extents)) + 1e-8
    scale = 2.0 / max_e
    m.vertices *= scale

    # Pivot: tabanı y≈0
    m.vertices[:, 1] -= float(m.bounds[0][1])

    return m


def process_ugc_catalog_zip(zip_path: str, keyword: str) -> str | None:
    """
    İndirilen UGC zip'ini işler; yeni zip yolu döner veya hata durumunda None.
    """
    style = _detect_visual_style(keyword)

    with tempfile.TemporaryDirectory(prefix="ugc_proc_") as tmp:
        raw_dir = os.path.join(tmp, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zin:
            zin.extractall(raw_dir)

        mesh_name = None
        tex_name = None
        for name in os.listdir(raw_dir):
            low = name.lower()
            if low.endswith("_mesh.obj") or (low.endswith(".obj") and "mesh" in low):
                mesh_name = name
            elif low.endswith(".mesh"):
                mesh_name = name
            elif "texture" in low and low.endswith(".png"):
                tex_name = name

        if not mesh_name:
            for name in os.listdir(raw_dir):
                if name.lower().endswith((".obj", ".mesh")):
                    mesh_name = name
                    break

        mesh_path = os.path.join(raw_dir, mesh_name) if mesh_name else None
        tex_path = os.path.join(raw_dir, tex_name) if tex_name else None

        out_mesh_path = os.path.join(tmp, "processed_mesh.obj")
        out_tex_path = os.path.join(tmp, "processed_texture.png")
        out_glb_path = os.path.join(tmp, "processed_model.glb")

        meta: dict[str, Any] = {
            "keyword": keyword,
            "style": style,
            "mesh_processed": False,
            "texture_processed": False,
            "notes": [],
        }

        # Texture
        if tex_path and os.path.isfile(tex_path):
            try:
                _process_texture_png(tex_path, out_tex_path, keyword, style)
                meta["texture_processed"] = True
            except Exception as e:
                Logger.warn(f"Texture işleme hatası: {e}")
                meta["notes"].append(f"texture_error:{e}")

        # Mesh
        processed_mesh = None
        if mesh_path and os.path.isfile(mesh_path):
            try:
                processed_mesh = _load_mesh_any(mesh_path)
            except Exception as e:
                meta["notes"].append(f"mesh_load_error:{e}")

        if processed_mesh is not None and _HAS_TRIMESH:
            try:
                processed_mesh = _apply_mesh_transforms(processed_mesh, keyword, style)
                processed_mesh.export(out_mesh_path)
                try:
                    processed_mesh.export(out_glb_path)
                except Exception as e:
                    meta["notes"].append(f"glb_export:{e}")
                meta["mesh_processed"] = True
                meta["triangle_count"] = int(len(processed_mesh.faces))
                meta["vertex_count"] = int(len(processed_mesh.vertices))
            except Exception as e:
                Logger.error(f"Mesh dönüşüm hatası: {e}")
                meta["notes"].append(f"mesh_process_error:{e}")
        elif not _HAS_TRIMESH:
            meta["notes"].append("trimesh_missing:mesh_skipped_install_trimesh_scipy")

        # Çıktı zip
        base = os.path.splitext(os.path.basename(zip_path))[0]
        out_zip = os.path.join(os.path.dirname(zip_path), f"{base}_processed.zip")

        if not meta.get("texture_processed") and not meta.get("mesh_processed"):
            Logger.warn("UGC işleme: ne mesh ne texture üretilebildi.")
            return None

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zout:
            # Orijinaller (sadece raw/)
            for root, _, files in os.walk(raw_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.relpath(fp, raw_dir)
                    zout.write(fp, arcname=f"original/{arc}")

            if os.path.isfile(out_tex_path):
                zout.write(out_tex_path, arcname="processed/processed_texture.png")
            if os.path.isfile(out_mesh_path):
                zout.write(out_mesh_path, arcname="processed/processed_mesh.obj")
            if os.path.isfile(out_glb_path):
                zout.write(out_glb_path, arcname="processed/processed_model.glb")

            zout.writestr(
                "processed/metadata.json",
                json.dumps(meta, indent=2, ensure_ascii=False),
            )
            zout.writestr(
                "processed/README_LEGAL.txt",
                _legal_readme(),
            )
            zout.writestr(
                "processed/README_PIPELINE.txt",
                _pipeline_readme(),
            )

        Logger.success(f"UGC işlenmiş paket: {out_zip}")
        return out_zip


def _legal_readme() -> str:
    return """\
LEGAL / MODERATION — Roblox UGC
================================

1) Bu paket, Roblox katalogundan indirilen varlıklar üzerinde OTOMATİK dönüşüm içerir.

2) Bu içeriği Creator Marketplace'e veya gruba YÜKLERKEN:
   - Başka yaratıcıların mesh/texture'ını kopyalayıp yeniden yayınlamak ToS ve telif ihlali riski taşır.
   - Moderasyon reddi veya hesap yaptırımı mümkündür.

3) Yayınlanabilir özgün ürün için:
   - Kendi modelinizi ve kendi texture'ınızı oluşturun VEYA
   - Açık lisanslı kaynak kullanın ve lisans şartlarına uyun.

4) Bu yazılım yalnızca teknik işlem sağlar; hukuki uyumluluk kullanıcı sorumluluğundadır.
"""


def _pipeline_readme() -> str:
    return """\
TEKNİK — Blender olmadan sunucu pipeline
========================================

Bu klasörde:
- original/ : İndirilen ham dosyalar
- processed/ : Dönüştürülmüş çıktılar

Mesh:
- Non-uniform ölçek, vertex jitter, ek küçük geometri (spike)
- Üçgen sayısı yaklaşık 1000–3000 aralığına indirgenmeye çalışılır
- Normal yönleri düzeltilir, taban y≈0 olacak şekilde pivot ayarı

Texture:
- Yeni gradient + HSV/brightness/saturation ile stil
- Stil anahtar kelimeden tahmin edilir (anime / futuristic / vb.)

Export:
- processed_mesh.obj — çoğu DCC ve Studio import zincirinde kullanılır
- processed_model.glb — glTF (Studio / araçlar)

FBX:
- Bu sunucu pipeline'ı FBX binary üretmez (Blender SDK gerektirir).
- FBX şart ise: Blender veya Autodesk FBX Converter ile OBJ/GLB'den dönüştürün.

Roblox limitleri için bkz. proje CLAUDE.md (üçgen, texture çözünürlüğü, UV).
"""
