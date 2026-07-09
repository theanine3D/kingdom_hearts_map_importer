"""Materials reproducing the KH1 fixed-function look.

Fragment path in the game: textureColor * vertexColor * 2.0,
alpha-masked at 0.125 for opaque geometry, alpha-blended for translucent.

Texture animations map to a keyframed Mapping node:
- UV scroll: linear Location keyframes with linear extrapolation. The game
  advances UVs by tableValue * 0.000005 per millisecond of block-normalized
  UV, i.e. tableValue * 0.005 UV/second, converted here to crop space.
- Sprite animation: stepped Location.y keyframes walking down the frame
  strip (one band per frame), cycled forever. The game shows each frame for
  speed/30 seconds.
"""

import bpy

from .anim import find_fcurves

ALPHA_CLIP_THRESHOLD = 0.125
COLOR_ATTR_NAME = "Col"


class MaterialCache:
    def __init__(self, name_prefix: str, shading: str, fps: float,
                 import_anims: bool):
        self.name_prefix = name_prefix
        self.shading = shading  # 'EMISSION' or 'PRINCIPLED'
        self.fps = fps
        self.import_anims = import_anims
        self._cache: dict[tuple, bpy.types.Material] = {}

    def get(self, texture, image, translucent: bool,
            scroll=(0.0, 0.0)) -> bpy.types.Material:
        if not self.import_anims:
            scroll = (0.0, 0.0)
        scroll = (round(scroll[0], 6), round(scroll[1], 6))
        key = (texture.name() if texture else None, translucent, scroll)
        material = self._cache.get(key)
        if material is None:
            material = _build_material(
                self.name_prefix, texture, image, translucent, self.shading,
                scroll, self.fps, self.import_anims)
            self._cache[key] = material
        return material


def _set_alpha_mode(material: bpy.types.Material, translucent: bool) -> None:
    # blend_method was deprecated for EEVEE Next (4.2+); set whichever
    # properties this Blender version exposes.
    if hasattr(material, "blend_method"):
        material.blend_method = "BLEND" if translucent else "CLIP"
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "BLENDED" if translucent else "DITHERED"
    if hasattr(material, "alpha_threshold"):
        material.alpha_threshold = ALPHA_CLIP_THRESHOLD


def _socket_fcurves(node_tree, socket):
    return find_fcurves(node_tree.animation_data,
                        socket.path_from_id("default_value"))


def _animate_mapping(node_tree, mapping, texture, scroll, fps):
    """Keyframe the Mapping node's Location for scroll and/or sprite frames."""
    location = mapping.inputs["Location"]
    anim = texture.sprite_anim

    if anim is not None:
        # Stepped walk down the strip: frame j occupies band j (top-down),
        # so the sample point moves by -1/numFrames per frame.
        n = anim.num_frames
        frame_duration = (anim.speed / 30.0) * fps
        for j in range(n):
            location.default_value = (0.0, -j / n, 0.0)
            location.keyframe_insert("default_value", frame=1.0 + j * frame_duration)
        location.default_value = (0.0, 0.0, 0.0)
        location.keyframe_insert("default_value", frame=1.0 + n * frame_duration)
        for fcurve in _socket_fcurves(node_tree, location):
            for point in fcurve.keyframe_points:
                point.interpolation = "CONSTANT"
            fcurve.modifiers.new("CYCLES")
        return

    # Scroll rates arrive in block-normalized UV/second; convert to the
    # crop-space UVs the mesh builder produced (V axis is flipped).
    block = texture.parent
    rate_u = scroll[0] * block.width / texture.width()
    rate_v = -scroll[1] * block.height / texture.height()
    location.default_value = (0.0, 0.0, 0.0)
    location.keyframe_insert("default_value", frame=1.0)
    location.default_value = (rate_u, rate_v, 0.0)
    location.keyframe_insert("default_value", frame=1.0 + fps)
    for fcurve in _socket_fcurves(node_tree, location):
        fcurve.extrapolation = "LINEAR"
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"


def _build_material(name_prefix: str, texture, image, translucent: bool,
                    shading: str, scroll, fps: float,
                    import_anims: bool) -> bpy.types.Material:
    name = f"{name_prefix}_{texture.name() if texture else 'untextured'}"
    if translucent:
        name += "_blend"
    animated = import_anims and texture is not None and (
        texture.sprite_anim is not None or scroll != (0.0, 0.0))
    if scroll != (0.0, 0.0):
        name += f"_s{scroll[0]:+.3f}{scroll[1]:+.3f}"
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.use_backface_culling = True
    _set_alpha_mode(material, translucent)

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)

    vcol = nodes.new("ShaderNodeVertexColor")
    vcol.layer_name = COLOR_ATTR_NAME
    vcol.location = (-600, -200)

    # vertexColor * 2.0 (PS2 modulate: 0x80 == 1.0)
    vcol_x2 = nodes.new("ShaderNodeVectorMath")
    vcol_x2.operation = "SCALE"
    vcol_x2.inputs["Scale"].default_value = 2.0
    vcol_x2.location = (-400, -200)
    links.new(vcol.outputs["Color"], vcol_x2.inputs[0])

    if texture is not None and image is not None:
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.interpolation = "Linear"
        if texture.sprite_anim is not None:
            # Never tiled in practice; EXTEND avoids cross-frame bleed.
            tex_node.extension = "EXTEND"
        else:
            tex_node.extension = "REPEAT" if (texture.tiled_u or texture.tiled_v) else "EXTEND"
        tex_node.location = (-600, 200)

        if animated:
            uv_node = nodes.new("ShaderNodeTexCoord")
            uv_node.location = (-1000, 200)
            mapping = nodes.new("ShaderNodeMapping")
            mapping.location = (-800, 200)
            links.new(uv_node.outputs["UV"], mapping.inputs["Vector"])
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])
            _animate_mapping(material.node_tree, mapping, texture, scroll, fps)

        mult = nodes.new("ShaderNodeMix")
        mult.data_type = "RGBA"
        mult.blend_type = "MULTIPLY"
        mult.inputs["Factor"].default_value = 1.0
        mult.location = (-100, 100)
        links.new(tex_node.outputs["Color"], mult.inputs["A"])
        links.new(vcol_x2.outputs["Vector"], mult.inputs["B"])
        color_socket = mult.outputs["Result"]

        alpha = nodes.new("ShaderNodeMath")
        alpha.operation = "MULTIPLY"
        alpha.location = (-100, -300)
        links.new(tex_node.outputs["Alpha"], alpha.inputs[0])
        links.new(vcol.outputs["Alpha"], alpha.inputs[1])
        alpha_socket = alpha.outputs["Value"]
    else:
        color_socket = vcol_x2.outputs["Vector"]
        alpha_socket = vcol.outputs["Alpha"]

    if shading == "PRINCIPLED":
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.location = (300, 0)
        shader.inputs["Roughness"].default_value = 1.0
        for specular_name in ("Specular IOR Level", "Specular"):
            if specular_name in shader.inputs:
                shader.inputs[specular_name].default_value = 0.0
                break
        links.new(color_socket, shader.inputs["Base Color"])
        links.new(alpha_socket, shader.inputs["Alpha"])
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    else:
        # Unlit: game lighting is baked into vertex colors.
        emission = nodes.new("ShaderNodeEmission")
        emission.location = (300, 100)
        links.new(color_socket, emission.inputs["Color"])

        transparent = nodes.new("ShaderNodeBsdfTransparent")
        transparent.location = (300, -150)

        mix_shader = nodes.new("ShaderNodeMixShader")
        mix_shader.location = (600, 0)
        links.new(alpha_socket, mix_shader.inputs["Fac"])
        links.new(transparent.outputs["BSDF"], mix_shader.inputs[1])
        links.new(emission.outputs["Emission"], mix_shader.inputs[2])
        links.new(mix_shader.outputs["Shader"], output.inputs["Surface"])

    return material
