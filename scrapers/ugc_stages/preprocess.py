"""
Stage 1 — Görsel Ön İşleme
============================
• Arka planı kaldırır (rembg / isnet-general-use)
• Görseli normalize eder (boyut, renk uzayı, merkez hizalama)
• PNG RGBA formatında temiz görsel üretir
"""

try:
    import cv2  # noqa: F401 — opsiyonel, pipeline'da kullanılmıyor
except ImportError:
    cv2 = None
import numpy as np
from pathlib import Path
from PIL import Image, ImageOps
import io

try:
    from rembg import remove, new_session
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    print("⚠️  rembg bulunamadı. 'pip install rembg' ile kur.")

from scrapers.ugc_stages.config import REMBG_MODEL, INPUT_DIR

# ─── Sabitler ────────────────────────────────────────────────────────────────
TARGET_SIZE = (1024, 1024)   # AI modeline gönderilecek boyut
MIN_SIZE    = (256, 256)     # Kabul edilebilir minimum boyut


def load_image(image_path: str | Path) -> Image.Image:
    """Görseli yükler ve RGB'ye dönüştürür."""
    img = Image.open(str(image_path))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def remove_background(img: Image.Image, model: str = REMBG_MODEL) -> Image.Image:
    """
    rembg ile arka planı kaldırır.
    Sonuç: RGBA modunda, şeffaf arka planlı görsel.
    """
    if not REMBG_AVAILABLE:
        print("│  ! rembg yok, arka plan kaldırma atlandı.")
        return img.convert("RGBA")

    session = new_session(model)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    result_bytes = remove(img_bytes.read(), session=session)
    result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    print(f"│  Arka plan kaldırıldı ✔  ({model})")
    return result


def center_crop_subject(img: Image.Image, padding: float = 0.08) -> Image.Image:
    """
    Alfa kanalını kullanarak nesneyi bulur ve sıkıştırılmış bounding box etrafında
    kırpar. padding: kenar boşluğu oranı (0.08 = %8).
    """
    if img.mode != "RGBA":
        return img

    alpha = np.array(img.split()[-1])
    coords = np.argwhere(alpha > 10)   # neredeyse şeffaf pikselleri atla

    if coords.size == 0:
        return img  # nesne bulunamadı, olduğu gibi döndür

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)

    w = x1 - x0
    h = y1 - y0
    pad_x = int(w * padding)
    pad_y = int(h * padding)

    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(img.width,  x1 + pad_x)
    y1 = min(img.height, y1 + pad_y)

    cropped = img.crop((x0, y0, x1, y1))

    side = max(cropped.width, cropped.height)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset_x = (side - cropped.width)  // 2
    offset_y = (side - cropped.height) // 2
    square.paste(cropped, (offset_x, offset_y))

    print(f"│  Nesne hizalandı ✔  ({square.size[0]}×{square.size[1]})")
    return square


def resize_for_model(img: Image.Image, size: tuple = TARGET_SIZE) -> Image.Image:
    """Görseli AI modeline uygun boyuta getirir (Lanczos resampling)."""
    resized = img.resize(size, Image.LANCZOS)
    print(f"│  Boyut    : {resized.size[0]}×{resized.size[1]} ✔")
    return resized


def validate_image(img: Image.Image) -> bool:
    """Temel geçerlilik kontrolü."""
    if img.width < MIN_SIZE[0] or img.height < MIN_SIZE[1]:
        print(f"│  ✖ Görsel çok küçük: {img.size}  (min: {MIN_SIZE})")
        return False
    return True


def preprocess(image_path: str | Path, output_dir: Path = INPUT_DIR) -> Path:
    """
    Tam ön işleme pipeline'ı.
    Returns: İşlenmiş PNG dosyasının yolu.
    """
    image_path = Path(image_path)
    print(f"\n┌─ Stage 1: Görsel Ön İşleme")
    print(f"│  Girdi  : {image_path.name}")

    img = load_image(image_path)
    print(f"│  Boyut  : {img.size[0]}×{img.size[1]}  mod: {img.mode}")

    if not validate_image(img):
        raise ValueError(f"Geçersiz görsel boyutu: {img.size}")

    img = remove_background(img)
    img = center_crop_subject(img)
    img = resize_for_model(img)

    output_path = output_dir / f"{image_path.stem}_processed.png"
    img.save(str(output_path), format="PNG")
    print(f"│  Çıktı  : {output_path.name}")
    print(f"└─ ✔ Stage 1 tamamlandı")
    return output_path


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "input/test.png"
    out = preprocess(src)
    print(f"\n✅ Stage 1 çıktısı: {out}")
