"""Parsed map data structures"""

from dataclasses import dataclass, field

from .tex_parser import TextureBlock


@dataclass
class Submesh:
    texture_block: TextureBlock | None = None
    texture_index: int = -1
    # Parallel per-vertex arrays.
    vtx: list[tuple[float, float, float]] = field(default_factory=list)
    vcol: list[tuple[float, float, float, float]] = field(default_factory=list)
    uv: list[tuple[float, float]] = field(default_factory=list)          # block-normalized
    uv_scroll_index: list[tuple[int, int]] = field(default_factory=list)
    ind: list[int] = field(default_factory=list)                          # triangle list


@dataclass
class Mesh:
    submeshes: list[Submesh] = field(default_factory=list)
    layer: int = 0
    translucent: bool = False
    bbox_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bbox_max: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class UVAnimInfo:
    uv_scroll_table: list[float]
    sky1_rot_y_factor: float


@dataclass
class BinFile:
    map_meshes: list[Mesh]
    map_texture_blocks: list[TextureBlock]
    sky0_meshes: list[Mesh]
    sky0_texture_blocks: list[TextureBlock]
    sky1_meshes: list[Mesh]
    sky1_texture_blocks: list[TextureBlock]
    uv_anim_info: UVAnimInfo
