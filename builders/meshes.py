"""Parsed map geometry -> Blender mesh objects.

UVs in the map data are normalized to the 256/512-px texture *block*; here
they are remapped into each texture's clip rect so they suit the standalone
per-texture images created by the images builder.
"""

import bpy

from .materials import COLOR_ATTR_NAME


def build_group_objects(bin_meshes, base_name, images, material_cache, mode, warn,
                        uv_scroll_table=None, import_anims=False):
    """Build objects for one geometry group (map, sky0, or sky1).

    mode 'LAYER' merges all meshes sharing a layer index into one object;
    mode 'MESH' keeps one object per map chunk (as stored in the file).
    Returns (objects, skipped_submesh_count).
    """
    objects = []
    skipped = 0
    if mode == "LAYER":
        by_layer: dict[int, list] = {}
        for mesh in bin_meshes:
            by_layer.setdefault(mesh.layer, []).append(mesh)
        for layer in sorted(by_layer):
            parts, n_skipped = _collect_parts(by_layer[layer])
            skipped += n_skipped
            if parts:
                name = f"{base_name}_layer{layer}" if len(by_layer) > 1 else base_name
                obj = _build_object(name, parts, images, material_cache, warn,
                                    uv_scroll_table, import_anims)
                obj["kh1_layer"] = layer
                objects.append(obj)
    else:
        for i, mesh in enumerate(bin_meshes):
            parts, n_skipped = _collect_parts([mesh])
            skipped += n_skipped
            if parts:
                obj = _build_object(f"{base_name}_m{i:04d}", parts, images,
                                    material_cache, warn, uv_scroll_table, import_anims)
                obj["kh1_layer"] = mesh.layer
                obj["kh1_translucent"] = mesh.translucent
                objects.append(obj)
    return objects, skipped


def _collect_parts(bin_meshes):
    """Flatten meshes into renderable (submesh, translucent) pairs.

    Submeshes that never received a texture tag are not rendered by the
    game viewer; skip them the same way.
    """
    parts = []
    skipped = 0
    for mesh in bin_meshes:
        for submesh in mesh.submeshes:
            if not submesh.vtx or not submesh.ind:
                continue
            if submesh.texture_block is None or submesh.texture_index < 0:
                skipped += 1
                continue
            parts.append((submesh, mesh.translucent))
    return parts, skipped


# The game shader advances UVs by tableValue * 0.000005 per millisecond.
SCROLL_UV_PER_SECOND_FACTOR = 0.005


def _submesh_scroll(submesh, uv_scroll_table):
    """Look up this submesh's UV scroll rate (block-normalized UV/second).

    Scroll indices are stored per vertex but are uniform per submesh in
    practice; use the first pair that yields a nonzero rate.
    """
    if not uv_scroll_table:
        return (0.0, 0.0)
    n = len(uv_scroll_table)
    for iu, iv in submesh.uv_scroll_index:
        su = uv_scroll_table[iu * 2] if 0 <= iu * 2 < n else 0.0
        sv = uv_scroll_table[iv * 2 + 1] if 0 <= iv * 2 + 1 < n else 0.0
        if su != 0.0 or sv != 0.0:
            return (su * SCROLL_UV_PER_SECOND_FACTOR, sv * SCROLL_UV_PER_SECOND_FACTOR)
    return (0.0, 0.0)


def _build_object(name, parts, images, material_cache, warn,
                  uv_scroll_table=None, import_anims=False):
    verts = []
    vert_uvs = []
    vert_cols = []
    faces = []
    face_mat = []
    materials = []
    mat_slots = {}
    seen_tris = set()

    for submesh, translucent in parts:
        block = submesh.texture_block
        tex = block.textures[submesh.texture_index]
        scroll = _submesh_scroll(submesh, uv_scroll_table) if import_anims else (0.0, 0.0)
        material = material_cache.get(tex, images.get(tex.name()), translucent, scroll)
        slot = mat_slots.get(material.name)
        if slot is None:
            slot = len(materials)
            mat_slots[material.name] = slot
            materials.append(material)

        base = len(verts)
        n = len(submesh.vtx)
        if tex.sprite_anim is not None:
            # Sprite textures sample a frame-sized window; UVs map into the
            # top band of the frame strip (see the images builder).
            tex_w, tex_h = tex.sprite_anim.sprite_width, tex.sprite_anim.sprite_height
            bands = tex.sprite_anim.num_frames if import_anims else 1
        else:
            tex_w, tex_h = tex.width(), tex.height()
            bands = 1
        for i in range(n):
            u, v = submesh.uv[i] if i < len(submesh.uv) else (0.0, 0.0)
            # Block-normalized -> texture-crop-normalized, V flipped for Blender.
            tu = (u * block.width - tex.clip_left) / tex_w
            tv = (v * block.height - tex.clip_top) / tex_h
            vert_uvs.append((tu, 1.0 - tv / bands))
            # Missing colors render as 0.5 gray in the game shader (x2 = identity).
            vert_cols.append(submesh.vcol[i] if i < len(submesh.vcol)
                             else (0.5, 0.5, 0.5, 1.0))
        verts.extend(submesh.vtx)

        ind = submesh.ind
        for t in range(0, len(ind), 3):
            a, b, c = ind[t] + base, ind[t + 1] + base, ind[t + 2] + base
            if a == b or b == c or a == c:
                continue
            key = (a, b, c) if a < b < c else tuple(sorted((a, b, c)))
            if key in seen_tris:
                # Double-sided face: both windings share vertices, but Blender
                # treats them as duplicate polygons. Give the second winding
                # its own vertices.
                new = len(verts)
                for src in (a, b, c):
                    verts.append(verts[src])
                    vert_uvs.append(vert_uvs[src])
                    vert_cols.append(vert_cols[src])
                a, b, c = new, new + 1, new + 2
            else:
                seen_tris.add(key)
            faces.append((a, b, c))
            face_mat.append(slot)

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(verts, [], faces)
    for material in materials:
        mesh_data.materials.append(material)
    mesh_data.polygons.foreach_set("material_index", face_mat)

    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    loop_uvs = [coord for face in faces for vi in face for coord in vert_uvs[vi]]
    uv_layer.data.foreach_set("uv", loop_uvs)

    colors = mesh_data.color_attributes.new(
        name=COLOR_ATTR_NAME, type="FLOAT_COLOR", domain="POINT")
    colors.data.foreach_set("color", [c for col in vert_cols for c in col])

    if mesh_data.validate():
        warn(f"{name}: mesh validation corrected invalid geometry")
    mesh_data.update()

    return bpy.data.objects.new(name, mesh_data)
