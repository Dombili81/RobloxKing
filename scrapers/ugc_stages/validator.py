"""
Stage 5 — Roblox UGC Validasyon
=================================
Mesh dosyasini ve texture'i dogrudan okur, JSON raporuna dayanmaz.
"""

import json
from pathlib import Path
from PIL import Image
import trimesh

from scrapers.ugc_stages.config import ROBLOX_LIMITS


def validate(
    fbx_path: Path,
    texture_paths: list,
    blender_report_path: Path | None = None,
    asset_type: str = "accessory",
) -> dict:
    limits = ROBLOX_LIMITS.get(asset_type, ROBLOX_LIMITS["accessory"])
    max_tri = limits["max_triangles"]
    max_vtx = limits["max_vertices"]
    max_tex = limits["texture_max_size"]
    max_mb  = limits["max_file_size_mb"]

    result = {
        "asset_type":     asset_type,
        "triangle_count": 0,
        "vertex_count":   0,
        "triangle_limit": max_tri,
        "vertex_limit":   max_vtx,
        "file_size_mb":   0.0,
        "texture_size":   "?",
        "roblox_ready":   False,
        "issues":         [],
    }

    fbx_path = Path(fbx_path)

    # 1. Mesh dosyasini oku
    if not fbx_path.exists():
        result["issues"].append(f"Dosya bulunamadi: {fbx_path}")
        return result

    size_mb = fbx_path.stat().st_size / 1e6
    result["file_size_mb"] = round(size_mb, 2)

    try:
        mesh = trimesh.load(str(fbx_path), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            geoms = list(mesh.geometry.values())
            mesh  = trimesh.util.concatenate(geoms) if geoms else None

        if mesh and len(mesh.faces) > 0:
            result["triangle_count"] = len(mesh.faces)
            result["vertex_count"]   = len(mesh.vertices)
        else:
            result["issues"].append("Mesh bos veya okunamadi")
    except Exception as e:
        result["issues"].append(f"Mesh okuma hatasi: {e}")

    # 2. Texture kontrol
    for tp in texture_paths:
        tp = Path(tp)
        if not tp.exists():
            continue
        try:
            img = Image.open(str(tp))
            w, h = img.size
            result["texture_size"] = f"{w}x{h}"
            if w > max_tex or h > max_tex:
                result["issues"].append(f"Texture cok buyuk: {w}x{h} > {max_tex}x{max_tex}")
        except Exception as e:
            result["issues"].append(f"Texture hatasi: {e}")

    # 3. Limit kontrol
    tri = result["triangle_count"]
    vtx = result["vertex_count"]

    if tri == 0:
        result["issues"].append("Mesh bos (0 triangle)")
    elif tri > max_tri:
        result["issues"].append(f"Triangle limit asildi: {tri} > {max_tri}")

    if vtx > max_vtx:
        result["issues"].append(f"Vertex limit asildi: {vtx} > {max_vtx}")

    if size_mb > max_mb:
        result["issues"].append(f"Dosya cok buyuk: {size_mb:.1f} MB > {max_mb} MB")

    result["roblox_ready"] = (len(result["issues"]) == 0 and tri > 0)
    return result


def print_report(report: dict):
    icon = "✅" if report["roblox_ready"] else "❌"
    print("\n" + "─" * 52)
    print(f"  ROBLOX UGC VALIDASYON RAPORU")
    print("─" * 52)
    print(f"  Asset    : {report['asset_type']}")
    print(f"  Triangle : {report['triangle_count']} / {report['triangle_limit']}")
    print(f"  Vertex   : {report['vertex_count']}  / {report['vertex_limit']}")
    print(f"  Texture  : {report['texture_size']}")
    print(f"  Boyut    : {report['file_size_mb']} MB")
    if report["issues"]:
        for iss in report["issues"]:
            print(f"  ⚠️  {iss}")
    print("─" * 52)
    print(f"  {icon}  SONUC: {'ROBLOX UGC UYUMLU' if report['roblox_ready'] else 'UYUMSUZ'}")
    print("─" * 52 + "\n")
