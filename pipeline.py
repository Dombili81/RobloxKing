"""
pipeline.py — Roblox outfit TikTok video üretim pipeline'ı.

Kullanım:
  python pipeline.py --shirt shirt.png --pants pants.png --name "Naruto Fit" --price 5
  python pipeline.py --batch-dir tmp/ --engine pil
  python pipeline.py --shirt s.png --pants p.png --engine blender --group "MyGroup"
"""
import argparse
import json
import os
import random
import re
import shutil
import sys
from scrapers.utils import Logger


# ── Config ──────────────────────────────────────────────────────────────────
DEFAULTS = {
    "engine": "auto",
    "output": {"output_dir": "output", "duration_seconds": 15},
    "audio": {"source_dir": "tempvid"},
}


def load_video_config(path: str = "config_video.json") -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        # Shallow merge top-level keys; nested dicts also merged one level
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


# ── Engine dispatch ──────────────────────────────────────────────────────────
def _get_composer(engine: str, cfg: dict):
    """
    engine: "auto" | "pil" | "blender"
    Döner: (composer_obj, use_blender: bool)
    """
    if engine in ("blender", "auto"):
        try:
            from scrapers.blender_video_composer import BlenderVideoComposer
            bvc = BlenderVideoComposer(cfg)
            if bvc.is_available():
                return bvc, True
        except ImportError:
            pass
        if engine == "blender":
            Logger.warn("Blender bulunamadı, PIL motoru kullanılıyor.")

    from scrapers.video_composer import VideoComposer
    return VideoComposer(), False


def run_single(
    shirt_path: str,
    pants_path: str,
    item_name:  str,
    price:      int,
    group_name: str,
    cfg:        dict,
    output_dir: str = None,
    engine:     str = "auto",
) -> str:
    composer, is_blender = _get_composer(engine, cfg)
    out_dir = output_dir or cfg.get("output", {}).get("output_dir", "output")
    os.makedirs(out_dir, exist_ok=True)

    if is_blender:
        raw = composer.compose(shirt_path, pants_path, item_name, price, group_name)
    else:
        raw = composer.compose_from_textures(shirt_path, pants_path, item_name, price, group_name)

    uid = f"{os.getpid()}_{random.randint(1000, 9999)}"
    final = os.path.join(out_dir, f"final_{uid}.mp4")
    shutil.move(raw, final)
    return final


# ── Batch discovery ──────────────────────────────────────────────────────────
def discover_pairs(batch_dir: str) -> list:
    """
    Klasördeki PNG dosyalarından shirt/pants çiftlerini bulur.
    Desteklenen isim kalıpları:
      shirt_<stem>.png  +  pants_<stem>.png
      <stem>_shirt.png  +  <stem>_pants.png
    """
    files = [f for f in os.listdir(batch_dir) if f.lower().endswith(".png")]
    pairs = {}

    for f in files:
        name = os.path.splitext(f)[0].lower()
        m = re.match(r"^shirt[_\-](.+)$", name)
        if m:
            stem = m.group(1)
            pairs.setdefault(stem, {})["shirt"] = os.path.join(batch_dir, f)
            continue
        m = re.match(r"^pants[_\-](.+)$", name)
        if m:
            stem = m.group(1)
            pairs.setdefault(stem, {})["pants"] = os.path.join(batch_dir, f)
            continue
        m = re.match(r"^(.+)[_\-]shirt$", name)
        if m:
            stem = m.group(1)
            pairs.setdefault(stem, {})["shirt"] = os.path.join(batch_dir, f)
            continue
        m = re.match(r"^(.+)[_\-]pants$", name)
        if m:
            stem = m.group(1)
            pairs.setdefault(stem, {})["pants"] = os.path.join(batch_dir, f)

    result = []
    for stem, p in pairs.items():
        if "shirt" in p and "pants" in p:
            result.append((p["shirt"], p["pants"], stem))
    return result


def run_batch(batch_dir: str, price: int, group_name: str, cfg: dict, engine: str) -> list:
    pairs = discover_pairs(batch_dir)
    if not pairs:
        Logger.warn(f"{batch_dir} içinde shirt/pants çifti bulunamadı.")
        return []

    outputs = []
    for shirt, pants, stem in pairs:
        name = stem.replace("_", " ").replace("-", " ").title()
        Logger.info(f"İşleniyor: {name} ({shirt}, {pants})")
        try:
            out = run_single(shirt, pants, name, price, group_name, cfg, engine=engine)
            Logger.success(f"Tamamlandı: {out}")
            outputs.append(out)
        except Exception as e:
            Logger.error(f"HATA ({name}): {e}")

    return outputs


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Roblox outfit TikTok video üretim pipeline'ı"
    )
    p.add_argument("--shirt",      help="Shirt texture PNG yolu")
    p.add_argument("--pants",      help="Pants texture PNG yolu")
    p.add_argument("--name",       default="Roblox Outfit", help="Kıyafet adı")
    p.add_argument("--price",      type=int, default=5,     help="Fiyat (Robux)")
    p.add_argument("--group",      default="Roblox Group",  help="Grup adı")
    p.add_argument("--output",     help="Çıktı dizini (varsayılan: output/)")
    p.add_argument("--batch-dir",  help="Toplu üretim için PNG klasörü")
    p.add_argument(
        "--engine",
        choices=["auto", "pil", "blender"],
        default="auto",
        help="Render motoru (varsayılan: auto)",
    )
    p.add_argument("--config",     default="config_video.json", help="Config dosyası yolu")
    return p.parse_args()


def main():
    args = parse_args()
    cfg  = load_video_config(args.config)

    if args.batch_dir:
        outputs = run_batch(
            args.batch_dir,
            price=args.price,
            group_name=args.group,
            cfg=cfg,
            engine=args.engine,
        )
        Logger.success(f"{len(outputs)} video üretildi.")
        for o in outputs:
            print(f"  → {o}")
    else:
        if not args.shirt or not args.pants:
            Logger.error("--shirt ve --pants veya --batch-dir belirtilmeli.")
            sys.exit(1)
        out = run_single(
            shirt_path=args.shirt,
            pants_path=args.pants,
            item_name=args.name,
            price=args.price,
            group_name=args.group,
            cfg=cfg,
            output_dir=args.output,
            engine=args.engine,
        )
        Logger.success(f"Video hazır: {out}")


if __name__ == "__main__":
    main()
