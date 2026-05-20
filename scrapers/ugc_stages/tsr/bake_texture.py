import numpy as np
import torch
import xatlas
import trimesh
from PIL import Image


def make_atlas(mesh, texture_resolution, texture_padding):
    atlas = xatlas.Atlas()
    atlas.add_mesh(mesh.vertices, mesh.faces)
    options = xatlas.PackOptions()
    options.resolution = texture_resolution
    options.padding = texture_padding
    options.bilinear = True
    atlas.generate(pack_options=options)
    vmapping, indices, uvs = atlas[0]
    return {"vmapping": vmapping, "indices": indices, "uvs": uvs}


def _rasterize_numpy(mesh, atlas_vmapping, atlas_indices, atlas_uvs, texture_resolution, texture_padding):
    """Pure numpy UV position atlas rasterizer — no OpenGL needed."""
    H = W = texture_resolution
    output = np.zeros((H, W, 4), dtype=np.float32)

    verts  = mesh.vertices[atlas_vmapping].astype(np.float32)
    uvs_px = (atlas_uvs * np.array([W, H], dtype=np.float32))

    v0 = verts[atlas_indices[:, 0]]
    v1 = verts[atlas_indices[:, 1]]
    v2 = verts[atlas_indices[:, 2]]
    u0 = uvs_px[atlas_indices[:, 0]]
    u1 = uvs_px[atlas_indices[:, 1]]
    u2 = uvs_px[atlas_indices[:, 2]]

    denom = ((u1[:, 1] - u2[:, 1]) * (u0[:, 0] - u2[:, 0]) +
             (u2[:, 0] - u1[:, 0]) * (u0[:, 1] - u2[:, 1]))
    valid  = np.where(np.abs(denom) > 1e-8)[0]

    for fi in valid:
        x0 = max(0, int(np.floor(min(u0[fi, 0], u1[fi, 0], u2[fi, 0]))))
        x1 = min(W, int(np.ceil( max(u0[fi, 0], u1[fi, 0], u2[fi, 0]))) + 1)
        y0 = max(0, int(np.floor(min(u0[fi, 1], u1[fi, 1], u2[fi, 1]))))
        y1 = min(H, int(np.ceil( max(u0[fi, 1], u1[fi, 1], u2[fi, 1]))) + 1)
        if x1 <= x0 or y1 <= y0:
            continue

        px  = np.arange(x0, x1, dtype=np.float32) + 0.5
        py  = np.arange(y0, y1, dtype=np.float32) + 0.5
        PX, PY = np.meshgrid(px, py)
        fx  = PX.ravel(); fy = PY.ravel()

        d   = denom[fi]
        a   = u0[fi]; b = u1[fi]; c = u2[fi]
        w0  = ((b[1] - c[1]) * (fx - c[0]) + (c[0] - b[0]) * (fy - c[1])) / d
        w1  = ((c[1] - a[1]) * (fx - c[0]) + (a[0] - c[0]) * (fy - c[1])) / d
        w2  = 1.0 - w0 - w1

        hit = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not hit.any():
            continue

        rows = fy[hit].astype(np.int32)
        cols = fx[hit].astype(np.int32)
        pos  = (w0[hit, None] * v0[fi] +
                w1[hit, None] * v1[fi] +
                w2[hit, None] * v2[fi])
        output[rows, cols, :3] = pos
        output[rows, cols, 3]  = 1.0

    # Dilation: bleed filled pixels outward by texture_padding
    if texture_padding > 0:
        try:
            from scipy.ndimage import distance_transform_edt
            filled = output[:, :, 3] > 0
            if filled.any() and not filled.all():
                dist, idx = distance_transform_edt(~filled, return_indices=True)
                dilate = (dist > 0) & (dist <= texture_padding)
                output[dilate, :3] = output[idx[0][dilate], idx[1][dilate], :3]
                output[dilate, 3]  = 1.0
        except ImportError:
            pass

    return output


def _rasterize_moderngl(mesh, atlas_vmapping, atlas_indices, atlas_uvs, texture_resolution, texture_padding):
    """OpenGL-accelerated UV position atlas rasterizer (requires moderngl)."""
    import moderngl
    ctx = moderngl.create_context(standalone=True)
    basic_prog = ctx.program(
        vertex_shader="""
            #version 330
            in vec2 in_uv; in vec3 in_pos; out vec3 v_pos;
            void main() { v_pos = in_pos; gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0); }
        """,
        fragment_shader="""
            #version 330
            in vec3 v_pos; out vec4 o_col;
            void main() { o_col = vec4(v_pos, 1.0); }
        """,
    )
    gs_prog = ctx.program(
        vertex_shader="""
            #version 330
            in vec2 in_uv; in vec3 in_pos; out vec3 vg_pos;
            void main() { vg_pos = in_pos; gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0); }
        """,
        geometry_shader="""
            #version 330
            uniform float u_resolution; uniform float u_dilation;
            layout (triangles) in; layout (triangle_strip, max_vertices = 12) out;
            in vec3 vg_pos[]; out vec3 vf_pos;
            void lineSegment(int aidx, int bidx) {
                vec2 a = gl_in[aidx].gl_Position.xy; vec2 b = gl_in[bidx].gl_Position.xy;
                vec2 dir = normalize((b - a) * u_resolution);
                vec2 offset = vec2(-dir.y, dir.x) * u_dilation / u_resolution;
                gl_Position = vec4(a + offset, 0.0, 1.0); vf_pos = vg_pos[aidx]; EmitVertex();
                gl_Position = vec4(a - offset, 0.0, 1.0); vf_pos = vg_pos[aidx]; EmitVertex();
                gl_Position = vec4(b + offset, 0.0, 1.0); vf_pos = vg_pos[bidx]; EmitVertex();
                gl_Position = vec4(b - offset, 0.0, 1.0); vf_pos = vg_pos[bidx]; EmitVertex();
            }
            void main() { lineSegment(0,1); lineSegment(1,2); lineSegment(2,0); EndPrimitive(); }
        """,
        fragment_shader="""
            #version 330
            in vec3 vf_pos; out vec4 o_col;
            void main() { o_col = vec4(vf_pos, 1.0); }
        """,
    )
    uvs     = atlas_uvs.flatten().astype("f4")
    pos     = mesh.vertices[atlas_vmapping].flatten().astype("f4")
    indices = atlas_indices.flatten().astype("i4")
    vao_content = [
        ctx.buffer(uvs).bind("in_uv",  layout="2f"),
        ctx.buffer(pos).bind("in_pos", layout="3f"),
    ]
    ibo       = ctx.buffer(indices)
    basic_vao = ctx.vertex_array(basic_prog, vao_content, ibo)
    gs_vao    = ctx.vertex_array(gs_prog,    vao_content, ibo)
    fbo = ctx.framebuffer(
        color_attachments=[ctx.texture((texture_resolution, texture_resolution), 4, dtype="f4")]
    )
    fbo.use(); fbo.clear(0.0, 0.0, 0.0, 0.0)
    gs_prog["u_resolution"].value = texture_resolution
    gs_prog["u_dilation"].value   = texture_padding
    gs_vao.render(); basic_vao.render()
    fbo_np = np.frombuffer(fbo.color_attachments[0].read(), dtype="f4").reshape(
        texture_resolution, texture_resolution, 4
    )
    return fbo_np


def rasterize_position_atlas(mesh, atlas_vmapping, atlas_indices, atlas_uvs, texture_resolution, texture_padding):
    try:
        return _rasterize_moderngl(mesh, atlas_vmapping, atlas_indices, atlas_uvs, texture_resolution, texture_padding)
    except Exception:
        return _rasterize_numpy(mesh, atlas_vmapping, atlas_indices, atlas_uvs, texture_resolution, texture_padding)


def render_bake_colors(model, scene_code, positions_texture, texture_resolution, n_views=6):
    """
    model.render() ile n_views kare üretir, her texel pozisyonunu
    en iyi kameraya yansıtarak renk örnek alır. query_triplane'den
    daha coherent renk verir. Doldurulmayan texeller için triplane fallback kullanır.
    """
    from tsr.utils import get_spherical_cameras

    device   = scene_code.device
    H = W    = 512

    # model.render returns List[List[ndarray]] — [batch_idx][view_idx] each (H, W, 3)
    with torch.no_grad():
        raw = model.render(
            scene_code.unsqueeze(0), n_views=n_views,
            height=H, width=W, return_type="np",
        )
    frames = np.stack(raw[0], axis=0)  # (n_views, H, W, 3)

    rays_o, rays_d = get_spherical_cameras(n_views, 0.0, 1.9, 40.0, H, W)
    cam_centers = rays_o[:, H // 2, W // 2, :].cpu().numpy()  # (n_views, 3)
    cam_dirs    = rays_d[:, H // 2, W // 2, :].cpu().numpy()  # (n_views, 3)

    tex_flat = positions_texture.reshape(-1, 4)
    alpha    = tex_flat[:, 3]
    pos3d    = tex_flat[:, :3]

    focal = 0.5 * H / np.tan(0.5 * np.deg2rad(40.0))

    rgb_out    = np.zeros((len(tex_flat), 3), dtype=np.float32)
    best_score = np.full(len(tex_flat), -np.inf, dtype=np.float32)
    best_px    = np.zeros(len(tex_flat), dtype=np.int32)
    best_py    = np.zeros(len(tex_flat), dtype=np.int32)
    best_vi    = np.zeros(len(tex_flat), dtype=np.int32)

    for vi in range(n_views):
        fwd = cam_dirs[vi].copy()
        fwd /= np.linalg.norm(fwd) + 1e-8
        co  = cam_centers[vi]

        rel   = pos3d - co[None, :]
        depth = -(rel * fwd[None, :]).sum(axis=1)
        valid = (depth > 0.01) & (alpha > 0)

        right = np.array([-fwd[1], fwd[0], 0.0], dtype=np.float32)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        right /= np.linalg.norm(right)
        up     = np.cross(right, fwd); up /= np.linalg.norm(up)

        x2d = (rel * right[None, :]).sum(axis=1) / (depth + 1e-8) * focal + W / 2
        y2d = (rel * up[None, :]).sum(axis=1)    / (depth + 1e-8) * focal + H / 2
        px  = np.clip(np.round(x2d).astype(np.int32), 0, W - 1)
        py  = np.clip(np.round(y2d).astype(np.int32), 0, H - 1)

        to_cam   = co[None, :] - pos3d
        to_cam_n = to_cam / (np.linalg.norm(to_cam, axis=1, keepdims=True) + 1e-8)
        score    = (to_cam_n * (-fwd[None, :])).sum(axis=1)

        improve      = valid & (score > best_score)
        best_score   = np.where(improve, score, best_score)
        best_px      = np.where(improve, px,    best_px)
        best_py      = np.where(improve, py,    best_py)
        best_vi      = np.where(improve, vi,    best_vi)

    filled = best_score > -np.inf
    if filled.any():
        fi = np.where(filled)[0]
        rgb_out[fi] = frames[best_vi[fi], best_py[fi], best_px[fi], :]

    # triplane fallback for remaining filled texels
    unfilled = ~filled & (alpha > 0)
    if unfilled.any():
        pos_t = torch.tensor(pos3d[unfilled], dtype=torch.float32).to(device)
        with torch.no_grad():
            q = model.renderer.query_triplane(model.decoder, pos_t, scene_code)
        rgb_out[unfilled] = q["color"].cpu().numpy()

    rgba_f = np.concatenate([rgb_out, alpha[:, None]], axis=1)
    rgba_f[alpha == 0] = 0.0
    return rgba_f.reshape(texture_resolution, texture_resolution, 4)


def bake_texture(mesh, model, scene_code, texture_resolution):
    texture_padding = round(max(2, texture_resolution / 256))
    atlas           = make_atlas(mesh, texture_resolution, texture_padding)
    positions_tex   = rasterize_position_atlas(
        mesh, atlas["vmapping"], atlas["indices"], atlas["uvs"],
        texture_resolution, texture_padding,
    )
    colors_tex = render_bake_colors(model, scene_code, positions_tex, texture_resolution)
    return {
        "vmapping": atlas["vmapping"],
        "indices":  atlas["indices"],
        "uvs":      atlas["uvs"],
        "colors":   colors_tex,
    }
