"""Organize extracted map files into named world folders.

Uses the bundled worlds.json (derived from the OpenKH project's KH1
worlds.md) to move each map .bin/.img pair from a flat extraction folder
into Worlds/<World>/<Area> (<id>).<ext>, giving files human-readable names
like "Worlds/Agrabah/Desert (al00_01).bin".

Pure Python, no Blender dependencies.
"""

import json
import os
import re

WORLDS_JSON_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "worlds.json")
MAP_FILE_RE = re.compile(r"([a-z]{2})\d{2}_\d{2}\.(bin|img)$")

# Windows-illegal filename characters; ": " reads well as " - ".
_COLON_RE = re.compile(r":\s*")
_INVALID_RE = re.compile(r'[\\/:*?"<>|]')


def load_worlds() -> tuple[dict[str, str], dict[str, str]]:
    """Returns (world prefix -> world name, map id -> area name)."""
    with open(WORLDS_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["worlds"], data["areas"]


def area_to_stem(area: str, map_id: str) -> str:
    """Filesystem-safe stem: 'Cave: Hall' + 'al00_04' -> 'Cave - Hall (al00_04)'.

    The id suffix keeps stems unique (several beta maps share one area name)
    and preserves the original reference."""
    name = _COLON_RE.sub(" - ", area)
    name = _INVALID_RE.sub("", name).strip()
    return f"{name} ({map_id})"


def organize_worlds(folder: str):
    """Move map files from `folder` into Worlds/<World>/ subfolders.

    Returns a stats dict: pairs moved with named areas, files moved with
    only a world match (original name kept), and the world folders used.
    """
    worlds, areas = load_worlds()
    stats = {"named": 0, "unnamed": 0, "worlds": set(), "files": 0}

    for entry in sorted(os.listdir(folder)):
        match = MAP_FILE_RE.fullmatch(entry)
        if not match or not os.path.isfile(os.path.join(folder, entry)):
            continue
        prefix = match.group(1)
        world = worlds.get(prefix)
        if world is None:
            continue
        map_id, ext = os.path.splitext(entry)
        area = areas.get(map_id)
        stem = area_to_stem(area, map_id) if area else map_id

        dst_dir = os.path.join(folder, "Worlds", world)
        os.makedirs(dst_dir, exist_ok=True)
        os.replace(os.path.join(folder, entry),
                   os.path.join(dst_dir, stem + ext))

        stats["files"] += 1
        stats["worlds"].add(world)
        # Count pairs once, on the .bin.
        if ext == ".bin":
            stats["named" if area else "unnamed"] += 1
    return stats
