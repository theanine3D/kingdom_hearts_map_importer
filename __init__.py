bl_info = {
    "name": "Kingdom Hearts Map Importer (.bin/.img)",
    "author": "Theanine3D",
    "version": (1, 0 ,0),
    "blender": (5, 0, 0),
    "location": "File > Import > Kingdom Hearts Map (.bin)",
    "description": "Import 3D scene models from Kingdom Hearts (PS2)",
    "category": "Import-Export",
}


def register():
    from . import extract_panel, import_operator
    import_operator.register()
    extract_panel.register()


def unregister():
    from . import extract_panel, import_operator
    extract_panel.unregister()
    import_operator.unregister()
