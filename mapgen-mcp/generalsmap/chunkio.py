"""Low-level I/O for C&C Generals / Zero Hour .map files.

The .map container is a "CkMp" chunk file (see
GeneralsMD/Code/GameEngine/Source/Common/System/DataChunk.cpp):

    'CkMp'
    int32  symbolCount
    symbolCount * { uint8 len, len bytes name, uint32 id }
    chunks: { uint32 nameId, uint16 version, int32 dataSize, dataSize bytes }

Chunks nest: a child chunk's bytes are simply part of the parent's payload.
Dicts (DataChunkOutput::writeDict): uint16 pairCount, then per pair an
int32 (symbolId << 8 | type) followed by the typed value.

Retail maps are RefPack-compressed ('EAR\\0' + int32 uncompressed size).
The engine also reads uncompressed files, which is what we write.
"""

import struct

DICT_BOOL = 0
DICT_INT = 1
DICT_REAL = 2
DICT_ASCIISTRING = 3
DICT_UNICODESTRING = 4


def refpack_decompress(d: bytes) -> bytes:
    """Decompress an EA RefPack stream (without the 'EAR\\0'+size prefix)."""
    pos = 0
    hdr = (d[0] << 8) | d[1]
    pos = 2
    if hdr & 0x0100:  # compressed-size field present
        pos += 4 if hdr & 0x8000 else 3
    nsize = 4 if hdr & 0x8000 else 3
    pos += nsize  # uncompressed size (we trust the caller's buffer)
    out = bytearray()
    while pos < len(d):
        b0 = d[pos]
        if b0 < 0x80:
            b1 = d[pos + 1]
            pos += 2
            lit = b0 & 3
            out += d[pos:pos + lit]
            pos += lit
            ref = ((b0 & 0x60) << 3) + b1 + 1
            length = ((b0 >> 2) & 7) + 3
            for _ in range(length):
                out.append(out[-ref])
        elif b0 < 0xC0:
            b1, b2 = d[pos + 1], d[pos + 2]
            pos += 3
            lit = (b1 >> 6) & 3
            out += d[pos:pos + lit]
            pos += lit
            ref = ((b1 & 0x3F) << 8) + b2 + 1
            length = (b0 & 0x3F) + 4
            for _ in range(length):
                out.append(out[-ref])
        elif b0 < 0xE0:
            b1, b2, b3 = d[pos + 1], d[pos + 2], d[pos + 3]
            pos += 4
            lit = b0 & 3
            out += d[pos:pos + lit]
            pos += lit
            ref = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
            length = ((b0 & 0x0C) << 6) + b3 + 5
            for _ in range(length):
                out.append(out[-ref])
        elif b0 < 0xFC:
            pos += 1
            lit = ((b0 & 0x1F) + 1) * 4
            out += d[pos:pos + lit]
            pos += lit
        else:
            pos += 1
            lit = b0 & 3
            out += d[pos:pos + lit]
            pos += lit
            break
    return bytes(out)


def maybe_decompress(data: bytes) -> bytes:
    if data[:4] == b'EAR\0':
        return refpack_decompress(data[8:])
    if data[:3] in (b'ZL1', b'ZL2', b'ZL3', b'ZL4', b'ZL5', b'ZL6', b'ZL7',
                    b'ZL8', b'ZL9') and data[3] == 0:
        import zlib
        return zlib.decompress(data[8:])
    return data


class ChunkReader:
    def __init__(self, data: bytes):
        data = maybe_decompress(data)
        if data[:4] != b'CkMp':
            raise ValueError('not a CkMp chunk file')
        self.data = data
        (count,) = struct.unpack_from('<i', data, 4)
        pos = 8
        self.names = {}
        for _ in range(count):
            ln = data[pos]
            pos += 1
            name = data[pos:pos + ln].decode('latin1')
            pos += ln
            (sym_id,) = struct.unpack_from('<I', data, pos)
            pos += 4
            self.names[sym_id] = name
        self.first_chunk = pos
        self.pos = pos
        self.end = len(data)

    # -- chunk traversal ---------------------------------------------------
    def chunks(self, start=None, end=None):
        """Yield (label, version, payload_start, payload_end) at one level."""
        pos = self.first_chunk if start is None else start
        end = self.end if end is None else end
        while pos + 10 <= end:
            sym_id, ver, size = struct.unpack_from('<IHi', self.data, pos)
            payload = pos + 10
            yield self.names.get(sym_id, '?%d' % sym_id), ver, payload, payload + size
            pos = payload + size

    # -- primitive reads (explicit cursor) ----------------------------------
    def seek(self, pos):
        self.pos = pos

    def read_int(self):
        (v,) = struct.unpack_from('<i', self.data, self.pos)
        self.pos += 4
        return v

    def read_uint(self):
        (v,) = struct.unpack_from('<I', self.data, self.pos)
        self.pos += 4
        return v

    def read_short(self):
        (v,) = struct.unpack_from('<h', self.data, self.pos)
        self.pos += 2
        return v

    def read_ushort(self):
        (v,) = struct.unpack_from('<H', self.data, self.pos)
        self.pos += 2
        return v

    def read_real(self):
        (v,) = struct.unpack_from('<f', self.data, self.pos)
        self.pos += 4
        return v

    def read_byte(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_bytes(self, n):
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def read_ascii(self):
        n = self.read_ushort()
        return self.read_bytes(n).decode('latin1')

    def read_unicode(self):
        n = self.read_ushort()
        return self.read_bytes(n * 2).decode('utf-16-le')

    def read_dict(self):
        n = self.read_ushort()
        d = {}
        for _ in range(n):
            key_and_type = self.read_uint()
            t = key_and_type & 0xFF
            key = self.names.get(key_and_type >> 8, '?%d' % (key_and_type >> 8))
            if t == DICT_BOOL:
                d[key] = bool(self.read_byte())
            elif t == DICT_INT:
                d[key] = self.read_int()
            elif t == DICT_REAL:
                d[key] = self.read_real()
            elif t == DICT_ASCIISTRING:
                d[key] = self.read_ascii()
            elif t == DICT_UNICODESTRING:
                d[key] = self.read_unicode()
            else:
                raise ValueError('bad dict type %d' % t)
        return d


class ChunkWriter:
    """Mirrors DataChunkOutput: builds the symbol table on the fly."""

    def __init__(self):
        self.names = {}          # name -> id
        self.next_id = 1
        self.body = bytearray()
        self.stack = []          # positions of open size fields

    def _sym(self, name: str) -> int:
        if name not in self.names:
            self.names[name] = self.next_id
            self.next_id += 1
        return self.names[name]

    # -- chunk structure ----------------------------------------------------
    def open_chunk(self, name: str, version: int):
        self.body += struct.pack('<IH', self._sym(name), version)
        self.stack.append(len(self.body))
        self.body += struct.pack('<i', 0)  # size placeholder

    def close_chunk(self):
        at = self.stack.pop()
        size = len(self.body) - at - 4
        struct.pack_into('<i', self.body, at, size)

    # -- primitives -----------------------------------------------------
    def write_int(self, v):
        self.body += struct.pack('<i', int(v))

    def write_short(self, v):
        self.body += struct.pack('<h', int(v))

    def write_real(self, v):
        self.body += struct.pack('<f', float(v))

    def write_byte(self, v):
        self.body += struct.pack('<B', int(v) & 0xFF)

    def write_bytes(self, b):
        self.body += b

    def write_ascii(self, s: str):
        b = s.encode('latin1')
        self.body += struct.pack('<H', len(b)) + b

    def write_unicode(self, s: str):
        b = s.encode('utf-16-le')
        self.body += struct.pack('<H', len(s)) + b

    def write_dict(self, d: dict):
        """Write a dict. Values: bool, int, float, str -> ascii,
        ('unicode', str) -> unicode string."""
        self.body += struct.pack('<H', len(d))
        for key, val in d.items():
            if isinstance(val, bool):
                t = DICT_BOOL
            elif isinstance(val, int):
                t = DICT_INT
            elif isinstance(val, float):
                t = DICT_REAL
            elif isinstance(val, str):
                t = DICT_ASCIISTRING
            elif isinstance(val, tuple) and val[0] == 'unicode':
                t = DICT_UNICODESTRING
            else:
                raise TypeError('bad dict value for %s: %r' % (key, val))
            self.body += struct.pack('<I', (self._sym(key) << 8) | t)
            if t == DICT_BOOL:
                self.write_byte(1 if val else 0)
            elif t == DICT_INT:
                self.write_int(val)
            elif t == DICT_REAL:
                self.write_real(val)
            elif t == DICT_ASCIISTRING:
                self.write_ascii(val)
            else:
                self.write_unicode(val[1])

    # -- output ---------------------------------------------------------
    def tobytes(self) -> bytes:
        if self.stack:
            raise RuntimeError('unclosed chunk')
        out = bytearray(b'CkMp')
        out += struct.pack('<i', len(self.names))
        # DataChunkTableOfContents prepends new mappings, so it writes the
        # list in reverse allocation order; readers don't care, but match it.
        for name, sym_id in sorted(self.names.items(), key=lambda kv: -kv[1]):
            b = name.encode('latin1')
            out += struct.pack('<B', len(b)) + b + struct.pack('<I', sym_id)
        out += self.body
        return bytes(out)
