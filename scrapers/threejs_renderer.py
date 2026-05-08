"""
threejs_renderer.py — Playwright + Three.js ile 3D Roblox karakter animasyonu üretir.

Tam 1080x1920 sahne (arka plan + karakter) render edilir; FFmpeg sadece metin+ses ekler.
Playwright/Chromium mevcut değilse False döner; caller VideoComposer fallback kullanır.

UV mapping: Roblox R6 Classic clothing template (585×559 px)
  Shirt torso front:  (99, 9, 97, 105)
  Shirt torso back:   (197, 9, 97, 105)
  Shirt torso right:  (1, 9, 97, 105)
  Shirt torso left:   (295, 9, 97, 105)
  Shirt right arm:    (447, 9, 43, 105) front, (491, 9, 43, 105) back
  Shirt left arm:     (360, 9, 43, 105) front, (404, 9, 43, 105) back
  Pants right leg:    (2, 9, 64, 105)  front, (67, 9, 64, 105) back
  Pants left leg:     (133, 9, 64, 105) front, (198, 9, 64, 105) back
"""
import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from scrapers.utils import Logger

# ─── Three.js sahne HTML şablonu ────────────────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>* { margin:0; padding:0; overflow:hidden; } body { background:#000; }</style>
</head>
<body>
<canvas id="c" width="{W}" height="{H}"></canvas>
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>
<script>
const W = {W}, H = {H};
const FPS = {FPS}, DUR = {DUR}, TOTAL = FPS * DUR;

const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setSize(W, H, false);
renderer.setPixelRatio(1);
renderer.shadowMap.enabled = true;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x04000e);
scene.fog = new THREE.FogExp2(0x06001a, 0.038);

const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 120);
camera.position.set(0, 1.8, 11.5);
camera.lookAt(0, 1.8, 0);

// ── Işıklar ──────────────────────────────────────────────────────────────
const ambient = new THREE.AmbientLight(0xffffff, 2.5);
scene.add(ambient);

const keyLight = new THREE.DirectionalLight(0xffffff, 5.0);
keyLight.position.set(6, 10, 8);
keyLight.castShadow = true;
scene.add(keyLight);

const fillLight = new THREE.DirectionalLight(0xccddff, 2.5);
fillLight.position.set(-5, 4, 5);
scene.add(fillLight);

const rimLight = new THREE.DirectionalLight(0xaaddff, 2.0);
rimLight.position.set(0, 3, -8);
scene.add(rimLight);

const neonBlue = new THREE.PointLight(0x00eeff, 8.0, 22);
scene.add(neonBlue);
const neonPink = new THREE.PointLight(0xff33cc, 8.0, 22);
scene.add(neonPink);
const neonPurple = new THREE.PointLight(0x8800ff, 4.0, 18);
neonPurple.position.set(0, 6, 3);
scene.add(neonPurple);

// ── Arka plan ─────────────────────────────────────────────────────────────
const gridHelper = new THREE.GridHelper(40, 30, 0x0055ff, 0x001133);
gridHelper.position.y = -2.0;
gridHelper.material.opacity = 0.7;
gridHelper.material.transparent = true;
scene.add(gridHelper);

const floorGeo = new THREE.PlaneGeometry(30, 30);
const floorMat = new THREE.MeshStandardMaterial({
  color: 0x050020, roughness: 0.9, metalness: 0.1,
  transparent: true, opacity: 0.85
});
const floor = new THREE.Mesh(floorGeo, floorMat);
floor.rotation.x = -Math.PI / 2;
floor.position.y = -2.0;
floor.receiveShadow = true;
scene.add(floor);

const ringGeo = new THREE.TorusGeometry(4.5, 0.06, 12, 80);
const ringMat = new THREE.MeshBasicMaterial({ color: 0x0088ff });
const ring1 = new THREE.Mesh(ringGeo, ringMat);
ring1.position.set(0, 1.5, -4);
scene.add(ring1);
const ringMat2 = new THREE.MeshBasicMaterial({ color: 0xff0088 });
const ring2 = new THREE.Mesh(new THREE.TorusGeometry(3.2, 0.04, 12, 80), ringMat2);
ring2.position.set(0, 1.5, -4);
ring2.rotation.x = Math.PI / 6;
scene.add(ring2);

const partGeo = new THREE.BufferGeometry();
const partCount = 160;
const pPos = new Float32Array(partCount * 3);
for (let i = 0; i < partCount; i++) {
  pPos[i*3]   = (Math.random() - 0.5) * 14;
  pPos[i*3+1] = Math.random() * 10 - 1;
  pPos[i*3+2] = (Math.random() - 0.5) * 8 - 1;
}
partGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
const partMat = new THREE.PointsMaterial({ color: 0x88ddff, size: 0.07, transparent: true, opacity: 0.75 });
const particles = new THREE.Points(partGeo, partMat);
scene.add(particles);

// ── Roblox R6 UV Mapping ──────────────────────────────────────────────────
// Template size: 585×559 pixels
// Confirmed layout via analysis:
//   LEFT block  x=0-231  (width=232): 4 torso faces, each 58px wide
//     Section order (L→R): Right side, Front, Back, Left side
//   GAP          x=232-357 (transparent)
//   RIGHT block x=358-584 (width=227): 4 arm sections, each ~57px wide
//     Order: R-arm-outer, R-arm-front, L-arm-front, L-arm-outer
//   PANTS: same layout for legs (x=0-231 = right leg 2 faces + left leg 2 faces)
const TW = 585, TH = 559;

const loader = new THREE.TextureLoader();
const shirtBase = loader.load('{SHIRT_URL}');
shirtBase.colorSpace = THREE.SRGBColorSpace;

const pantsBase = loader.load('{PANTS_URL}');
pantsBase.colorSpace = THREE.SRGBColorSpace;

// Clone texture with specific UV region (px,py = top-left in pixels)
function texRegion(base, px, py, pw, ph) {
  const t = base.clone();
  t.needsUpdate = true;
  t.wrapS = THREE.ClampToEdgeWrapping;
  t.wrapT = THREE.ClampToEdgeWrapping;
  t.repeat.set(pw / TW, ph / TH);
  t.offset.set(px / TW, 1.0 - (py + ph) / TH);
  return t;
}

// Build 6-material array — BoxGeometry face order: [+X, -X, +Y, -Y, +Z, -Z]
function buildMats(base, specs, fallbackHex) {
  return specs.map(s => {
    if (!s) return new THREE.MeshStandardMaterial({ color: fallbackHex, roughness: 0.8 });
    return new THREE.MeshStandardMaterial({
      map: texRegion(base, s[0], s[1], s[2], s[3]),
      roughness: 0.65,
      metalness: 0.05
    });
  });
}

const skinMat = new THREE.MeshStandardMaterial({ color: 0xffcc99, roughness: 0.8 });
const shoeMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.7 });
const hairMat = new THREE.MeshStandardMaterial({ color: 0x3d2206, roughness: 0.9 });

// ── Shirt UV regions ───────────────────────────────────────────────────────
// Torso: 4 × 58px sections at y=9, height=105
// Template order L→R: [right-side, front, back, left-side]
const TS = 58; // torso section width
const torsoMats = buildMats(shirtBase, [
  [0*TS, 9, TS, 105],  // +X  character's right side
  [3*TS, 9, TS, 105],  // -X  character's left side
  [1*TS, 0, TS,   9],  // +Y  top strip
  [2*TS, 0, TS,   9],  // -Y  bottom strip
  [1*TS, 9, TS, 105],  // +Z  front face
  [2*TS, 9, TS, 105],  // -Z  back face
], 0x888888);

// Arms: right block (x=358+), 4 sections of 57px
// Order: R-arm-outer, R-arm-front/back, L-arm-front/back, L-arm-outer
const AS = 57; // arm section width
const ARM_X = 358;

// Right upper arm (+X = outer, -X = inner/body side)
const rUArmMats = buildMats(shirtBase, [
  [ARM_X+0*AS, 9, AS, 105],  // +X outer side
  [ARM_X+1*AS, 9, AS, 105],  // -X inner side
  [ARM_X+0*AS, 0, AS,   9],  // +Y top
  [ARM_X+1*AS, 0, AS,   9],  // -Y bottom
  [ARM_X+1*AS, 9, AS, 105],  // +Z front
  [ARM_X+0*AS, 9, AS, 105],  // -Z back
], 0xffcc99);

// Left upper arm (-X = outer, +X = inner/body side)
const lUArmMats = buildMats(shirtBase, [
  [ARM_X+2*AS, 9, AS, 105],  // +X inner side
  [ARM_X+3*AS, 9, AS, 105],  // -X outer side
  [ARM_X+3*AS, 0, AS,   9],  // +Y top
  [ARM_X+2*AS, 0, AS,   9],  // -Y bottom
  [ARM_X+2*AS, 9, AS, 105],  // +Z front
  [ARM_X+3*AS, 9, AS, 105],  // -Z back
], 0xffcc99);

// ── Pants UV regions ───────────────────────────────────────────────────────
// Same layout: left block has legs, x=0-231, section width=58
// Pants section order: Right-leg-outer, Right-leg-front, Left-leg-front, Left-leg-outer
const LS = 58; // leg section width

const rULegMats = buildMats(pantsBase, [
  [0*LS, 9, LS, 105],  // +X outer
  [1*LS, 9, LS, 105],  // -X inner
  [0*LS, 0, LS,   9],  // +Y
  [1*LS, 0, LS,   9],  // -Y
  [1*LS, 9, LS, 105],  // +Z front
  [0*LS, 9, LS, 105],  // -Z back
], 0x333344);

const lULegMats = buildMats(pantsBase, [
  [2*LS, 9, LS, 105],  // +X inner
  [3*LS, 9, LS, 105],  // -X outer
  [3*LS, 0, LS,   9],  // +Y
  [2*LS, 0, LS,   9],  // -Y
  [2*LS, 9, LS, 105],  // +Z front
  [3*LS, 9, LS, 105],  // -Z back
], 0x333344);

// Lower legs: second row of pants template (y=114+)
const rLLegMats = buildMats(pantsBase, [
  [0*LS, 114, LS, 105],  // +X
  [1*LS, 114, LS, 105],  // -X
  [0*LS, 114, LS,   9],  // +Y
  [1*LS, 114, LS,   9],  // -Y
  [1*LS, 114, LS, 105],  // +Z front
  [0*LS, 114, LS, 105],  // -Z back
], 0x333344);

const lLLegMats = buildMats(pantsBase, [
  [2*LS, 114, LS, 105],  // +X
  [3*LS, 114, LS, 105],  // -X
  [3*LS, 114, LS,   9],  // +Y
  [2*LS, 114, LS,   9],  // -Y
  [2*LS, 114, LS, 105],  // +Z front
  [3*LS, 114, LS, 105],  // -Z back
], 0x333344);

// ── R6 Avatar ─────────────────────────────────────────────────────────────
const avatar = new THREE.Group();

function boxMultiMat(w, h, d, materials, px, py, pz) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), materials);
  m.position.set(px, py, pz);
  m.castShadow = true;
  return m;
}

function boxSingleMat(w, h, d, material, px, py, pz) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(px, py, pz);
  m.castShadow = true;
  return m;
}

// Kafa (deri rengi)
const head = boxSingleMat(1.30, 1.30, 1.30, skinMat, 0, 4.35, 0);
avatar.add(head);

// Saç
const hair = boxSingleMat(1.34, 0.40, 1.34, hairMat, 0, 4.88, 0);
avatar.add(hair);

// Gözler
const eyeGeo = new THREE.BoxGeometry(0.28, 0.20, 0.04);
const eyeMat = new THREE.MeshBasicMaterial({ color: 0x080808 });
[-0.31, 0.31].forEach(ex => {
  const eye = new THREE.Mesh(eyeGeo, eyeMat);
  eye.position.set(ex, 4.33, 0.67);
  avatar.add(eye);
  const sparkGeo = new THREE.BoxGeometry(0.07, 0.07, 0.04);
  const sparkMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const spark = new THREE.Mesh(sparkGeo, sparkMat);
  spark.position.set(ex + 0.08, 4.40, 0.70);
  avatar.add(spark);
});

// Gövde — tam Roblox R6 boyutları: 2x2x1 stud oranı
const torso = boxMultiMat(1.80, 2.00, 1.10, torsoMats, 0, 2.50, 0);
avatar.add(torso);

// Üst kollar — shirt UV ile
const lUArm = boxMultiMat(0.80, 1.45, 0.80, lUArmMats, -1.38, 2.70, 0);
const rUArm = boxMultiMat(0.80, 1.45, 0.80, rUArmMats,  1.38, 2.70, 0);
avatar.add(lUArm); avatar.add(rUArm);

// Alt kollar — deri
const lLArm = boxSingleMat(0.70, 1.25, 0.70, skinMat, -1.38, 1.45, 0);
const rLArm = boxSingleMat(0.70, 1.25, 0.70, skinMat,  1.38, 1.45, 0);
avatar.add(lLArm); avatar.add(rLArm);

// Eller — deri
const lHand = boxSingleMat(0.65, 0.65, 0.65, skinMat, -1.38, 0.75, 0);
const rHand = boxSingleMat(0.65, 0.65, 0.65, skinMat,  1.38, 0.75, 0);
avatar.add(lHand); avatar.add(rHand);

// Üst bacaklar — pants UV ile
const lULeg = boxMultiMat(0.82, 1.45, 0.82, lULegMats, -0.50, 0.75, 0);
const rULeg = boxMultiMat(0.82, 1.45, 0.82, rULegMats,  0.50, 0.75, 0);
avatar.add(lULeg); avatar.add(rULeg);

// Alt bacaklar — pants UV ile
const lLLeg = boxMultiMat(0.76, 1.35, 0.76, lLLegMats, -0.50, -0.60, 0);
const rLLeg = boxMultiMat(0.76, 1.35, 0.76, rLLegMats,  0.50, -0.60, 0);
avatar.add(lLLeg); avatar.add(rLLeg);

// Ayakkabılar
const lShoe = boxSingleMat(0.88, 0.42, 1.00, shoeMat, -0.50, -1.44, 0.08);
const rShoe = boxSingleMat(0.88, 0.42, 1.00, shoeMat,  0.50, -1.44, 0.08);
avatar.add(lShoe); avatar.add(rShoe);

scene.add(avatar);
avatar.position.y = 0.0;

// ── Animasyon ─────────────────────────────────────────────────────────────
let frame = 0;
window._frameData = null;
window._done = false;

window._renderFrame = function () {
  if (frame >= TOTAL) { window._done = true; return; }

  const t = frame / FPS;

  // Y ekseni tam 360° rotasyon
  avatar.rotation.y = -(2 * Math.PI * t) / DUR;

  // Minimal idle (sadece 4cm — kullanıcı yukarı-aşağı istemedi)
  avatar.position.y = Math.sin(t * 2.8) * 0.04;

  // Kollar hafif sallanma
  const swing = Math.sin(t * 3.2) * 0.18;
  lUArm.rotation.x =  swing;
  rUArm.rotation.x = -swing;
  lLArm.rotation.x =  swing * 0.6;
  rLArm.rotation.x = -swing * 0.6;
  lHand.rotation.x =  swing * 0.4;
  rHand.rotation.x = -swing * 0.4;

  // Bacaklar adım atma
  const step = Math.sin(t * 3.2) * 0.10;
  lULeg.rotation.x =  step;
  rULeg.rotation.x = -step;

  // Neon ışıklar yörüngesi
  const la = t * 0.7;
  neonBlue.position.set(Math.cos(la) * 5, 3 + Math.sin(la * 0.5) * 1.5, Math.sin(la) * 5);
  neonPink.position.set(Math.cos(la + Math.PI) * 5, 1 + Math.sin(la * 0.5 + 1) * 1.5, Math.sin(la + Math.PI) * 5);

  ring1.rotation.z = t * 0.3;
  ring2.rotation.y = t * 0.4;

  const ppa = partGeo.attributes.position;
  for (let i = 0; i < partCount; i++) {
    ppa.array[i*3+1] += 0.006;
    if (ppa.array[i*3+1] > 9) ppa.array[i*3+1] = -1;
  }
  ppa.needsUpdate = true;

  renderer.render(scene, camera);
  window._frameData = canvas.toDataURL('image/jpeg', 0.88);
  frame++;
};

window._frame = () => frame;
</script>
</body>
</html>"""


class ThreeJSRenderer:

    def __init__(self):
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from playwright.sync_api import sync_playwright  # noqa
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    # ── Ana metod (sync wrapper) ─────────────────────────────────────────────
    def render(
        self,
        shirt_png:  str,
        pants_png:  str,
        output_path: str,
        fps:        int = 30,
        duration:   int = 15,
        width:      int = 1080,
        height:     int = 1920,
    ) -> str:
        """Three.js sahnesini render edip MP4 döndürür. Hata olursa RuntimeError."""
        asyncio.run(self._render_async(shirt_png, pants_png, output_path, fps, duration, width, height))
        return output_path

    # ── Async render ─────────────────────────────────────────────────────────
    async def _render_async(
        self, shirt_png, pants_png, output_path,
        fps, duration, width, height,
    ):
        from playwright.async_api import async_playwright

        html = (
            _HTML
            .replace('{W}',        str(width))
            .replace('{H}',        str(height))
            .replace('{FPS}',      str(fps))
            .replace('{DUR}',      str(duration))
            .replace('{SHIRT_URL}', self._to_data_url(shirt_png))
            .replace('{PANTS_URL}', self._to_data_url(pants_png))
        )

        total = fps * duration
        frames_dir = tempfile.mkdtemp(prefix='roblox3d_')

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    args=['--disable-gpu-sandbox', '--enable-unsafe-webgpu']
                )
                page = await browser.new_page(
                    viewport={'width': width, 'height': height}
                )
                await page.set_content(html)
                # Three.js + CDN yüklensin (max 15 saniye)
                await page.wait_for_function(
                    "typeof THREE !== 'undefined' && window._renderFrame !== undefined",
                    timeout=15000,
                )
                # Texture'ların yüklenmesi için bekle
                await page.wait_for_timeout(2000)

                for i in range(total):
                    await page.evaluate('window._renderFrame()')
                    frame_data = await page.evaluate('window._frameData')
                    if not frame_data:
                        raise RuntimeError(f"Frame {i} boş döndü")
                    b64 = frame_data.split(',', 1)[1]
                    frame_path = os.path.join(frames_dir, f'{i:04d}.jpg')
                    with open(frame_path, 'wb') as f:
                        f.write(base64.b64decode(b64))

                    if i % 60 == 0:
                        Logger.info(f"3D render: {i}/{total} frame ({i*100//total}%)")

                await browser.close()

            Logger.info("3D render: Frame yakalama tamamlandı, FFmpeg başlatılıyor...")
            self._frames_to_video(frames_dir, output_path, fps)

        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    # ── Frames → MP4 ────────────────────────────────────────────────────────
    @staticmethod
    def _frames_to_video(frames_dir: str, output_path: str, fps: int):
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps),
            '-i', os.path.join(frames_dir, '%04d.jpg'),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-pix_fmt', 'yuv420p',
            '-r', str(fps),
            output_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f'FFmpeg frames→video başarısız:\n{res.stderr[-600:]}')
        Logger.success(f"3D render video hazır: {output_path}")

    # ── Yardımcı ─────────────────────────────────────────────────────────────
    @staticmethod
    def _to_data_url(png_path: str) -> str:
        with open(png_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(png_path)[1].lower().lstrip('.')
        mime = 'image/png' if ext == 'png' else 'image/jpeg'
        return f'data:{mime};base64,{b64}'
