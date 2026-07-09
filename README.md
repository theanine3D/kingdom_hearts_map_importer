# Kingdom Hearts (PS2) Map Importer for Blender

Imports scene models from Kingdom Hearts / Kingdom Hearts Final Mix (PS2)
into Blender — meshes, textures, UVs, vertex colors, and display layers.

The map format parser is a Python port of the Kingdom Hearts renderer from
[noclip.website](https://github.com/magcius/noclip.website)
(`src/KingdomHearts/bin.ts`, `bin_tex.ts`).

## Requirements

- Blender 5.0+
- A dump (ISO) of your Kingdom Hearts game disc — Japanese original or
  Final Mix. The addon has a built-in extractor (see below), so no external
  tools are needed.

## Install

Zip the `io_scene_kh1map` folder and install via
`Edit > Preferences > Add-ons > Install from Disk`, or copy the folder into
your Blender `scripts/addons` directory. Enable "Kingdom Hearts Map Importer".

## Extracting the game files

On the right-hand side of the Blender window, go into the World tab, then
open the `Kingdom Hearts ISO Extractor` subpanel. Select your game ISO
and an output folder, then press **Extract**. All game files are pulled out
of the ISO, including the map `.bin`/`.img` pairs the importer reads.

Only the Japanese ISOs (original or Final Mix) are supported. KH1 hides its
files outside the ISO filesystem; the extractor (ported from the
[KH1 decompilation project](https://github.com/ethteck/kh1)) reads the
hidden KINGDOM.IDX file table and decompresses files as needed.

### Rename & Reorganize World Models

To make it easier to find the exact scene you're looking for, the addon
has a "Rename & Reorganize" button that will automatically organize your
extracted map files and rename them with readable scene names from the
[OpenKH](https://openkh.dev/) project's KH1 worlds documentation. For example:

```
kingdom/al00_01.bin  ->  kingdom/Worlds/Agrabah/Desert (al00_01).bin
```

Every `.bin`/`.img` pair is renamed after its in-game area (with the
original id kept in parentheses), so you can browse to "Traverse Town /
1st District" instead of decoding filenames like `tw00_01`. Non-map files
are left untouched, and the renamed pairs import normally.

## Use

`File > Import > Kingdom Hearts Map (.bin)` — pick a map `.bin`; the `.img`
is loaded automatically from the same folder.

Options:

- **Scale** (default 0.01) — map units are large; 0.01 gives roughly
  meter-scale scenes.
- **Import Skyboxes** — SKY0/SKY1 domes as separate collections.
- **Objects** — one object per display layer (default), or one per map chunk
  (matches the file's culling granularity; hundreds of objects).
- **Shading** — *Unlit (faithful)*: emission materials, since the game's
  lighting is baked into vertex colors; or *Principled BSDF* for
  relighting/export.
- **Import texture animations** (default on) — recreates the game's texture
  animations as keyframed material node animations:
  - *UV scroll* (rivers, waterfalls): a Mapping node with linear keyframes
    and linear extrapolation, so it scrolls forever at the game's rate.
  - *Sprite sheets* (shoreline foam, etc.): frames are baked into a vertical
    strip image and a stepped, cycled Mapping animation walks through them
    at the game's frame timing.
  - *SKY1 rotation*: the second sky layer slowly spins about the vertical
    axis (an animated empty parents the Sky1 objects).
  Keyframe timing uses the scene FPS at import time. Submeshes with mixed
  per-vertex scroll rates (rare) use their first nonzero rate.
- **Disable Color Correction** (default on) — sets the scene's View
  Transform to Standard (and Look to None), so the decoded textures and
  vertex colors match the original game instead of being reshaped by
  Blender's default AgX/Filmic view transform. Turn this off if you're
  compositing the import into a scene that already uses AgX/Filmic
  elsewhere and want consistent tonemapping instead of game-accurate colors.

