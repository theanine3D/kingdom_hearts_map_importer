"""Decoded RGBA texture data -> packed Blender images.

Sprite-animated textures (waterfalls, shoreline foam, ...) are baked into a
vertical strip image, frame 0 at the top; the material animates a Mapping
node down the strip. With animations disabled only frame 0 is baked.
"""

import bpy
import numpy as np


def build_images(texture_block_groups, name_prefix: str, import_anims: bool) -> dict:
    """Create one bpy Image per unique texture. Returns texture name -> Image."""
    images: dict[str, bpy.types.Image] = {}
    for group in texture_block_groups:
        for block in group:
            for tex in block.textures:
                key = tex.name()
                if key in images:
                    continue
                if tex.sprite_anim is not None:
                    frames = tex.sprite_anim.num_frames if import_anims else 1
                    rgba, width, height = _sprite_strip(tex, frames)
                else:
                    rgba = tex.pixels()
                    width, height = tex.width(), tex.height()
                image = bpy.data.images.new(
                    f"{name_prefix}_{key}", width, height, alpha=True)
                pixels = np.frombuffer(bytes(rgba), dtype=np.uint8)
                pixels = pixels.astype(np.float32) / 255.0
                # Texture rows are top-to-bottom; Blender expects bottom-to-top.
                pixels = pixels.reshape(height, width * 4)[::-1].ravel()
                image.pixels.foreach_set(pixels)
                image.pack()
                images[key] = image
    return images


def _sprite_strip(tex, num_frames: int):
    """Stack sprite frames vertically into one RGBA buffer."""
    anim = tex.sprite_anim
    width, height = anim.sprite_width, anim.sprite_height
    block = tex.parent
    out = bytearray(width * height * num_frames * 4)
    for j in range(num_frames):
        sx, sy = anim.sprite_left[j], anim.sprite_top[j]
        copy_w = min(width, block.width - sx)
        if copy_w <= 0:
            continue
        for y in range(height):
            by = sy + y
            if by >= block.height:
                break
            src = (by * block.width + sx) * 4
            dst = ((j * height + y) * width) * 4
            out[dst:dst + copy_w * 4] = block.pixels[src:src + copy_w * 4]
    return out, width, height * num_frames
