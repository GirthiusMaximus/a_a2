"""Minimal protobuf wire-format reader/writer.

Implements just enough of the protobuf encoding to serialize Rust's
WorldData message graph (as written by protobuf-net), without requiring
generated code or the protobuf runtime.

Wire types used: 0 (varint), 1 (64-bit), 2 (length-delimited), 5 (32-bit).
"""
from __future__ import annotations

import struct

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LEN = 2
WIRE_32BIT = 5

_float_pack = struct.Struct("<f")


class ProtoWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    # -- primitives -------------------------------------------------
    def _varint(self, value: int) -> None:
        if value < 0:
            value &= (1 << 64) - 1  # two's complement, protobuf style
        while True:
            b = value & 0x7F
            value >>= 7
            if value:
                self.buf.append(b | 0x80)
            else:
                self.buf.append(b)
                return

    def _tag(self, field: int, wire: int) -> None:
        self._varint((field << 3) | wire)

    # -- fields -----------------------------------------------------
    def uint32(self, field: int, value: int) -> None:
        self._tag(field, WIRE_VARINT)
        self._varint(int(value))

    def int32(self, field: int, value: int) -> None:
        self._tag(field, WIRE_VARINT)
        self._varint(int(value))

    def bool_(self, field: int, value: bool) -> None:
        self._tag(field, WIRE_VARINT)
        self._varint(1 if value else 0)

    def float_(self, field: int, value: float) -> None:
        self._tag(field, WIRE_32BIT)
        self.buf += _float_pack.pack(float(value))

    def bytes_(self, field: int, value: bytes) -> None:
        self._tag(field, WIRE_LEN)
        self._varint(len(value))
        self.buf += value

    def string(self, field: int, value: str) -> None:
        self.bytes_(field, value.encode("utf-8"))

    def message(self, field: int, inner: "ProtoWriter") -> None:
        self.bytes_(field, bytes(inner.buf))

    def getvalue(self) -> bytes:
        return bytes(self.buf)


class ProtoReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def _varint(self) -> int:
        result = 0
        shift = 0
        data = self.data
        while True:
            if self.pos >= len(data):
                raise EOFError("truncated varint")
            b = data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
            if shift > 70:
                raise ValueError("varint too long")

    def tag(self) -> tuple[int, int]:
        v = self._varint()
        return v >> 3, v & 0x07

    def varint(self) -> int:
        return self._varint()

    def float_(self) -> float:
        v = _float_pack.unpack_from(self.data, self.pos)[0]
        self.pos += 4
        return v

    def bytes_(self) -> bytes:
        n = self._varint()
        out = self.data[self.pos : self.pos + n]
        if len(out) != n:
            raise EOFError("truncated length-delimited field")
        self.pos += n
        return out

    def string(self) -> str:
        return self.bytes_().decode("utf-8")

    def skip(self, wire: int) -> None:
        if wire == WIRE_VARINT:
            self._varint()
        elif wire == WIRE_64BIT:
            self.pos += 8
        elif wire == WIRE_LEN:
            self.pos += self._varint()
        elif wire == WIRE_32BIT:
            self.pos += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
