"""
video_composer.py — Roblox outfit tanıtım videosu üretir (1080x1920, TikTok).

Pipeline:
  1. RobloxRenderer → karakterin kıyafeti giydiği render (fallback: shirt texture)
  2. PIL → koyu neon gradient arka plan + sparkle noktalar + neon glow metin PNG'leri
  3. ffmpeg → karakter bounce+swing animasyonu, neon metin fade+zoom overlay
     Ses: tempvid/ klasöründen ilk .mp4'ün sesi (yoksa sessiz)
"""
import os
import re
import math
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FFMPEG      = "ffmpeg"
TMP_DIR     = "tmp"
TEMPVID_DIR = "tempvid"
TARGET_W    = 1080
TARGET_H    = 1920
TARGET_SECS = 15

_MAIN_CALLS = [
    "🔥 NEW DROP",
    "LIMITED STYLE",
    "ROBLOX OUTFIT IDEA",
    "RATE THIS FIT 1-10",
    "WOULD YOU WEAR THIS?",
    "RATE THIS FIT ⭐",
]


class VideoComposer:

    # ── Ana metod (Roblox asset ID ile) ─────────────────────────────────────
    def compose(
        self,
        thumbnail_path: str,
        item_name:      str,
        price:          int,
        group_name:     str = "Roblox Group",
        shirt_id:       str = None,
        pants_id:       str = None,
        cookie:         str = None,
        group_id:       int = None,
    ) -> str:
        os.makedirs(TMP_DIR, exist_ok=True)
        uid = f"{os.getpid()}_{random.randint(1000, 9999)}"

        char_png  = self._get_char_render(shirt_id, pants_id, thumbnail_path, cookie, uid)
        bg_png    = self._gen_background(uid)
        texts     = self._gen_neon_texts(item_name, price, group_name, uid)
        audio_src = self._find_audio()

        group_icon_png = None
        gi_texts       = None
        if group_id:
            group_icon_png = self._fetch_group_icon(group_id, uid)
        if group_icon_png:
            gi_texts = self._gen_group_intro_texts(group_name, uid)

        output = os.path.join(TMP_DIR, f"tiktok_{uid}.mp4")
        try:
            self._run_ffmpeg(bg_png, char_png, texts, audio_src, output,
                             group_icon_png=group_icon_png, gi_texts=gi_texts)
            return output
        finally:
            cleanup = [bg_png] + list(texts)
            if group_icon_png:
                cleanup.append(group_icon_png)
            if gi_texts:
                cleanup.extend(gi_texts)
            if char_png != thumbnail_path:
                cleanup.append(char_png)
            for p in cleanup:
                try:
                    os.remove(p)
                except Exception:
                    pass

    # ── Ana metod (PNG texture dosyaları ile) ────────────────────────────────
    def compose_from_textures(
        self,
        shirt_png:  str,
        pants_png:  str,
        item_name:  str,
        price:      int,
        group_name: str = "Roblox Group",
    ) -> str:
        """
        Önce Three.js/Playwright ile gerçek 3D animasyon dener.
        Playwright yoksa Roblox API render → statik karakter fallback kullanır.
        """
        os.makedirs(TMP_DIR, exist_ok=True)
        uid = f"{os.getpid()}_{random.randint(1000, 9999)}"
        output = os.path.join(TMP_DIR, f"tiktok_{uid}.mp4")

        # ── Yol 1: Three.js 3D animasyon ────────────────────────────────────
        try:
            from scrapers.threejs_renderer import ThreeJSRenderer
            renderer = ThreeJSRenderer()
            if renderer.is_available():
                raw_3d = os.path.join(TMP_DIR, f"3d_{uid}.mp4")
                renderer.render(shirt_png, pants_png, raw_3d,
                                fps=30, duration=TARGET_SECS,
                                width=TARGET_W, height=TARGET_H)
                texts     = self._gen_neon_texts(item_name, price, group_name, uid)
                audio_src = self._find_audio()
                try:
                    self._run_ffmpeg_on_video(raw_3d, texts, audio_src, output)
                    return output
                finally:
                    for p in list(texts) + [raw_3d]:
                        try: os.remove(p)
                        except Exception: pass
        except Exception as e:
            print(f"[VideoComposer] Three.js render başarısız ({e}), fallback...")

        # ── Yol 2: Roblox API veya R6 avatar (statik) ───────────────────────
        char_png  = self._build_char_from_textures(shirt_png, pants_png, uid)
        bg_png    = self._gen_background(uid)
        texts     = self._gen_neon_texts(item_name, price, group_name, uid)
        audio_src = self._find_audio()
        try:
            self._run_ffmpeg(bg_png, char_png, texts, audio_src, output)
            return output
        finally:
            cleanup = [bg_png, char_png] + list(texts)
            for p in cleanup:
                try: os.remove(p)
                except Exception: pass

    # ── 1a. Roblox API karakter render ───────────────────────────────────────
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

    # ── 1b. Texture PNG'lerinden karakter görüntüsü ───────────────────────────
    def _build_char_from_textures(self, shirt_png: str, pants_png: str, uid: str) -> str:
        """
        1. Önce PNG dosya adından Roblox asset ID çıkarmaya çalış →
           Başarılı olursa Roblox Thumbnails API ile gerçek karakter render'ı indir.
        2. Başarısız olursa: Roblox R6 avatar silüeti çiz, shirt/pants dominant
           renkleriyle boyayıp kıyafet izlenimi ver.
        """
        char_sz = int(TARGET_W * 0.78)

        # ── Roblox API üzerinden karakter render dene ───────────────────────
        shirt_id = self._extract_roblox_id(shirt_png)
        pants_id = self._extract_roblox_id(pants_png)
        if shirt_id:
            try:
                from scrapers.roblox_renderer import RobloxRenderer
                rr = RobloxRenderer()
                path, _ = rr.get_outfit_render(shirt_id, pants_id, size="420x420")
                if path and os.path.exists(path):
                    # Roblox'tan gelen render'ı beyaz arka plan kaldırarak döndür
                    img = Image.open(path).convert("RGBA").resize((char_sz, char_sz), Image.LANCZOS)
                    out = os.path.join(TMP_DIR, f"char_{uid}.png")
                    img.save(out, "PNG")
                    return out
            except Exception:
                pass

        # ── Fallback: Roblox R6 avatar silüeti çiz ──────────────────────────
        return self._draw_r6_avatar(shirt_png, pants_png, char_sz, uid)

    @staticmethod
    def _extract_roblox_id(path: str) -> str | None:
        """Dosya adındaki ilk 7-13 basamaklı sayıyı Roblox asset ID olarak döndür."""
        name = os.path.splitext(os.path.basename(path))[0]
        # _ veya başlangıç/bitiş ile sınırlı 7-13 haneli sayılar
        m = re.search(r"(?:^|[_\-])(\d{7,13})(?=[_\-]|$)", name)
        if m:
            return m.group(1)
        # Sadece rakamlardan oluşan dosya adı (örn: 6764794692.png)
        if re.fullmatch(r"\d{7,13}", name):
            return name
        return None

    def _draw_r6_avatar(self, shirt_png: str, pants_png: str, char_sz: int, uid: str) -> str:
        """
        PIL ile Roblox R6 avatar silüeti çizer.
        Shirt/pants dominant renklerini alıp vücuda uygular; beyaz arka plan.
        """
        shirt_col = self._dominant_color(shirt_png, default=(100, 140, 220))
        pants_col = self._dominant_color(pants_png, default=(60, 80, 160))
        skin_col  = (255, 200, 140)
        outline   = (30, 30, 30)

        # Çizim alanı: kare, şeffaf arka plan
        W = H = char_sz
        img  = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)

        # Oranlar (char_sz birim sisteminde)
        cx    = W // 2
        scale = W / 400.0   # referans genişlik 400px

        def sc(v):
            return int(v * scale)

        # ── Vücut parçaları (R6 proporsiyon, önden görünüm) ──────────────────
        # Kafa
        head_w, head_h = sc(100), sc(100)
        head_y = sc(30)
        draw.rounded_rectangle(
            [cx - head_w//2, head_y, cx + head_w//2, head_y + head_h],
            radius=sc(12), fill=skin_col, outline=outline, width=sc(3),
        )
        # Gözler
        ey = head_y + sc(38)
        for ex in [cx - sc(22), cx + sc(22)]:
            draw.ellipse([ex - sc(8), ey - sc(8), ex + sc(8), ey + sc(8)],
                         fill=(30, 30, 30))
            draw.ellipse([ex - sc(3), ey - sc(10), ex + sc(1), ey - sc(5)],
                         fill=(255, 255, 255))
        # Gülümseme
        draw.arc([cx - sc(20), ey + sc(8), cx + sc(20), ey + sc(28)],
                 start=10, end=170, fill=outline, width=sc(3))

        # Gövde (shirt rengi)
        torso_w, torso_h = sc(120), sc(130)
        torso_y = head_y + head_h + sc(8)
        draw.rectangle(
            [cx - torso_w//2, torso_y, cx + torso_w//2, torso_y + torso_h],
            fill=shirt_col, outline=outline, width=sc(3),
        )
        # Yaka çizgisi
        draw.line([(cx - sc(20), torso_y), (cx, torso_y + sc(20)),
                   (cx + sc(20), torso_y)], fill=outline, width=sc(3))

        # Kollar (shirt rengi)
        arm_w, arm_h = sc(36), sc(110)
        for side in [-1, 1]:
            ax = cx + side * (torso_w//2 + arm_w//2 + sc(4))
            draw.rectangle(
                [ax - arm_w//2, torso_y + sc(4), ax + arm_w//2, torso_y + arm_h],
                fill=shirt_col, outline=outline, width=sc(3),
            )
            # El
            draw.ellipse(
                [ax - sc(18), torso_y + arm_h - sc(4),
                 ax + sc(18), torso_y + arm_h + sc(30)],
                fill=skin_col, outline=outline, width=sc(2),
            )

        # Bacaklar (pants rengi)
        leg_w, leg_h = sc(52), sc(140)
        legs_y = torso_y + torso_h + sc(4)
        for side, off in [(-1, -sc(4)), (1, sc(4))]:
            lx = cx + side * sc(34)
            draw.rectangle(
                [lx - leg_w//2 + off, legs_y, lx + leg_w//2 + off, legs_y + leg_h],
                fill=pants_col, outline=outline, width=sc(3),
            )
            # Ayak
            shoe_y = legs_y + leg_h - sc(4)
            draw.ellipse(
                [lx - sc(30) + off, shoe_y, lx + sc(30) + off, shoe_y + sc(28)],
                fill=(40, 40, 40), outline=outline, width=sc(2),
            )

        path = os.path.join(TMP_DIR, f"char_{uid}.png")
        img.save(path, "PNG")
        return path

    @staticmethod
    def _dominant_color(png_path: str, default: tuple) -> tuple:
        """PNG'nin en baskın (ortalama ağırlıklı) rengini döndürür."""
        try:
            img   = Image.open(png_path).convert("RGB").resize((80, 80), Image.LANCZOS)
            data  = list(img.getdata())
            r = sum(p[0] for p in data) // len(data)
            g = sum(p[1] for p in data) // len(data)
            b = sum(p[2] for p in data) // len(data)
            # Çok açık veya çok koyu ise varsayılana dön
            brightness = (r + g + b) // 3
            if brightness > 230 or brightness < 15:
                return default
            return (r, g, b)
        except Exception:
            return default

    # ── 2. Ses kaynağı (tempvid'den ilk .mp4) ────────────────────────────────
    def _find_audio(self):
        if not os.path.isdir(TEMPVID_DIR):
            return None
        for f in sorted(os.listdir(TEMPVID_DIR)):
            if f.lower().endswith(".mp4"):
                return os.path.join(TEMPVID_DIR, f)
        return None

    # ── 2b. Roblox grup ikonu indir + dairesel kırp + neon border ────────────
    def _fetch_group_icon(self, group_id: int, uid: str) -> str | None:
        import io
        import json
        import urllib.request
        try:
            url = (
                f"https://thumbnails.roblox.com/v1/groups/icons"
                f"?groupIds={group_id}&size=150x150&format=Png&isCircular=false"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read()).get("data", [])
            if not data or data[0].get("state") != "Completed":
                return None
            img_url = data[0]["imageUrl"]

            req2 = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                raw = Image.open(io.BytesIO(resp2.read())).convert("RGBA")

            size = 300
            raw  = raw.resize((size, size), Image.LANCZOS)

            # Dairesel maske
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            raw.putalpha(mask)

            # Neon glow border: concentric ellipse outlines + Gaussian blur
            border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            bd     = ImageDraw.Draw(border)
            for offset, alpha in [(0, 200), (2, 140), (4, 80)]:
                bd.ellipse(
                    [offset, offset, size - 1 - offset, size - 1 - offset],
                    outline=(0, 200, 255, alpha), width=4,
                )
            border = border.filter(ImageFilter.GaussianBlur(radius=6))

            final = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            final = Image.alpha_composite(final, border)
            final = Image.alpha_composite(final, raw)

            path = os.path.join(TMP_DIR, f"group_icon_{uid}.png")
            final.save(path, "PNG")
            return path

        except Exception as e:
            print(f"[VideoComposer] Grup ikonu alınamadı: {e}")
            return None

    # ── 2c. Grup intro metin PNG'leri ────────────────────────────────────────
    def _gen_group_intro_texts(self, group_name: str, uid: str) -> tuple:
        f_name = self._font(72, bold=True)
        f_sub  = self._font(48, bold=False)
        name_png = self._neon_png(
            group_name[:28],
            f_name,
            text_col=(255, 255, 255),
            glow_col=(0, 200, 255),
            uid=uid, tag="gi_name",
        )
        sub_png = self._neon_png(
            "Join Our Group",
            f_sub,
            text_col=(180, 255, 220),
            glow_col=(0, 160, 120),
            uid=uid, tag="gi_sub",
        )
        return name_png, sub_png

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
        center_glow = center_glow.filter(ImageFilter.GaussianBlur(radius=180))
        rgba = Image.alpha_composite(rgba, center_glow)

        # Sparkle noktalar
        sd = ImageDraw.Draw(rgba)
        for _ in range(220):
            x  = random.randint(0, TARGET_W - 1)
            y  = random.randint(0, TARGET_H - 1)
            sz = random.choice([1, 1, 1, 2, 2, 3])
            a  = random.randint(70, 220)
            col = random.choice([
                (160, 230, 255, a),
                (255, 160, 255, a),
                (140, 255, 200, a),
                (255, 255, 255, a),
            ])
            sd.ellipse([x - sz, y - sz, x + sz, y + sz], fill=col)

        # Metin alanı üst çizgisi (neon yatay çizgi)
        line_y = int(TARGET_H * 0.71)
        for lx in range(TARGET_W):
            a = int(160 * math.sin(math.pi * lx / TARGET_W))
            sd.point((lx, line_y),     fill=(0, 220, 255, a))
            sd.point((lx, line_y + 1), fill=(0, 220, 255, a // 2))

        # Üst neon çizgi (main_call alanı altı)
        line_top = int(TARGET_H * 0.12)
        for lx in range(TARGET_W):
            a = int(120 * math.sin(math.pi * lx / TARGET_W))
            sd.point((lx, line_top),     fill=(255, 80, 200, a))
            sd.point((lx, line_top + 1), fill=(255, 80, 200, a // 2))

        path = os.path.join(TMP_DIR, f"bg_{uid}.png")
        rgba.convert("RGB").save(path, "PNG")
        return path

    # ── 4. Neon metin PNG'leri ────────────────────────────────────────────────
    def _gen_neon_texts(self, name: str, price: int, group: str, uid: str) -> tuple:
        main_call = random.choice(_MAIN_CALLS)
        f_main  = self._font(88, bold=True)
        f_title = self._font(62, bold=True)
        f_price = self._font(64, bold=True)
        f_group = self._font(44, bold=False)

        main_p = self._neon_png(
            main_call,
            f_main,
            text_col=(255, 255, 255),
            glow_col=(0, 200, 255),
            uid=uid, tag="main",
        )
        title = self._neon_png(
            f"{name[:30]}{'…' if len(name) > 30 else ''}",
            f_title,
            text_col=(255, 255, 255),
            glow_col=(180, 0, 255),
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
        return main_p, title, price_p, group_p

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

        # Çok katmanlı blur → neon glow efekti (1080p için büyütülmüş radii)
        for radius in [44, 32, 20, 10]:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            alpha = int(180 * (1 - radius / 50))
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
            [
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/calibrib.ttf",
                "C:/Windows/Fonts/verdanab.ttf",
            ]
            if bold else
            [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/calibri.ttf",
                "C:/Windows/Fonts/verdana.ttf",
            ]
        )
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # ── 5. ffmpeg pipeline (fade+zoom text animasyonu + grup intro) ──────────
    def _run_ffmpeg(self, bg_png, char_png, texts, audio_src, output,
                    group_icon_png=None, gi_texts=None):
        main_png, title_png, price_png, group_png = texts
        dur     = TARGET_SECS
        char_sz = int(TARGET_W * 0.78)  # 840px
        char_cy = int(TARGET_H * 0.38)

        # Metin Y pozisyonları (1920px)
        y_main  = int(TARGET_H * 0.06)
        y_title = int(TARGET_H * 0.73)
        y_price = int(TARGET_H * 0.83)
        y_group = int(TARGET_H * 0.91)

        has_intro = group_icon_png is not None and gi_texts is not None
        t_offset  = 2.5 if has_intro else 0.0

        # Fade+zoom yardımcıları — intro varsa tüm start zamanları +2.5s kaydırılır
        overlays = [
            (main_png,  0.3  + t_offset, 0.60, 0.40, y_main,  "t0"),
            (title_png, 1.2  + t_offset, 0.70, 0.35, y_title, "t1"),
            (price_png, 2.0  + t_offset, 0.75, 0.30, y_price, "t2"),
            (group_png, 3.0  + t_offset, 1.00, 0.40, y_group, "t3"),
        ]

        fc_parts = [
            # Arka plan: scale → 1080x1920
            f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[bg]",

            # Karakter: scale → colorkey → RGBA → swing rotasyonu
            f"[1:v]scale={char_sz}:{char_sz}[cs]",
            f"[cs]colorkey=white:0.30:0.20[ck]",
            f"[ck]format=rgba[cr]",
            f"[cr]rotate="
            f"angle='0.18*sin(2*3.14159*t/1.1)':"
            f"fillcolor=0x00000000:"
            f"ow=rotw(iw):oh=roth(iw)[canim]",

            # Zoom pulse: ±5% scale, 3s periyot
            f"[canim]scale=w='round(iw*(0.95+0.05*sin(2*3.14159*t/3.0))/2)*2':"
            f"h='round(ih*(0.95+0.05*sin(2*3.14159*t/3.0))/2)*2':eval=frame[czoom]",

            # t=7s'de 360° dönüş (0.5s süre)
            f"[czoom]rotate="
            f"angle='if(between(t,7,7.5),(t-7)/0.5*2*3.14159,0)':"
            f"fillcolor=0x00000000:"
            f"ow=rotw(iw):oh=roth(iw)[cspin]",

            # Karakter overlay: yatay ortalı + dikey bounce
            f"[bg][cspin]overlay="
            f"x='(main_w-overlay_w)/2':"
            f"y='{char_cy} - overlay_h/2 + 55*sin(2*3.14159*t/0.85)':"
            f"eval=frame:format=auto[base]",
        ]

        prev = "base"
        for i, (_, t_start, zoom_from, zoom_dur, y_pos, label) in enumerate(overlays):
            inp_idx  = i + 2   # inputs: 0=bg, 1=char, 2=main, 3=title, 4=price, 5=group
            is_last  = i == len(overlays) - 1
            next_lbl = ("pre_intro" if has_intro else "final") if is_last else f"w{i+1}"

            fc_parts.append(
                f"[{inp_idx}:v]"
                f"fade=in:st={t_start}:d={zoom_dur}:alpha=1,"
                f"scale=w='iw*({zoom_from}+{1-zoom_from:.2f}*min(1,(t-{t_start})/{zoom_dur}))':"
                f"h='-1':eval=frame"
                f"[{label}]"
            )
            fc_parts.append(
                f"[{prev}][{label}]overlay="
                f"x='(main_w-overlay_w)/2':"
                f"y={y_pos}:"
                f"eval=frame:format=auto"
                f"[{next_lbl}]"
            )
            prev = next_lbl

        # ── Grup intro overlay'leri (yalnızca has_intro=True ise) ────────────
        if has_intro:
            icon_sz     = 300
            icon_base_y = int(TARGET_H * 0.30)  # 576px — ikonun duracağı Y

            # İkon: alttan kayarak girer (0-0.8s), 2.0-2.5s'de fade out
            fc_parts.append(
                f"[6:v]scale={icon_sz}:{icon_sz},"
                f"fade=in:st=0:d=0.4:alpha=1,"
                f"fade=out:st=2.0:d=0.5:alpha=1[gi_icon]"
            )
            fc_parts.append(
                f"[pre_intro][gi_icon]overlay="
                f"x='(main_w-{icon_sz})/2':"
                f"y='if(lt(t,2.5),{TARGET_H}-({TARGET_H}-{icon_base_y})*min(1,t/0.8),{TARGET_H})':"
                f"eval=frame:format=auto[aft_icon]"
            )

            # Grup adı: fade in 0.8-1.5s, fade out 2.0-2.5s
            fc_parts.append(
                f"[7:v]fade=in:st=0.8:d=0.7:alpha=1,"
                f"fade=out:st=2.0:d=0.5:alpha=1[gi_name_f]"
            )
            fc_parts.append(
                f"[aft_icon][gi_name_f]overlay="
                f"x='(main_w-overlay_w)/2':y={int(TARGET_H * 0.55)}:"
                f"eval=frame:format=auto[aft_name]"
            )

            # Subtitle: fade in 1.5-2.2s, fade out 2.0-2.5s
            fc_parts.append(
                f"[8:v]fade=in:st=1.5:d=0.7:alpha=1,"
                f"fade=out:st=2.0:d=0.5:alpha=1[gi_sub_f]"
            )
            fc_parts.append(
                f"[aft_name][gi_sub_f]overlay="
                f"x='(main_w-overlay_w)/2':y={int(TARGET_H * 0.63)}:"
                f"eval=frame:format=auto[aft_sub]"
            )

            # Beyaz flash geçişi 2.3-2.5s (lavfi white input [9:v])
            fc_parts.append(
                f"[9:v]fade=in:st=2.3:d=0.1:alpha=1,"
                f"fade=out:st=2.4:d=0.1:alpha=1[flash_layer]"
            )
            fc_parts.append(
                f"[aft_sub][flash_layer]overlay="
                f"x=0:y=0:eval=frame:format=auto[final]"
            )

        fc = ";".join(fc_parts)

        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", bg_png,
            "-loop", "1", "-i", char_png,
            "-loop", "1", "-i", main_png,
            "-loop", "1", "-i", title_png,
            "-loop", "1", "-i", price_png,
            "-loop", "1", "-i", group_png,
        ]

        if has_intro:
            gi_name_png, gi_sub_png = gi_texts
            cmd += [
                "-loop", "1", "-i", group_icon_png,  # [6]
                "-loop", "1", "-i", gi_name_png,      # [7]
                "-loop", "1", "-i", gi_sub_png,        # [8]
                "-f", "lavfi", "-i",
                f"color=white:size={TARGET_W}x{TARGET_H}:rate=30",  # [9]
            ]
            audio_base = 10
        else:
            audio_base = 6

        audio_map = []
        if audio_src:
            cmd += ["-stream_loop", "-1", "-i", audio_src]
            audio_map = ["-map", f"{audio_base}:a", "-c:a", "aac", "-b:a", "128k"]

        cmd += [
            "-filter_complex", fc,
            "-map", "[final]",
            *audio_map,
            "-t", str(dur),
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            output,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg başarısız:\n{res.stderr[-1200:]}")

    # ── 5b. Three.js video üzerine metin + ses ekle ───────────────────────────
    def _run_ffmpeg_on_video(self, char_video, texts, audio_src, output):
        """Three.js tam sahne videosu üzerine fade+zoom metin ve ses bindirir."""
        main_png, title_png, price_png, group_png = texts
        dur = TARGET_SECS

        y_main  = int(TARGET_H * 0.06)
        y_title = int(TARGET_H * 0.73)
        y_price = int(TARGET_H * 0.83)
        y_group = int(TARGET_H * 0.91)

        overlays = [
            (main_png,  0.3,  0.60, 0.40, y_main,  "t0"),
            (title_png, 1.2,  0.70, 0.35, y_title, "t1"),
            (price_png, 2.0,  0.75, 0.30, y_price, "t2"),
            (group_png, 3.0,  1.00, 0.40, y_group, "t3"),
        ]

        # Girdi 0: Three.js karaktervideo (tam sahne, arka plan dahil)
        fc_parts = [
            f"[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[base0]",
        ]

        prev = "base0"
        for i, (_, t_start, zoom_from, zoom_dur, y_pos, label) in enumerate(overlays):
            inp_idx = i + 1   # 0=video, 1=main, 2=title, 3=price, 4=group
            next_lbl = "final" if i == len(overlays) - 1 else f"w{i+1}"
            fc_parts.append(
                f"[{inp_idx}:v]"
                f"fade=in:st={t_start}:d={zoom_dur}:alpha=1,"
                f"scale=w='iw*({zoom_from}+{1-zoom_from:.2f}*min(1,(t-{t_start})/{zoom_dur}))':"
                f"h='-1':eval=frame[{label}]"
            )
            fc_parts.append(
                f"[{prev}][{label}]overlay="
                f"x='(main_w-overlay_w)/2':y={y_pos}:"
                f"eval=frame:format=auto[{next_lbl}]"
            )
            prev = next_lbl

        fc = ";".join(fc_parts)

        cmd = [
            FFMPEG, "-y",
            "-i", char_video,
            "-loop", "1", "-i", main_png,
            "-loop", "1", "-i", title_png,
            "-loop", "1", "-i", price_png,
            "-loop", "1", "-i", group_png,
        ]

        audio_map = []
        if audio_src:
            cmd += ["-stream_loop", "-1", "-i", audio_src]
            audio_map = ["-map", "5:a", "-c:a", "aac", "-b:a", "128k"]

        cmd += [
            "-filter_complex", fc,
            "-map", "[final]",
            *audio_map,
            "-t", str(dur),
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            output,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg (video overlay) başarısız:\n{res.stderr[-1200:]}")
