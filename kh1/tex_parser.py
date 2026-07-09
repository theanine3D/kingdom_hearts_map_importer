"""Kingdom Hearts (PS2) map texture decoding.

Textures are stored as 4- or 8-bit palettized data with CLUTs, optionally
swizzled in PS2 GS memory layout.
"""

from .dataview import DataView


class TextureSpriteAnim:
    """UV sprite-sheet animation (e.g. waterfalls). Kept as metadata for the
    importer; frame offsets are normalized to the parent texture block."""

    def __init__(self, texture_block: "TextureBlock", texture: "Texture",
                 sprite_left_anim: list[int], sprite_top_anim: list[int],
                 num_frames: int, sprite_width: int, sprite_height: int, speed: int):
        self.num_frames = num_frames
        self.sprite_width = sprite_width
        self.sprite_height = sprite_height
        self.speed = speed  # frame duration = speed/30 seconds
        # Raw per-frame positions within the texture block, in pixels.
        self.sprite_left = list(sprite_left_anim[:num_frames])
        self.sprite_top = list(sprite_top_anim[:num_frames])
        self.u_anim = [(sprite_left_anim[i] - texture.clip_left) / texture_block.width
                       for i in range(num_frames)]
        self.v_anim = [(sprite_top_anim[i] - texture.clip_top) / texture_block.height
                       for i in range(num_frames)]


class Texture:
    def __init__(self, index: int, parent: "TextureBlock", color_table_offs: int, translucent: bool):
        self.index = index
        self.parent = parent
        self.color_table_offs = color_table_offs
        self.translucent = translucent
        self.clip_left = 0
        self.clip_right = 0
        self.clip_top = 0
        self.clip_bottom = 0
        self.tiled_u = False
        self.tiled_v = False
        self.sprite_anim: TextureSpriteAnim | None = None

    def width(self) -> int:
        return self.clip_right - self.clip_left + 1

    def height(self) -> int:
        return self.clip_bottom - self.clip_top + 1

    def name(self) -> str:
        return f"{self.parent.bank}_{self.parent.data_offs:x}_{self.index}"

    def pixels(self) -> bytearray:
        """RGBA pixels cropped to this texture's clip rect within its block."""
        width = self.width()
        height = self.height()
        if width == self.parent.width and height == self.parent.height:
            return bytearray(self.parent.pixels)
        clipped = bytearray(width * height * 4)
        # Clamp to the parent block; the region past it stays transparent
        # (see the clip-rect note in _fill_from_texture).
        copy_w = (min(self.clip_right, self.parent.width - 1) - self.clip_left + 1) * 4
        for y in range(min(height, self.parent.height - self.clip_top)):
            src = ((y + self.clip_top) * self.parent.width + self.clip_left) * 4
            dst = y * width * 4
            clipped[dst:dst + copy_w] = self.parent.pixels[src:src + copy_w]
        return clipped


class TextureBlock:
    def __init__(self, width: int, height: int, bit_depth: int, bank: int,
                 data_offs: int, deswizzle: bool):
        self.width = width
        self.height = height
        self.bit_depth = bit_depth
        self.bank = bank
        self.data_offs = data_offs
        self._deswizzle = deswizzle
        self.textures: list[Texture] = []
        self.format = f"Indexed{bit_depth}"
        self.pixels: bytearray = bytearray(0)

    def is_ovf(self) -> bool:
        # Texture data that overflowed the .IMG file and spilled into the .BIN.
        return self.bank == 0 and self.data_offs >= 0x100000

    def key(self) -> str:
        return f"{self.bank}{self.data_offs}"

    def build(self, tex_data_view: DataView, tex_clut_view: DataView) -> None:
        if self._deswizzle:
            data_offs = self.data_offs
            if self.bank == 0:
                data_offs -= 0x100000
            if self.bit_depth == 8:
                deswizzle_indexed8(tex_data_view, data_offs, self.width, self.height)
            elif self.bit_depth == 4:
                deswizzle_indexed4(tex_data_view, data_offs, self.width, self.height)
        self.pixels = bytearray(self.width * self.height * 4)
        for texture in self.textures:
            self._fill_from_texture(texture, tex_data_view, tex_clut_view)

    def _fill_from_texture(self, texture: Texture, tex_data_view: DataView,
                           tex_clut_view: DataView) -> None:
        if texture.color_table_offs >= tex_clut_view.byte_length:
            # At least two maps reference textures missing from the .IMG due to
            # the file pair being out of sync when the game shipped:
            #   Neverland - Clock Tower (Beta)
            #   End of the World - Deep Jungle (World Terminus)
            return
        data_offs = self.data_offs
        if self.bank >= 0:
            data_offs += 0x100000 * (-1 if self.is_ovf() else self.bank)
        pixels_per_byte = 2 if self.bit_depth == 4 else 1
        pixels = self.pixels
        clut_base = texture.color_table_offs
        # Some maps (e.g. Final Mix Atlantica) declare clip rects larger than
        # the texture block. The original JS silently drops the out-of-range
        # writes; clamp to match.
        clip_bottom = min(texture.clip_bottom, self.height - 1)
        clip_right = min(texture.clip_right, self.width - 1)
        for y in range(texture.clip_top, clip_bottom + 1):
            row = y * self.width
            for x in range(texture.clip_left, clip_right + 1):
                offs = row + x
                p = tex_data_view.get_u8(data_offs + offs // pixels_per_byte)
                if pixels_per_byte == 2:
                    p = (p if x % 2 == 0 else (p >> 4)) & 0xF
                else:
                    # Flip bits 4 and 5: 000xy000 -> 000yx000
                    p = (p & 0xE7) | ((p & 0x8) << 1) | ((p & 0x10) >> 1)
                dst = offs * 4
                clut = clut_base + p * 4
                pixels[dst] = tex_clut_view.get_u8(clut)
                pixels[dst + 1] = tex_clut_view.get_u8(clut + 1)
                pixels[dst + 2] = tex_clut_view.get_u8(clut + 2)
                # PS2 alpha: 0x80 = fully opaque; scale to 0xFF.
                pixels[dst + 3] = min(0xFF, tex_clut_view.get_u8(clut + 3) * 2)


def deswizzle_indexed8(tex_view: DataView, offs: int, width: int, height: int) -> None:
    byte_length = width * height
    source = bytes(tex_view.buf[tex_view.offset + offs:tex_view.offset + offs + byte_length])
    for i in range(byte_length):
        a = (i % 4) * 4 + ((i // 8) % 2) * 2
        b = ((i // 0x10) * 0x20) % (width * 4) + (i // (width * 4)) * (width * 4)
        c = (((i // 4) + ((i + width * 2) // (width * 4))) % 2) * 0x10
        d = (i // (width * 2)) % 2
        tex_view.set_u8(offs + i, source[a + b + c + d])


def deswizzle_indexed4(tex_view: DataView, offs: int, width: int, height: int) -> None:
    if width < 0x20 or height < 0x16:
        return
    byte_length = width * height // 2
    source = bytes(tex_view.buf[tex_view.offset + offs:tex_view.offset + offs + byte_length])
    rows = min(height, 0x80) // 0x10
    columns = min(4, width // 0x20)
    tiles = rows * width // 0x80
    for i in range(byte_length):
        v = [0, 0]
        for j in range(2):
            index = i * 2 + j
            a = (index // 0x20) % columns * tiles * 0x200
            b = (index // 0x80) % (width // 0x80) * (min(height, 0x80) // 0x10) * 0x40
            c = ((index // (tiles * 0x10)) % 2) * tiles * 0x40
            d = ((index // (tiles * 0x40)) % 4) * tiles * 0x80
            e = (index // (tiles * 0x20)) % 2
            f = (index % 4) * 8
            g = ((index % 0x20) // 8) * 2
            h = ((index + (((index // (tiles * 0x10) + 2) // 4) % 2) * 4) % 8 // 4) * 0x20
            m = (index // (tiles * 0x800)) * tiles * 0x800
            n = ((index // (tiles * 0x100)) % rows) * 0x40
            r = a + b + c + d + e + f + g + h + m + n
            x = source[r // 2]
            if r % 2 == 1:
                x >>= 4
            v[j] = x & 0xF
        tex_view.set_u8(offs + i, v[0] | (v[1] << 4))
