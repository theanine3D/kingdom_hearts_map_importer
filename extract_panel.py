"""World Properties panel embedding the KH1 ISO extractor."""

import os
import time

import bpy
from bpy.props import PointerProperty, StringProperty

from .kh1 import iso_extract, worlds


class KH1ExtractSettings(bpy.types.PropertyGroup):
    iso_path: StringProperty(
        name="Game ISO",
        description="Kingdom Hearts ISO image (Japanese original or Final Mix)",
        subtype="FILE_PATH",
    )
    out_dir: StringProperty(
        name="Output Folder",
        description="Folder to extract the game files into",
        subtype="DIR_PATH",
    )


class KH1_OT_extract_iso(bpy.types.Operator):
    """Extract all game files (including map .bin/.img pairs) from the ISO"""
    bl_idname = "kh1.extract_iso"
    bl_label = "Extract"

    @classmethod
    def poll(cls, context):
        settings = context.scene.kh1_extract
        return bool(settings.iso_path) and bool(settings.out_dir)

    def execute(self, context):
        settings = context.scene.kh1_extract
        iso_path = bpy.path.abspath(settings.iso_path)
        out_dir = bpy.path.abspath(settings.out_dir)

        if not os.path.isfile(iso_path):
            self.report({"ERROR"}, f"ISO not found: {iso_path}")
            return {"CANCELLED"}
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.report({"ERROR"}, f"Cannot create output folder: {exc}")
            return {"CANCELLED"}

        wm = context.window_manager
        wm.progress_begin(0, 100)
        start_time = time.monotonic()

        def progress(done, total, name):
            wm.progress_update(int(done * 100 / max(1, total)))
            if done % 200 == 0:
                print(f"KH1 extract: {done}/{total} {name}")

        try:
            num_files, num_unknown = iso_extract.extract_iso(
                iso_path, out_dir, progress)
        except iso_extract.UnsupportedIsoError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Extraction failed: {exc}")
            return {"CANCELLED"}
        finally:
            wm.progress_end()

        elapsed = time.monotonic() - start_time
        message = (f"Extracted {num_files} files to {out_dir} "
                   f"in {elapsed:.0f}s")
        if num_unknown:
            message += f" ({num_unknown} unknown filenames -> unknown/)"
        self.report({"INFO"}, message)
        return {"FINISHED"}


class KH1_OT_organize_worlds(bpy.types.Operator):
    """Move the extracted map files into Worlds/<World name>/ subfolders,
    renamed after their in-game areas (e.g. Agrabah/Desert (al00_01).bin)"""
    bl_idname = "kh1.organize_worlds"
    bl_label = "Rename & Reorganize World Models"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.kh1_extract.out_dir)

    def execute(self, context):
        folder = bpy.path.abspath(context.scene.kh1_extract.out_dir)
        if not os.path.isdir(folder):
            self.report({"ERROR"}, f"Output folder not found: {folder}")
            return {"CANCELLED"}

        try:
            stats = worlds.organize_worlds(folder)
        except Exception as exc:
            self.report({"ERROR"}, f"Reorganize failed: {exc}")
            return {"CANCELLED"}

        if stats["files"] == 0:
            self.report({"WARNING"},
                        "No map files found to organize. Extract the ISO "
                        "first, or the files may already be organized.")
            return {"CANCELLED"}

        message = (f"Moved {stats['named'] + stats['unnamed']} scenes into "
                   f"{len(stats['worlds'])} world folders under "
                   f"{os.path.join(folder, 'Worlds')}")
        if stats["unnamed"]:
            message += f" ({stats['unnamed']} kept their original names)"
        self.report({"INFO"}, message)

        if not bpy.app.background and context.window is not None:  # popups need a UI
            def draw_popup(menu, _context):
                menu.layout.label(text="World models have been renamed and "
                                       "reorganized into a new 'Worlds' folder.")
                menu.layout.label(text=message)

            context.window_manager.popup_menu(
                draw_popup, title="Reorganize Complete", icon="CHECKMARK")
        return {"FINISHED"}


class KH1_PT_iso_extract(bpy.types.Panel):
    bl_label = "Kingdom Hearts ISO Extractor"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.kh1_extract

        box = layout.box()
        box.label(text="Only Japanese ISOs are supported", icon="INFO")
        box.label(text="(original version or Final Mix)")

        col = layout.column(align=True)
        col.prop(settings, "iso_path")
        col.prop(settings, "out_dir")
        layout.operator(KH1_OT_extract_iso.bl_idname, icon="PACKAGE")

        layout.separator()
        layout.operator(KH1_OT_organize_worlds.bl_idname, icon="NEWFOLDER")


_classes = (KH1ExtractSettings, KH1_OT_extract_iso, KH1_OT_organize_worlds,
            KH1_PT_iso_extract)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.kh1_extract = PointerProperty(type=KH1ExtractSettings)


def unregister():
    del bpy.types.Scene.kh1_extract
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
