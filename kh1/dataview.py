"""Little-endian byte-buffer reader mirroring the JS DataView API.
"""

import struct


class DataView:
    def __init__(self, buf: bytearray, offset: int = 0, length: int | None = None):
        self.buf = buf
        self.offset = offset
        self.byte_length = (len(buf) - offset) if length is None else length

    def subview(self, offset: int, length: int | None = None) -> "DataView":
        if length is None:
            length = self.byte_length - offset
        return DataView(self.buf, self.offset + offset, length)

    def get_u8(self, offs: int) -> int:
        return self.buf[self.offset + offs]

    def get_u16(self, offs: int) -> int:
        return struct.unpack_from("<H", self.buf, self.offset + offs)[0]

    def get_i16(self, offs: int) -> int:
        return struct.unpack_from("<h", self.buf, self.offset + offs)[0]

    def get_u32(self, offs: int) -> int:
        return struct.unpack_from("<I", self.buf, self.offset + offs)[0]

    def get_f32(self, offs: int) -> float:
        return struct.unpack_from("<f", self.buf, self.offset + offs)[0]

    def set_u8(self, offs: int, value: int) -> None:
        self.buf[self.offset + offs] = value
