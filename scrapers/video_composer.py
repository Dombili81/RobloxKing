"""
video_composer.py — Roblox outfit tanıtım videosu üretir.

Pipeline:
  1. RobloxRenderer → karakterin kıyafeti giydiği render (fallback: shirt texture)
  2. PIL → koyu neon gradient arka plan + sparkle noktalar + neon glow metin PNG'leri
  3. ffmpeg → karakter bounce+swing animasyonu, neon metin overlay
     Ses: tempvid/ klasöründen ilk .mp4'ün sesi (yoksa sessiz)
"""
import os
import math
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FFMPEG      = "ffmpeg"
TMP_DIR     = "tmp"
TEMPVID_DIR = "tempvid"
TARGET_W    = 576
TARGET_H    = 1024
TARGET_SECS = 15


class VideoComposer:

    # ── Ana metod ────────────────────────────────────────────────────────────
    def compose(
        self,
        thumbnail_path: str,
        item_name:      str,
        price:          int,
        group_name:     str  = "Roblox Group",
        shirt_id:       str  = None,
        pants_id:       str  = None,
        cookie:         str  = None,
    ) -> str:
        os.makedirs(TMP_DIR, exist_ok=True)
        uid = f"{os.getpid()}_{random.randint(1000, 9999)}"

        char_png  = self._get_char_render(shirt_id, pants_id, thumbnail_path, cookie, uid)
        bg_png    = self._gen_background(uid)
        texts     = self._gen_neon_texts(item_name, price, group_name, uid)
        audio_src = self._find_audio()

        output = os.path.join(TMP_DIR, f"tiktok_{uid}.mp4")
        try:
            self._run_ffmpeg(bg_png, char_png, texts, audio_src, output)
            return output
        finally:
            cleanup = [bg_png] + list(texts)
            if char_png != thumbnail_path:
                cleanup.append(char_png)
            for p in cleanup:
                try:
                    os.remove(p)
                except Exception:
                    pass

    # ── 1. Karakter render ────────────────────────────────────────────────────
    def _get_char_render(self, shirt_id, pants_id, fallback, cookie, uid):
        if shirt_id:
            try:
                from scrapers.roblox_renderer import RobloxRenderer
                path, _ = RobloxRenderer(cookie).get_outfit_render(shirt_id, pants_id)
                if path and os.path.exists(path):
                    return path
            except Exception:
                pass
        return fallback

    # ── 2. Ses kaynağı (tempvid'den ilk .mp4) ────────────────────────────────
    def _find_audio(self):
        if not os.path.isdir(TEMPVID_DIR):
            return None
        for f in sorted(os.listdir(TEMPVID_DIR)):
            if f.lower().endswith(".mp4"):
                return os.path.join(TEMPVID_DIR, f)
        return None

    # ── 3. Arka plan PNG ─────────────────────────────────────────────────────
    def _gen_background(self, uid: str) -> str:
        img  = Image.new("RGB", (TARGET_W, TARGET_H))
        draw = ImageDraw.Draw(img)

        # Koyu gradient: üstten alta derin siyah-mor → lacivert
        for y in range(TARGET_H):
            t = y / TARGET_H
            r = int(5  + 10  * t)
            g = int(0  +  8  * t)
            b = int(20 + 28  * t)
            draw.line([(0, y), (TARGET_W - 1, y)], fill=(r, g, b))

        # Merkez parlama (glow)
        rgba = img.convert("RGBA")
        center_glow = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        cg = ImageDraw.Draw(center_glow)
        cg.ellipse(
            [TARGET_W // 6, TARGET_H // 8, 5 * TARGET_W // 6, 6 * TARGET_H // 8],
            fill=(40, 20, 80, 90),
        )
        center_glow = center_glow.filter(ImageFilter.GaussianBlur(radius=100))
        rgba = Image.alpha_composite(rgba, center_glow)

        # Sparkle noktalar
        sd = ImageDraw.Draw(rgba)
        for _ in range(130):
            x  = random.randint(0, TARGET_W - 1)
            y  = random.randint(0, TARGET_H - 1)
            sz = random.choice([1, 1, 1, 2, 2, 3])
            a  = random.randint(70, 220)
            col = random.choice([
                (160, 230, 255, a),   # buz mavisi
                (255, 160, 255, a),   # pembe
                (140, 255, 200, a),   # mint yeşil
                (255, 255, 255, a),   # beyaz
            ])
            sd.ellipse([x - sz, y - sz, x + sz, y + sz], fill=col)

        # Metin alanı üst çizgisi (neon yatay çizgi)
        line_y = int(TARGET_H * 0.71)
        for lx in range(TARGET_W):
            a = int(160 * math.sin(math.pi * lx / TARGET_W))
            sd.point((lx, line_y),     fill=(0, 220, 255, a))
            sd.point((lx, line_y + 1), fill=(0, 220, 255, a // 2))

        path = os.path.join(TMP_DIR, f"bg_{uid}.png")
        rgba.convert("RGB").save(path, "PNG")
        return path

    # ── 4. Neon metin PNG'leri ────────────────────────────────────────────────
    def _gen_neon_texts(self, name: str, price: int, group: str, uid: str) -> tuple:
        f_title = self._font(46, bold=True)
        f_price = self._font(38, bold=True)
        f_group = self._font(24, bold=False)

        title = self._neon_png(
            f"{name[:26]}{'…' if len(name) > 26 else ''}",
            f_title,
            text_col=(255, 255, 255),
            glow_col=(0, 200, 255),
            uid=uid, tag="title",
        )
        price_p = self._neon_png(
            f"💰  {price} Robux",
            f_price,
            text_col=(255, 240, 50),
            glow_col=(255, 140, 0),
            uid=uid, tag="price",
        )
        group_p = self._neon_png(
            f"🛒  {group}",
            f_group,
            text_col=(220, 180, 255),
            glow_col=(160, 0, 255),
            uid=uid, tag="group",
        )
        return title, price_p, group_p

    def _neon_png(
        self, text: str, font, text_col: tuple, glow_col: tuple, uid: str, tag: str
    ) -> str:
        dummy = Image.new("RGBA", (1, 1))
        bbox  = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
        tw    = bbox[2] - bbox[0] + 40
        th    = bbox[3] - bbox[1] + 30
        W     = max(TARGET_W, tw + 60)
        H     = th + 30
        tx    = (W - tw) // 2 + 10
        ty    = 15

        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # Çok katmanlı blur → neon glow efekti
        for radius in [22, 16, 10, 5]:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            alpha = int(180 * (1 - radius / 26))
            ImageDraw.Draw(layer).text(
                (tx, ty), text, font=font, fill=glow_col + (alpha,)
            )
            blurred = layer.filter(ImageFilter.GaussianBlur(radius=radius))
            canvas  = Image.alpha_composite(canvas, blurred)

        # Keskin metin üstte
        ImageDraw.Draw(canvas).text((tx, ty), text, font=font, fill=text_col + (255,))

        path = os.path.join(TMP_DIR, f"neon_{tag}_{uid}.png")
        canvas.save(path, "PNG")
        return path

    def _font(self, size: int, bold: bool) -> ImageFont.FreeTypeFont:
        candidates = (
            ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf"]
            if bold else
            ["C:/Windows/Fonts/arial.ttf",   "C:/Windows/Fonts/calibri.ttf"]
        )
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # ── 5. ffmpeg pipeline ────────────────────────────────────────────────────
    def _run_ffmpeg(self, bg_png, char_png, texts, audio_src, output):
        title_png, price_png, group_png = texts
        dur     = TARGET_SECS
        char_sz = 420

        # Karakterin ekrandaki merkez Y noktası (üst yarı)
        char_cy = int(TARGET_H * 0.37)

        # Metin Y pozisyonları
        y_title = int(TARGET_H * 0.74)
        y_price = int(TARGET_H * 0.83)
        y_group = int(TARGET_H * 0.91)

        fc = (
            # Arka plan: scale → 576x1024
            f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[bg];"

            # Karakter: scale → colorkey (beyaz bg kaldır) → RGBA → sallanma rotasyonu
            f"[1:v]scale={char_sz}:{char_sz}[cs];"
            f"[cs]colorkey=white:0.30:0.20[ck];"
            f"[ck]format=rgba[cr];"
            f"[cr]rotate="
            f"angle='0.18*sin(2*3.14159*t/1.1)':"
            f"fillcolor=0x00000000:"
            f"ow=rotw(iw):oh=roth(iw)[canim];"

            # Karakter overlay: yatay ortalı + dikey bounce (dans efekti)
            f"[bg][canim]overlay="
            f"x='(main_w-overlay_w)/2':"
            f"y='{char_cy} - overlay_h/2 + 38*sin(2*3.14159*t/0.85)':"
            f"eval=frame:format=auto[base];"

            # Neon metin katmanları
            f"[2:v]scale={TARGET_W}:-1[tt];"
            f"[3:v]scale={TARGET_W}:-1[tp];"
            f"[4:v]scale={TARGET_W}:-1[tg];"

            f"[base][tt]overlay=0:{y_title}:enable='gte(t,0.8)'[w1];"
            f"[w1][tp]overlay=0:{y_price}:enable='gte(t,1.8)'[w2];"
            f"[w2][tg]overlay=0:{y_group}:enable='gte(t,3.0)'[final]"
        )

        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", bg_png,        # 0: arka plan
            "-loop", "1", "-i", char_png,       # 1: karakter
            "-loop", "1", "-i", title_png,      # 2: başlık
            "-loop", "1", "-i", price_png,      # 3: fiyat
            "-loop", "1", "-i", group_png,      # 4: grup
        ]

        audio_map = []
        if audio_src:
            cmd += ["-stream_loop", "-1", "-i", audio_src]   # 5: ses
            audio_map = ["-map", "5:a", "-c:a", "aac", "-b:a", "128k"]

        cmd += [
            "-filter_complex", fc,
            "-map", "[final]",
            *audio_map,
            "-t", str(dur),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            output,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg başarısız:\n{res.stderr[-800:]}")
