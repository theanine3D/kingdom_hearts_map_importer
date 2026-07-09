import math
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

from .builders import images as images_builder
from .builders import meshes as meshes_builder
from .builders.anim import find_fcurves
from .builders.materials import MaterialCache
from .kh1 import bin_parser


class ImportKH1Map(bpy.types.Operator, ImportHelper):
    """Import a Kingdom Hearts (PS2) map (.bin with .img alongside)"""
    bl_idname = "import_scene.kh1_map"
    bl_label = "Import Kingdom Hearts Map"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".bin"
    filter_glob: StringProperty(default="*.bin", options={"HIDDEN"})

    scale: FloatProperty(
        name="Scale",
        description="Uniform scale applied on import (map units are large)",
        default=0.01, min=0.0001, max=1000.0,
    )
    import_sky: BoolProperty(
        name="Import Skyboxes",
        description="Import the SKY0/SKY1 skybox geometry as separate collections",
        default=True,
    )
    import_anims: BoolProperty(
        name="Import texture animations",
        description="Recreate UV scrolling and sprite-sheet texture animations "
                    "(waterfalls, shorelines) as keyframed material animations",
        default=True,
    )
    object_mode: EnumProperty(
        name="Objects",
        description="How to split the map into Blender objects",
        items=(
            ("LAYER", "One object per layer",
             "Merge map chunks that share a display layer (recommended)"),
            ("MESH", "One object per map chunk",
             "Keep the file's chunk granularity (hundreds of small objects)"),
        ),
        default="LAYER",
    )
    shading: EnumProperty(
        name="Shading",
        description="Material style",
        items=(
            ("EMISSION", "Unlit (faithful)",
             "Emission shader; game lighting is baked into vertex colors"),
            ("PRINCIPLED", "Principled BSDF",
             "Standard shaded materials, for relighting or export"),
        ),
        default="EMISSION",
    )
    disable_color_management: BoolProperty(
        name="Disable Color Correction",
        description="Set the scene's View Transform to Standard so viewport "
                    "and render colors match the original game, instead of "
                    "being reshaped by Blender's default AgX/Filmic look",
        default=True,
    )

    def execute(self, context):
        bin_path = self.filepath
        img_path = os.path.splitext(bin_path)[0] + ".img"
        if not os.path.isfile(img_path):
            self.report({"ERROR"}, f"Companion .img not found: {img_path}")
            return {"CANCELLED"}
        stem = os.path.splitext(os.path.basename(bin_path))[0]

        with open(bin_path, "rb") as f:
            bin_data = f.read()
        with open(img_path, "rb") as f:
            img_data = f.read()

        warnings: list[str] = []
        try:
            bin_file = bin_parser.parse(bin_data, img_data, warn=warnings.append)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to parse {stem}: {exc}")
            return {"CANCELLED"}

        if self.disable_color_management:
            self._disable_color_management(context, warnings.append)
        if self.shading == "EMISSION":
            self._disable_eevee_shadows(context, warnings.append)

        texture_groups = [bin_file.map_texture_blocks]
        if self.import_sky:
            texture_groups += [bin_file.sky0_texture_blocks, bin_file.sky1_texture_blocks]
        images = images_builder.build_images(texture_groups, stem, self.import_anims)
        fps = context.scene.render.fps / context.scene.render.fps_base
        material_cache = MaterialCache(stem, self.shading, fps, self.import_anims)

        # Map data is Y-down and mirrored relative to Blender's world
        # applies a 180-degree Z rotation to the same data before its Y-up view).
        transform = (Matrix.Rotation(math.radians(90.0), 4, "X")
                     @ Matrix.Rotation(math.pi, 4, "Z")
                     @ Matrix.Scale(self.scale, 4))

        root = bpy.data.collections.new(stem)
        context.scene.collection.children.link(root)

        groups = [(bin_file.map_meshes, "Map", f"{stem}_map", self.object_mode)]
        if self.import_sky:
            groups.append((bin_file.sky0_meshes, "Sky0", f"{stem}_sky0", "LAYER"))
            groups.append((bin_file.sky1_meshes, "Sky1", f"{stem}_sky1", "LAYER"))

        total_objects = 0
        total_skipped = 0
        sky1_objects = []
        sky1_collection = None
        for bin_meshes, coll_name, base_name, mode in groups:
            objects, skipped = meshes_builder.build_group_objects(
                bin_meshes, base_name, images, material_cache, mode, warnings.append,
                bin_file.uv_anim_info.uv_scroll_table, self.import_anims)
            total_skipped += skipped
            if not objects:
                continue
            collection = bpy.data.collections.new(coll_name)
            root.children.link(collection)
            for obj in objects:
                obj.matrix_world = transform
                collection.objects.link(obj)
            total_objects += len(objects)
            if coll_name == "Sky1":
                sky1_objects = objects
                sky1_collection = collection

        if self.import_anims and sky1_objects:
            self._animate_sky1(bin_file.uv_anim_info.sky1_rot_y_factor,
                               sky1_objects, sky1_collection, f"{stem}_sky1_rotation", fps)

        for message in warnings:
            self.report({"WARNING"}, message)
        return self._finish(stem, total_objects, len(images), total_skipped)

    def _disable_color_management(self, context, warn):
        """The decoded textures and vertex colors are already in the game's
        display-ready color space; Blender's default AgX/Filmic view
        transform would reshape contrast and desaturate them relative to
        the original game."""
        view_settings = context.scene.view_settings
        try:
            view_settings.view_transform = "Standard"
        except TypeError:
            warn("Could not set View Transform to Standard: not available "
                "in this Blender's color management configuration")
            return
        try:
            view_settings.look = "None"
        except TypeError:
            pass

    def _disable_eevee_shadows(self, context, warn):
        """Unlit materials use Emission, so EEVEE never has anything to
        shadow; leaving shadow sampling on only costs viewport/render
        performance. Set on the scene's EEVEE settings regardless of the
        currently active render engine, so it takes effect if the user
        switches to EEVEE later."""
        eevee = context.scene.eevee
        if not hasattr(eevee, "use_shadows"):
            warn("Could not disable EEVEE shadows: 'use_shadows' not found "
                "on this Blender's EEVEE settings")
            return
        eevee.use_shadows = False

    def _animate_sky1(self, factor, objects, collection, name, fps):
        """The game spins the SKY1 layer about the vertical axis by
        factor * time_ms / 6pi radians. Game +Y maps to Blender -Z under the
        import transform, so drive a parent empty's Z rotation, negated."""
        if factor == 0.0:
            return
        rate = -factor * 1000.0 / (6.0 * math.pi)  # radians per second
        empty = bpy.data.objects.new(name, None)
        empty["kh1_sky1_rot_y_factor"] = factor
        collection.objects.link(empty)
        for obj in objects:
            obj.parent = empty
        empty.rotation_mode = "XYZ"
        empty.rotation_euler = (0.0, 0.0, 0.0)
        empty.keyframe_insert("rotation_euler", index=2, frame=1.0)
        empty.rotation_euler[2] = rate
        empty.keyframe_insert("rotation_euler", index=2, frame=1.0 + fps)
        for fcurve in find_fcurves(empty.animation_data, "rotation_euler"):
            fcurve.extrapolation = "LINEAR"
            for point in fcurve.keyframe_points:
                point.interpolation = "LINEAR"

    def _finish(self, stem, total_objects, num_images, total_skipped):
        self.report(
            {"INFO"},
            f"Imported {stem}: {total_objects} objects, {num_images} textures"
            + (f", {total_skipped} untextured submeshes skipped" if total_skipped else ""))
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(ImportKH1Map.bl_idname, text="Kingdom Hearts Map (.bin)")


def register():
    bpy.utils.register_class(ImportKH1Map)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportKH1Map)
