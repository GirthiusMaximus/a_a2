"""lz4net "legacy" LZ4Stream codec, as used by Rust .map files.

Rust serializes .map files with K4os.Compression.LZ4.Legacy (the lz4net
stream format). The stream is a sequence of chunks:

    varint(chunkFlags)        # 7-bit little-endian varint
    varint(originalLength)    # uncompressed byte count of this chunk
    varint(compressedLength)  # ONLY present if flags & COMPRESSED
    <payload bytes>           # raw LZ4 *block* data (or raw bytes if not compressed)

Flags: 0x01 = compressed, 0x02 = high-compression (informational),
bits 2..4 = pass count (always 0 / single pass).

Default chunk (block) size used by lz4net/K4os is 1 MiB.
"""
from __future__ import annotations

import lz4.block

CHUNK_COMPRESSED = 0x01
CHUNK_HIGH_COMPRESSION = 0x02
DEFAULT_BLOCK_SIZE = 1024 * 1024


def _write_varint(out: bytearray, value: int) -> None:
    if value < 0:
        raise ValueError("varint must be non-negative")
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            if self.pos >= len(self.data):
                raise EOFError("unexpected end of stream while reading varint")
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
            if shift > 63:
                raise ValueError("varint too long")

    def read_bytes(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError("unexpected end of stream while reading chunk")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out


def decompress(data: bytes) -> bytes:
    """Decompress a complete lz4net legacy stream."""
    reader = _Reader(data)
    parts: list[bytes] = []
    while not reader.eof():
        flags = reader.read_varint()
        original_length = reader.read_varint()
        is_compressed = bool(flags & CHUNK_COMPRESSED)
        passes = flags >> 2
        if passes:
            raise ValueError("multi-pass LZ4 chunks are not supported")
        if is_compressed:
            compressed_length = reader.read_varint()
            if compressed_length > original_length:
                raise ValueError("corrupted stream: compressed > original")
            payload = reader.read_bytes(compressed_length)
            parts.append(
                lz4.block.decompress(payload, uncompressed_size=original_length)
            )
        else:
            parts.append(reader.read_bytes(original_length))
    return b"".join(parts)


def compress(data: bytes, block_size: int = DEFAULT_BLOCK_SIZE, high_compression: bool = True) -> bytes:
    """Compress bytes into an lz4net legacy stream."""
    out = bytearray()
    mode = "high_compression" if high_compression else "default"
    for offset in range(0, len(data), block_size):
        chunk = data[offset : offset + block_size]
        compressed = lz4.block.compress(chunk, mode=mode, store_size=False)
        if len(compressed) < len(chunk):
            flags = CHUNK_COMPRESSED | (CHUNK_HIGH_COMPRESSION if high_compression else 0)
            _write_varint(out, flags)
            _write_varint(out, len(chunk))
            _write_varint(out, len(compressed))
            out += compressed
        else:
            _write_varint(out, 0)
            _write_varint(out, len(chunk))
            out += chunk
    return bytes(out)
