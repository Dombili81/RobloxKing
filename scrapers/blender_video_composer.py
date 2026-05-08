"""
blender_video_composer.py — Blender tabanlı karakter render + FFmpeg post-process.

BlenderVideoComposer.is_available() → False ise pipeline.py otomatik olarak
VideoComposer (PIL motoru) fallback'ine geçer.
"""
import os
import random
import shutil
import subprocess

from scrapers.utils import Logger
from scrapers.video_composer import VideoComposer

BLENDER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "blender_scripts",
    "render_outfit.py",
)

_COMMON_PATHS = [
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 3.5\blender.exe",
]


class BlenderVideoComposer:

    def __init__(self, config: dict = None):
        self.cfg          = config or {}
        self._blender_exe = self._find_blender()
        self._pil         = VideoComposer()

    # ── Blender keşfi ────────────────────────────────────────────────────────
    def _find_blender(self) -> str | None:
        exe = self.cfg.get("blender", {}).get("executable", "blender")
        if shutil.which(exe):
            return shutil.which(exe)
        for path in _COMMON_PATHS:
            if os.path.exists(path):
                return path
        return None

    def is_available(self) -> bool:
        return self._blender_exe is not None and os.path.exists(BLENDER_SCRIPT)

    # ── Ana metod ────────────────────────────────────────────────────────────
    def compose(
        self,
        shirt_png:  str,
        pants_png:  str,
        item_name:  str,
        price:      int,
        group_name: str = "Roblox Group",
    ) -> str:
        """
        Döner: tmp/tiktok_*.mp4 yolu
        Blender başarısız olursa PIL motoru devreye girer.
        """
        uid = f"{os.getpid()}_{random.randint(1000, 9999)}"
        raw_render = os.path.join("tmp", f"blender_raw_{uid}.mp4")

        try:
            self._render_character(shirt_png, pants_png, raw_render)
        except Exception as e:
            Logger.warn(f"Blender başarısız ({e}), PIL fallback.")
            return self._pil.compose_from_textures(
                shirt_png, pants_png, item_name, price, group_name
            )

        # Blender render başarılı — FFmpeg post-process ile metin/ses ekle
        try:
            return self._post_process(raw_render, item_name, price, group_name, uid)
        finally:
            try:
                os.remove(raw_render)
            except Exception:
                pass

    # ── Blender çağrısı ──────────────────────────────────────────────────────
    def _render_character(self, shirt_png: str, pants_png: str, output: str):
        os.makedirs("tmp", exist_ok=True)
        duration = self.cfg.get("output", {}).get("duration_seconds", 15)
        template = self.cfg.get("blender", {}).get(
            "blend_template", "blender_scripts/roblox_rig.blend"
        )

        cmd = [
            self._blender_exe,
            "--background",
            "--python", BLENDER_SCRIPT,
            "--",
            "--shirt",    os.path.abspath(shirt_png),
            "--pants",    os.path.abspath(pants_png),
            "--output",   os.path.abspath(output),
            "--duration", str(duration),
            "--template", os.path.abspath(template),
        ]

        timeout = duration * 40  # render süresi tahmini
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0 or not os.path.exists(output):
            raise RuntimeError(f"Blender render başarısız:\n{res.stderr[-600:]}")

    # ── FFmpeg post-process (Blender video + metin + ses) ────────────────────
    def _post_process(
        self,
        raw_video:  str,
        item_name:  str,
        price:      int,
        group_name: str,
        uid:        str,
    ) -> str:
        # Metin ve ses üretimi için PIL composer'ın yardımcı metodlarını kullan
        texts     = self._pil._gen_neon_texts(item_name, price, group_name, uid)
        audio_src = self._pil._find_audio()

        main_png, title_png, price_png, group_png = texts
        dur = self.cfg.get("output", {}).get("duration_seconds", 15)

        W = self.cfg.get("output", {}).get("width",  1080)
        H = self.cfg.get("output", {}).get("height", 1920)

        y_main  = int(H * 0.06)
        y_title = int(H * 0.73)
        y_price = int(H * 0.83)
        y_group = int(H * 0.91)

        overlays = [
            (main_png,  0.3,  0.60, 0.40, y_main),
            (title_png, 1.2,  0.70, 0.35, y_title),
            (price_png, 2.0,  0.75, 0.30, y_price),
            (group_png, 3.0,  1.00, 0.40, y_group),
        ]

        fc_parts = [
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[base0]",
        ]

        prev = "base0"
        for i, (_, t_start, zoom_from, zoom_dur, y_pos) in enumerate(overlays):
            inp_idx = i + 1
            next_lbl = "final" if i == len(overlays) - 1 else f"w{i+1}"
            label = f"t{i}"
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
        output = os.path.join("tmp", f"tiktok_{uid}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", raw_video,
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
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            output,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg post-process başarısız:\n{res.stderr[-800:]}")

        return output
