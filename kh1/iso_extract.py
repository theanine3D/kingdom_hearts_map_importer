"""Kingdom Hearts (PS2) ISO extractor.

Port of the KH1 decompilation project's tools/iso/extract.py
(https://github.com/ethteck/kh1). Kingdom Hearts hides its game files
outside the ISO9660 directory tree: the visible file KINGDOM.IDX is a table
of (filename hash, compressed flag, block, length) records, with data blocks
addressed relative to SYSTEM.CNF's position. Hashes are resolved to
filenames via the bundled kingdom_filenames.txt list.

Only the Japanese releases (original and Final Mix) are supported, matching
the upstream extractor. Pure Python, no Blender dependencies.
"""

import os
import struct
from dataclasses import dataclass

BLOCK_LENGTH = 0x800
FILENAMES_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                              "kingdom_filenames.txt")


class UnsupportedIsoError(Exception):
    """The image does not look like a supported Kingdom Hearts ISO."""


@dataclass
class KingdomFile:
    hash: int
    is_compressed: bool
    iso_block: int
    length: int
    filename: str | None = None


def hash_filename(filename: str) -> int:
    value = 0
    for c in filename:
        value = ((value * 2) ^ ((ord(c) << 0x10) % 69665)) & 0xFFFFFFFF
    return value


def load_filenames() -> dict[int, str]:
    result: dict[int, str] = {}
    with open(FILENAMES_PATH, encoding="utf-8") as f:
        for line in f:
            filename = line.strip()
            if filename:
                result[hash_filename(filename)] = filename
    return result


def decompress(src_data: bytes) -> bytearray:
    """The game's backwards LZ/RLE scheme: data is decoded from the end,
    with a trailer of [24-bit size][key byte]."""
    src_index = len(src_data) - 1

    if src_index == 0:
        return bytearray()

    key = src_data[src_index]
    src_index -= 1
    dec_size = (
        src_data[src_index]
        | (src_data[src_index - 1] << 8)
        | (src_data[src_index - 2] << 16)
    )
    src_index -= 3

    dst_index = dec_size - 1
    dst_data = bytearray(dec_size)
    while dst_index >= 0 and src_index >= 0:
        data = src_data[src_index]
        src_index -= 1
        if data == key and src_index >= 0:
            copy_index = src_data[src_index]
            src_index -= 1
            if copy_index > 0 and src_index >= 0:
                copy_length = src_data[src_index]
                src_index -= 1
                for _ in range(copy_length + 3):
                    if dst_index + copy_index + 1 < len(dst_data):
                        dst_data[dst_index] = dst_data[dst_index + copy_index]
                    else:
                        dst_data[dst_index] = 0
                    dst_index -= 1
                    if dst_index < 0:
                        break
            else:
                dst_data[dst_index] = data
                dst_index -= 1
        else:
            dst_data[dst_index] = data
            dst_index -= 1

    return dst_data


def _get_file_offset(iso, filename: str) -> int | None:
    """Scan the ISO9660 directory records for a visible file and return its
    extent LBA (read big-endian, 0x1B bytes before the identifier)."""
    base_pos = 0x105 * BLOCK_LENGTH
    filename_bytes = filename.encode("utf-8")

    # The upstream scanner walks at most 0x500 marker bytes; buffer a
    # generous window of the directory region and replicate its stepping.
    iso.seek(base_pos)
    window = iso.read(0x4000)

    pos = 0
    for _ in range(0x500):
        if pos >= len(window):
            break
        marker = window[pos]
        pos += 1
        if marker != 1:
            continue
        if pos >= len(window):
            break
        string_length = window[pos]
        pos += 1
        if string_length != len(filename_bytes):
            continue
        name_pos = pos
        if window[name_pos:name_pos + string_length] == filename_bytes:
            return struct.unpack_from(">I", window, name_pos - 0x1B)[0]
        pos = name_pos + 1
    return None


def _get_file_pos(iso, filename: str) -> int:
    lba = _get_file_offset(iso, filename)
    if not lba:
        raise UnsupportedIsoError(
            f"{filename} not found in the image. Only Japanese Kingdom Hearts "
            "ISOs (original or Final Mix) are supported.")
    return lba * BLOCK_LENGTH


def read_file_table(iso, filenames: dict[int, str]):
    """Parse KINGDOM.IDX. Returns (files, num_unknown)."""
    start = _get_file_pos(iso, "KINGDOM.IDX;1")
    iso.seek(start)
    files: list[KingdomFile] = []
    num_unknown = 0
    while True:
        entry = iso.read(0x10)
        if len(entry) < 0x10:
            break
        hash_value, is_compressed, iso_block, length = struct.unpack("<IIII", entry)
        if hash_value == 0:
            break
        file = KingdomFile(hash_value, bool(is_compressed), iso_block, length)
        file.filename = filenames.get(hash_value)
        if file.filename is None:
            num_unknown += 1
        files.append(file)
    return files, num_unknown


def extract_iso(iso_path: str, out_dir: str, progress=None):
    """Extract all files. `progress(done, total, name)` is called per file.
    Returns (num_files, num_unknown)."""
    filenames = load_filenames()
    with open(iso_path, "rb") as iso:
        files, num_unknown = read_file_table(iso, filenames)
        if not files:
            raise UnsupportedIsoError("KINGDOM.IDX contains no file entries.")
        cnf_start = _get_file_pos(iso, "SYSTEM.CNF;1")

        files.sort(key=lambda f: f.iso_block)
        for i, entry in enumerate(files):
            name = entry.filename or f"unknown/{entry.hash:08X}.bin"
            if progress:
                progress(i, len(files), name)
            iso.seek(cnf_start + entry.iso_block * BLOCK_LENGTH)
            contents = iso.read(entry.length)
            if entry.is_compressed:
                contents = decompress(contents)
            out_path = os.path.join(out_dir, *name.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as out:
                out.write(contents)
        if progress:
            progress(len(files), len(files), "")
    return len(files), num_unknown
