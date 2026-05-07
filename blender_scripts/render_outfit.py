"""
render_outfit.py — Blender headless outfit render scripti.

Kullanım (Blender ile çalıştır):
  blender --background --python blender_scripts/render_outfit.py -- \
    --shirt shirt.png --pants pants.png --output tmp/render.mp4 \
    [--duration 15] [--fps 30] [--width 1080] [--height 1920]

Blender'ın kendi Python ortamında çalışır; proje paketlerine erişimi yoktur.
"""
import sys
import os
import math
import argparse


def parse_blender_args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--shirt",    required=True)
    p.add_argument("--pants",    required=True)
    p.add_argument("--output",   required=True)
    p.add_argument("--duration", type=int,   default=15)
    p.add_argument("--fps",      type=int,   default=30)
    p.add_argument("--width",    type=int,   default=1080)
    p.add_argument("--height",   type=int,   default=1920)
    p.add_argument("--template", default="blender_scripts/roblox_rig.blend")
    return p.parse_args(raw)


def load_or_build_rig(blend_path: str):
    import bpy
    if os.path.exists(blend_path):
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(blend_path))
        return

    # Template yoksa: minimal prosedürel R6 avatar inşa et
    bpy.ops.wm.read_factory_settings(use_empty=True)

    def add_part(name, loc, dims, mat_name=None):
        bpy.ops.mesh.primitive_cube_add(location=loc)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = (dims[0] / 2, dims[1] / 2, dims[2] / 2)
        bpy.ops.object.transform_apply(scale=True)
        if mat_name:
            mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
            mat.use_nodes = True
            if not obj.data.materials:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat
        return obj

    root = bpy.data.objects.new("CharacterRoot", None)
    bpy.context.scene.collection.objects.link(root)

    parts = [
        ("Head",     (0, 0, 2.90), (0.60, 0.60, 0.60), "Skin"),
        ("Torso",    (0, 0, 1.80), (0.60, 0.40, 0.80), "Shirt"),
        ("LeftArm",  (-0.50, 0, 1.60), (0.22, 0.22, 0.70), "Shirt"),
        ("RightArm", ( 0.50, 0, 1.60), (0.22, 0.22, 0.70), "Shirt"),
        ("LeftLeg",  (-0.20, 0, 0.60), (0.24, 0.24, 0.80), "Pants"),
        ("RightLeg", ( 0.20, 0, 0.60), (0.24, 0.24, 0.80), "Pants"),
    ]
    for name, loc, dims, mat in parts:
        obj = add_part(name, loc, dims, mat)
        obj.parent = root


def apply_texture_to_material(mat_name: str, tex_path: str):
    import bpy
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        return
    mat.use_nodes = True
    tree = mat.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    if not bsdf:
        return

    img = bpy.data.images.load(os.path.abspath(tex_path), check_existing=True)
    tex_node = tree.nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])


def setup_lighting():
    import bpy
    from mathutils import Vector

    # Sahneyi temizle
    for obj in list(bpy.context.scene.objects):
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)

    def add_light(name, loc, energy, color, light_type="AREA"):
        light_data = bpy.data.lights.new(name=name, type=light_type)
        light_data.energy = energy
        light_data.color  = color
        if light_type == "AREA":
            light_data.size = 3.0
        obj = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = Vector(loc)
        obj.rotation_euler = (
            math.atan2(loc[2], -loc[1]),
            0,
            math.atan2(loc[0], -loc[1]),
        )

    add_light("KeyLight",  ( 3.0, -3.0, 5.0), 1200, (1.0,  0.95, 0.85))
    add_light("FillLight", (-2.5, -2.0, 4.0),  400, (0.75, 0.85, 1.0))
    add_light("RimLight",  ( 0.0,  4.0, 5.0),  700, (0.0,  0.9,  1.0))
    add_light("NeonBack",  ( 0.0,  3.5, 2.0),  300, (0.8,  0.0,  1.0))


def setup_camera(width: int, height: int, fps: int):
    import bpy
    from mathutils import Vector

    for obj in list(bpy.context.scene.objects):
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 85
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    cam_obj.location = Vector((0.0, -5.0, 1.8))
    cam_obj.rotation_euler = (math.radians(80), 0, 0)

    scene = bpy.context.scene
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps


def setup_neon_background():
    import bpy

    bpy.ops.mesh.primitive_plane_add(size=16, location=(0, 3, 2))
    plane = bpy.context.active_object
    plane.name = "NeonBackground"

    mat = bpy.data.materials.new("NeonBG")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()

    out   = tree.nodes.new("ShaderNodeOutputMaterial")
    emit  = tree.nodes.new("ShaderNodeEmission")
    ramp  = tree.nodes.new("ShaderNodeValToRGB")
    coord = tree.nodes.new("ShaderNodeTexCoord")
    map_n = tree.nodes.new("ShaderNodeMapping")

    emit.inputs["Strength"].default_value = 1.5
    cr = ramp.color_ramp
    cr.elements[0].color = (0.02, 0.0, 0.08, 1)
    cr.elements[1].color = (0.05, 0.03, 0.18, 1)

    tree.links.new(coord.outputs["Generated"], map_n.inputs["Vector"])
    tree.links.new(map_n.outputs["Vector"],    ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"],      emit.inputs["Color"])
    tree.links.new(emit.outputs["Emission"],   out.inputs["Surface"])

    plane.data.materials.append(mat)


def setup_rotation_animation(fps: int, duration: int):
    import bpy

    root = bpy.data.objects.get("CharacterRoot")
    if not root:
        return

    scene = bpy.context.scene
    total_frames = fps * duration
    scene.frame_start = 1
    scene.frame_end   = total_frames

    root.rotation_mode = "XYZ"

    # Frame 1: 0°
    root.rotation_euler.z = 0
    root.keyframe_insert(data_path="rotation_euler", index=2, frame=1)

    # Son frame: 360°
    root.rotation_euler.z = 2 * math.pi
    root.keyframe_insert(data_path="rotation_euler", index=2, frame=total_frames)

    # FCurve interpolasyonunu LINEAR yap
    if root.animation_data and root.animation_data.action:
        for fcurve in root.animation_data.action.fcurves:
            if fcurve.data_path == "rotation_euler" and fcurve.array_index == 2:
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "LINEAR"


def render_to_video(output_path: str):
    import bpy

    scene = bpy.context.scene
    scene.render.engine              = "BLENDER_EEVEE"
    scene.render.image_settings.file_format  = "FFMPEG"
    scene.render.ffmpeg.format       = "MPEG4"
    scene.render.ffmpeg.codec        = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.filepath            = os.path.abspath(output_path)

    try:
        scene.eevee.taa_render_samples = 32
    except AttributeError:
        pass

    bpy.ops.render.render(animation=True)


def main():
    args = parse_blender_args()

    load_or_build_rig(args.template)
    apply_texture_to_material("Shirt", args.shirt)
    apply_texture_to_material("Pants", args.pants)
    setup_lighting()
    setup_camera(args.width, args.height, args.fps)
    setup_neon_background()
    setup_rotation_animation(args.fps, args.duration)
    render_to_video(args.output)
    print(f"[blender] Render tamamlandı: {args.output}")


main()
