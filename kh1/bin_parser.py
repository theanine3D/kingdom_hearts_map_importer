"""Kingdom Hearts (PS2) map geometry parser.

A map is a .BIN/.IMG pair: the .BIN holds geometry as pre-recorded
PS2 VIF (VU1 DMA) packets plus skybox texture data; the .IMG holds
map texture data, CLUTs, and UV animation tables.
"""

from . import tex_parser as bin_tex
from .dataview import DataView
from .types import BinFile, Mesh, Submesh, UVAnimInfo


def _init_mesh(view: DataView, bounding_box_offs: int, mesh_out: Mesh) -> None:
    bx, by, bz = [], [], []
    for i in range(8):
        bx.append(view.get_f32(bounding_box_offs + i * 0x10))
        by.append(view.get_f32(bounding_box_offs + i * 0x10 + 0x4))
        bz.append(view.get_f32(bounding_box_offs + i * 0x10 + 0x8))
    mesh_out.bbox_min = (min(bx), min(by), min(bz))
    mesh_out.bbox_max = (max(bx), max(by), max(bz))
    mesh_out.layer = int(view.get_f32(bounding_box_offs + 0x4C))


def _process_triangle_strips(view: DataView, offs: int, submesh_out: Submesh) -> int:
    qwc = view.get_u8(offs)
    offs += 2
    for i in range(qwc):
        submesh_out.vtx.append((
            view.get_f32(offs),
            view.get_f32(offs + 0x4),
            view.get_f32(offs + 0x8),
        ))
        # The W component doubles as strip connectivity/winding: sign selects
        # the winding, and a raw low byte of 0x2 marks a double-sided face.
        w = view.get_f32(offs + 0xC)
        if i > 0 and abs(w) > 1e-6:
            double_sided = view.get_u8(offs + 0xC) == 0x2
            if w < 0 or double_sided:
                submesh_out.ind.extend((i, i - 1, i - 2))
            if w > 0 or double_sided:
                submesh_out.ind.extend((i - 2, i - 1, i))
        offs += 0x10
    return offs


def _process_vertex_colors(view: DataView, offs: int, submesh_out: Submesh) -> int:
    qwc = view.get_u8(offs)
    offs += 2
    for i in range(qwc):
        submesh_out.vcol.append((
            view.get_u8(offs + i * 0x4) / 256,
            view.get_u8(offs + i * 0x4 + 0x1) / 256,
            view.get_u8(offs + i * 0x4 + 0x2) / 256,
            view.get_u8(offs + i * 0x4 + 0x3) / 128,  # PS2 alpha: 0x80 = 1.0
        ))
    return offs + qwc * 0x4


def _process_uvs(view: DataView, offs: int, submesh_out: Submesh) -> int:
    qwc = view.get_u8(offs)
    cmd = view.get_u8(offs + 0x1)
    anim = (cmd & 0x8) > 0
    width = 8 if anim else 4
    offs += 2
    for i in range(qwc):
        # 12.4 fixed point, normalized to the texture block dimensions.
        submesh_out.uv.append((
            view.get_i16(offs + i * width) / 4096,
            view.get_i16(offs + i * width + 0x2) / 4096,
        ))
        submesh_out.uv_scroll_index.append((
            view.get_u16(offs + i * width + 0x4) if anim else 0,
            view.get_u16(offs + i * width + 0x6) if anim else 0,
        ))
    return offs + qwc * width


def _process_texture_tag(view: DataView, offs: int, mesh: Mesh, submesh_out: Submesh,
                         texture_blocks_out: list[bin_tex.TextureBlock]) -> int:
    if view.get_u8(offs) == 0x5:
        # Indexed data and color table are unpacked directly, not from a texture bank.
        return _process_texture_unpack(view, offs, mesh, submesh_out, texture_blocks_out)
    properties_offs = offs + 0x14
    bounds_offs = offs + 0x24
    # Quick hack to handle cases where these two blocks are occasionally stored out of order.
    if view.get_u8(offs + 0x1C) > view.get_u8(offs + 0x2C):
        properties_offs = offs + 0x24
        bounds_offs = offs + 0x14
    bank = 1 if (view.get_u8(properties_offs + 0x2) & 0x80) > 0 else 0
    data_offs_base = view.get_u16(properties_offs) * 0x100
    data_offs = (data_offs_base - 0x260000) if bank == 0 else (data_offs_base // 4)
    color_table_offs = ((view.get_u16(properties_offs + 0x4) & 0x3FF0) >> 4) * 0x80

    texture_block = None
    for block in texture_blocks_out:
        if block.bank == bank and block.data_offs == data_offs:
            texture_block = block
            break
    if texture_block is None:
        bit_depth = 4 if (view.get_u8(properties_offs + 0x2) & 0x40) > 0 else 8
        deswizzle = bank == 0 and data_offs >= 0x100000
        texture_block = bin_tex.TextureBlock(
            width=256 if bit_depth == 8 else 512, height=256,
            bit_depth=bit_depth, bank=bank, data_offs=data_offs, deswizzle=deswizzle)
        texture_blocks_out.append(texture_block)
    texture_index = 0
    for texture in texture_block.textures:
        if texture.color_table_offs == color_table_offs:
            break
        texture_index += 1
    if texture_index == len(texture_block.textures):
        texture = bin_tex.Texture(texture_index, texture_block, color_table_offs, mesh.translucent)
        _parse_texture_bounds(view, bounds_offs, texture)
        texture_block.textures.append(texture)
    submesh_out.texture_block = texture_block
    submesh_out.texture_index = texture_index
    return offs + 0x34


def _process_texture_unpack(view: DataView, offs: int, mesh: Mesh, submesh_out: Submesh,
                            texture_blocks_out: list[bin_tex.TextureBlock]) -> int:
    tex_data_offs = 0
    tex_clut_offs = 0
    tex_width = 0
    tex_size = 0
    deswizzle = True
    for _ in range(3):
        block_id = view.get_u8(offs)
        if block_id == 0x5:
            block_type = view.get_u8(offs + 0x15)
            if block_type == 0x36:
                tex_data_offs = offs + 0x68
                tex_width = view.get_u8(offs + 0x34) * 2
                tex_size = tex_width * view.get_u8(offs + 0x38) * 2
                if (view.get_u8(offs + 0x17) & 0x10) > 0:
                    deswizzle = False
                    tex_width //= 2
                    tex_size = tex_size // (8 if (view.get_u8(offs + 0x17) & 0x4) > 0 else 4)
            elif block_type == 0x3A:
                tex_clut_offs = offs + 0x68
            data_size = (view.get_u16(offs + 0x54) & 0xFFFE) * 0x10
            offs += data_size + 0x68
        elif block_id == 0x4:
            properties_offs = offs + 0x24
            bounds_offs = offs + 0x34
            # Quick hack to handle cases where these two blocks are occasionally stored out of order.
            if view.get_u8(offs + 0x2C) > view.get_u8(offs + 0x3C):
                properties_offs = offs + 0x34
                bounds_offs = offs + 0x24
            tex_bit_depth = 4 if (view.get_u8(properties_offs + 0x2) & 0x40) > 0 else 8
            tex_height = (tex_size // tex_width) * (2 if tex_bit_depth == 4 else 1)

            texture_block = bin_tex.TextureBlock(
                width=tex_width, height=tex_height, bit_depth=tex_bit_depth,
                bank=-1, data_offs=tex_data_offs, deswizzle=deswizzle)
            texture_blocks_out.append(texture_block)

            texture = bin_tex.Texture(0, texture_block, tex_clut_offs, mesh.translucent)
            _parse_texture_bounds(view, bounds_offs, texture)
            texture_block.textures.append(texture)
            submesh_out.texture_block = texture_block
            submesh_out.texture_index = 0

            offs += 0x44
    return offs


def _parse_texture_bounds(view: DataView, offs: int, texture_out: bin_tex.Texture) -> None:
    texture_out.tiled_u = (view.get_u8(offs) & 0xF0) == 0xF0
    texture_out.tiled_v = (view.get_u8(offs + 0x3) & 0xF) == 0xF
    if texture_out.tiled_u:
        texture_out.clip_right = ((view.get_u8(offs + 0x1) & 0xF) + 1) * 0x10 - 1
    else:
        texture_out.clip_left = (view.get_u8(offs + 0x1) & 0x3F) * 0x10
        texture_out.clip_right = (view.get_u8(offs + 0x2) + 1) * 4 - 1
    if texture_out.tiled_v:
        texture_out.clip_bottom = (((view.get_u8(offs + 0x3) & 0xF0) >> 4) + 1) * 0x10 - 1
    else:
        texture_out.clip_top = ((view.get_u8(offs + 0x3) >> 4) & 0xF) * 0x10
        texture_out.clip_bottom = ((view.get_u16(offs + 0x4) >> 4) + 1) * 4 - 1


def _parse_vif_packets(view: DataView, offs: int, end_offs: int, first: bool,
                       mesh_out: Mesh, texture_blocks_out: list[bin_tex.TextureBlock],
                       warn) -> None:
    submesh: Submesh | None = None
    last_texture_block = None
    last_texture_index = -1
    while offs < end_offs:
        cmd = view.get_u16(offs)
        offs += 2
        if cmd == 0x0101:    # STCYCLE (write)
            offs += 2
        elif cmd == 0x8000:  # Begin unpack
            submesh = Submesh()
            mesh_out.submeshes.append(submesh)
            offs += 0x12 if first else 0x16
        elif cmd == 0x8001:  # Triangle strips
            offs = _process_triangle_strips(view, offs, submesh)
        elif cmd == 0xC002:  # Vertex colors
            offs = _process_vertex_colors(view, offs, submesh)
        elif cmd == 0x8003:  # UVs
            offs = _process_uvs(view, offs, submesh)
        elif cmd == 0x1100:  # FLUSH (texture tag)
            offs = _process_texture_tag(view, offs, mesh_out, submesh, texture_blocks_out)
            last_texture_block = submesh.texture_block
            last_texture_index = submesh.texture_index
        elif cmd == 0x0:
            pass
        elif cmd == 0x1700:  # MSCNT (end submesh)
            if submesh.texture_block is None:
                submesh.texture_block = last_texture_block
                submesh.texture_index = last_texture_index
        else:
            # Warn and keep the partial mesh.
            warn(f"VIF parse error: unknown command 0x{cmd:x} at offset 0x{offs:x}")
            return


def _parse_geometry_sector(view: DataView, geom_sector_offs: int, is_skybox: bool,
                           meshes_out: list[Mesh],
                           texture_blocks_out: list[bin_tex.TextureBlock],
                           warn) -> None:
    if is_skybox:
        vif_table_count = 4
        vif_table_offs = geom_sector_offs + 0x80
        bounding_box_table_offs = geom_sector_offs
    else:
        vif_table_count = view.get_u16(geom_sector_offs) * 2 + 2
        vif_table_offs = geom_sector_offs + view.get_u32(geom_sector_offs + 0x4)
        bounding_box_table_offs = geom_sector_offs + 0x10

    column_count = vif_table_count // 2
    for i in range(vif_table_count):
        index = (i - column_count) * 2 + 1 if i >= column_count else i * 2
        size = (view.get_u32(vif_table_offs + index * 8) & 0xFFFFFFF) * 0x10
        if size == 0:
            continue
        offs = geom_sector_offs + view.get_u32(vif_table_offs + index * 8 + 0x4)
        end_offs = offs + size

        mesh = Mesh()
        mesh.translucent = (index % 2) == 1
        if index > 1:
            bounding_box_offs = bounding_box_table_offs + (index // 2 - 1) * 0x80
            _init_mesh(view, bounding_box_offs, mesh)
        _parse_vif_packets(view, offs, end_offs, index == 0, mesh, texture_blocks_out, warn)
        meshes_out.append(mesh)


def _build_textures(bin_view: DataView, img_view: DataView,
                    map_texture_blocks: list[bin_tex.TextureBlock],
                    sky0_texture_blocks: list[bin_tex.TextureBlock],
                    sky1_texture_blocks: list[bin_tex.TextureBlock]) -> None:
    tex_data_offs = img_view.get_u32(0x18)
    tex_data_size = img_view.get_u32(0x1C)
    tex_clut_offs = img_view.get_u32(0x10)
    tex_clut_size = img_view.get_u32(0x14)

    # Texture data may overflow the .IMG; the remainder lives at the end of
    # the .BIN's map sector.
    tex_data_ovf_size = max(0, tex_data_size - (img_view.byte_length - tex_data_offs))
    map_sector_offs = bin_view.get_u32(0x18)
    map_sector_size = bin_view.get_u32(0x1C)

    tex_data_view = img_view.subview(tex_data_offs, tex_data_size - tex_data_ovf_size)
    tex_clut_view = img_view.subview(tex_clut_offs, tex_clut_size)
    tex_data_ovf_view = bin_view.subview(
        map_sector_offs + map_sector_size - tex_data_ovf_size, tex_data_ovf_size)
    for texture_block in map_texture_blocks:
        if texture_block.is_ovf():
            texture_block.build(tex_data_ovf_view, tex_clut_view)
        else:
            texture_block.build(tex_data_view, tex_clut_view)
    for texture_block in sky0_texture_blocks:
        texture_block.build(bin_view, bin_view)
    for texture_block in sky1_texture_blocks:
        texture_block.build(bin_view, bin_view)


def _parse_uv_anim_sectors(view: DataView,
                           map_texture_blocks: list[bin_tex.TextureBlock]) -> UVAnimInfo:
    uv_anim_table_sector_offs = view.get_u32(0x08)

    sky1_rot_y_factor = view.get_f32(uv_anim_table_sector_offs + 0x34)
    uv_scroll_table = [0.0] * 0x22
    for i in range(0x20):
        uv_scroll_table[i + 2] = view.get_f32(uv_anim_table_sector_offs + 0x40 + i * 4)

    uv_sprite_sector_offs = view.get_u32(0)
    uv_sprite_sector_size = view.get_u32(0x04)
    sprite_count = uv_sprite_sector_size // 0xA0
    for i in range(sprite_count):
        offs = uv_sprite_sector_offs + i * 0xA0
        num_frames = min(0x20, view.get_u32(offs))
        if num_frames == 0:
            continue
        sprite_left = view.get_u16(offs + 0x4)
        sprite_top = view.get_u16(offs + 0x6)
        data_offset_u = view.get_u16(offs + 0x10)
        data_width_u = view.get_u16(offs + 0x12)
        bank = 1 if (data_width_u & 0x800) > 0 else 0
        tex_data_offs = (data_offset_u * 0x100 - 0x260000) if bank == 0 else (data_offset_u * 0x100 // 4)
        # Locate texture for this sprite sheet.
        texture_block = None
        texture = None
        for block in map_texture_blocks:
            if block.bank != bank or block.data_offs != tex_data_offs:
                continue
            for cur_tex in block.textures:
                if cur_tex.clip_left == sprite_left and cur_tex.clip_top == sprite_top:
                    texture_block = block
                    texture = cur_tex
                    break
            if texture is not None:
                break
        if texture_block is None or texture is None:
            continue
        sprite_width = view.get_u32(offs + 0x18)
        sprite_height = view.get_u32(offs + 0x1C)
        speed = view.get_u32(offs + 0x8)
        sprite_left_anim = [view.get_u16(offs + 0x20 + j * 4) for j in range(num_frames)]
        sprite_top_anim = [view.get_u16(offs + 0x22 + j * 4) for j in range(num_frames)]
        texture.sprite_anim = bin_tex.TextureSpriteAnim(
            texture_block, texture, sprite_left_anim, sprite_top_anim,
            num_frames, sprite_width, sprite_height, speed)

    return UVAnimInfo(uv_scroll_table=uv_scroll_table, sky1_rot_y_factor=sky1_rot_y_factor)


def parse(bin_data: bytes, img_data: bytes, warn=print) -> BinFile:
    bin_view = DataView(bytearray(bin_data))
    img_view = DataView(bytearray(img_data))

    map_sector_offs = bin_view.get_u32(0x18)
    sky0_sector_offs = bin_view.get_u32(0x20)
    sky1_sector_offs = bin_view.get_u32(0x28)

    map_meshes: list[Mesh] = []
    map_texture_blocks: list[bin_tex.TextureBlock] = []
    _parse_geometry_sector(bin_view, map_sector_offs, False, map_meshes, map_texture_blocks, warn)

    sky0_meshes: list[Mesh] = []
    sky0_texture_blocks: list[bin_tex.TextureBlock] = []
    _parse_geometry_sector(bin_view, sky0_sector_offs, True, sky0_meshes, sky0_texture_blocks, warn)

    sky1_meshes: list[Mesh] = []
    sky1_texture_blocks: list[bin_tex.TextureBlock] = []
    _parse_geometry_sector(bin_view, sky1_sector_offs, True, sky1_meshes, sky1_texture_blocks, warn)

    _build_textures(bin_view, img_view, map_texture_blocks, sky0_texture_blocks, sky1_texture_blocks)

    uv_anim_info = _parse_uv_anim_sectors(img_view, map_texture_blocks)

    return BinFile(
        map_meshes=map_meshes,
        map_texture_blocks=map_texture_blocks,
        sky0_meshes=sky0_meshes,
        sky0_texture_blocks=sky0_texture_blocks,
        sky1_meshes=sky1_meshes,
        sky1_texture_blocks=sky1_texture_blocks,
        uv_anim_info=uv_anim_info,
    )
