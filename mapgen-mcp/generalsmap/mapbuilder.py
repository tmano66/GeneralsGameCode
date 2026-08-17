"""High-level builder for C&C Generals Zero Hour .map files.

Coordinate system (from the engine):
  - The heightmap is a grid of (width x height) samples, one per cell corner.
  - MAP_XY_FACTOR: one cell = 10.0 world units.
  - MAP_HEIGHT_SCALE: one height byte = 0.625 world units of elevation.
  - The playable area is the boundary box; `border` extra cells surround it
    on every side. World (0,0) is the corner of the PLAYABLE area, so a cell
    at grid (i,j) sits at world ((i-border)*10, (j-border)*10).

Chunk layouts verified against the engine parsers in
Core/GameEngineDevice/Source/W3DDevice/GameClient/WorldHeightMap.cpp and by
round-trip decoding retail maps from MapsZH.big.
"""

import math
import struct

from .chunkio import ChunkWriter

MAP_XY_FACTOR = 10.0
MAP_HEIGHT_SCALE = 10.0 / 16.0  # 0.625

# BlendTileData constants (WorldHeightMap.cpp / WHeightMapEdit.cpp)
K_HEIGHT_MAP_VERSION = 4
K_BLEND_TILE_VERSION = 8
K_OBJECTS_VERSION = 3
K_WORLDDICT_VERSION = 1
K_LIGHTING_VERSION = 3
K_WAYPOINTS_VERSION = 1
K_SIDES_VERSION = 3
K_TRIGGERS_VERSION = 4

# Per-texture tile counts (numTiles = (imageWidth/64)^2, width = sqrt) —
# harvested from every retail map in MapsZH.big; must match the shipped TGA
# or readTexClass() fails and the texture renders black.
_CATALOG_PATH = __file__.rsplit('/', 1)[0] + '/texture_catalog.json'


def _load_catalog():
    import json
    with open(_CATALOG_PATH) as f:
        return json.load(f)


TEXTURE_CATALOG = _load_catalog()


class Waypoint:
    def __init__(self, wp_id, name, x, y, path_label=''):
        self.id = wp_id
        self.name = name
        self.x = x
        self.y = y
        self.path_label = path_label


class MapObject:
    def __init__(self, name, x, y, z=0.0, angle=0.0, owner='teamPlyrCivilian',
                 unique_id=None, extra_props=None):
        self.name = name
        self.x = x
        self.y = y
        self.z = z
        self.angle = angle
        self.owner = owner
        self.unique_id = unique_id
        self.extra_props = extra_props or {}


class GeneralsMap:
    """A Zero Hour map being built. All x/y positions are world units
    within the playable area (0..playable_cells*10)."""

    def __init__(self, playable_width=300, playable_height=300, border=30,
                 base_height=25, default_texture='SandMediumType1',
                 map_name='Untitled', time_of_day=2, weather=0):
        self.border = border
        self.width = playable_width + 2 * border    # heightmap samples x
        self.height = playable_height + 2 * border  # heightmap samples y
        self.playable_width = playable_width
        self.playable_height = playable_height
        self.map_name = map_name
        self.time_of_day = time_of_day
        self.weather = weather
        self.default_texture = default_texture
        # heights indexed [j][i] j=row (y), i=col (x); grid coords incl. border
        self.heights = [bytearray([base_height] * self.width)
                        for _ in range(self.height)]
        # per-cell texture name (cells = samples - 1, but engine stores
        # width*height tile indices; we keep one per sample for simplicity)
        self.textures = [[default_texture] * self.width
                         for _ in range(self.height)]
        self.objects = []      # MapObject
        self.waypoints = []    # Waypoint
        self.waypoint_links = []  # (id, id)
        self.players = []      # dicts, filled by add_skirmish_players
        self.teams = []
        self.triggers = []
        self._next_wp_id = 1
        self._uid_counter = 1

    # ------------------------------------------------------------------
    # coordinate helpers
    def world_to_grid(self, x, y):
        return (int(round(x / MAP_XY_FACTOR)) + self.border,
                int(round(y / MAP_XY_FACTOR)) + self.border)

    @property
    def playable_world(self):
        return (self.playable_width * MAP_XY_FACTOR,
                self.playable_height * MAP_XY_FACTOR)

    # ------------------------------------------------------------------
    # terrain editing (grid coords are playable-relative world units)
    def set_height_world(self, x, y, h):
        i, j = self.world_to_grid(x, y)
        if 0 <= i < self.width and 0 <= j < self.height:
            self.heights[j][i] = max(0, min(255, int(h)))

    def raise_rect(self, x0, y0, x1, y1, h, feather=0.0):
        """Set height h inside the world-unit rect, with optional linear
        feathering (world units) outside the rect edge."""
        gi0, gj0 = self.world_to_grid(x0 - feather, y0 - feather)
        gi1, gj1 = self.world_to_grid(x1 + feather, y1 + feather)
        for j in range(max(0, gj0), min(self.height, gj1 + 1)):
            for i in range(max(0, gi0), min(self.width, gi1 + 1)):
                wx = (i - self.border) * MAP_XY_FACTOR
                wy = (j - self.border) * MAP_XY_FACTOR
                dx = max(x0 - wx, 0, wx - x1)
                dy = max(y0 - wy, 0, wy - y1)
                d = math.hypot(dx, dy)
                if d >= feather and feather > 0 and d > 0:
                    continue
                cur = self.heights[j][i]
                if feather > 0 and d > 0:
                    t = 1.0 - d / feather
                    val = cur + (h - cur) * t
                else:
                    val = h
                self.heights[j][i] = max(0, min(255, int(round(val))))

    def paint_rect(self, x0, y0, x1, y1, texture):
        gi0, gj0 = self.world_to_grid(x0, y0)
        gi1, gj1 = self.world_to_grid(x1, y1)
        for j in range(max(0, gj0), min(self.height, gj1 + 1)):
            for i in range(max(0, gi0), min(self.width, gi1 + 1)):
                self.textures[j][i] = texture

    # ------------------------------------------------------------------
    # content
    def add_object(self, name, x, y, angle=0.0, owner='teamPlyrCivilian',
                   **extra):
        uid = '%s %d' % (name, self._uid_counter)
        self._uid_counter += 1
        obj = MapObject(name, x, y, angle=angle, owner=owner, unique_id=uid,
                        extra_props=extra)
        self.objects.append(obj)
        return obj

    def add_waypoint(self, name, x, y, path_label=''):
        wp = Waypoint(self._next_wp_id, name, x, y, path_label)
        self._next_wp_id += 1
        self.waypoints.append(wp)
        return wp

    def link_waypoints(self, wp_a, wp_b):
        self.waypoint_links.append((wp_a.id, wp_b.id))

    # ------------------------------------------------------------------
    # serialization
    def _texture_class_table(self):
        """Assign tile ranges to each distinct texture used."""
        used = []
        for row in self.textures:
            for t in row:
                if t not in used:
                    used.append(t)
        classes = {}
        first = 0
        for name in used:
            info = TEXTURE_CATALOG.get(name)
            if info is None:
                raise ValueError('unknown terrain texture %r (see '
                                 'texture_catalog.json for valid names)' % name)
            classes[name] = {'firstTile': first,
                             'numTiles': info['numTiles'],
                             'width': info['width']}
            first += info['numTiles']
        return classes, first

    def _tile_ndx(self, cls, i, j):
        """tileNdx = (tile << 2) | quadrant. One 64px source tile covers a
        2x2 block of cells; a width-W texture repeats every 2*W cells.
        (WHeightMapEdit::getTileNdxForClass, WHeightMapEdit.cpp:960-988)"""
        w = cls['width']
        tile = cls['firstTile'] + ((i >> 1) % w) + w * ((j >> 1) % w)
        return (tile << 2) | (2 * (j & 1)) | (i & 1)

    def _write_height_and_tiles(self, w: ChunkWriter):
        W, H = self.width, self.height
        w.open_chunk('HeightMapData', K_HEIGHT_MAP_VERSION)
        w.write_int(W)
        w.write_int(H)
        w.write_int(self.border)
        w.write_int(1)  # one boundary
        w.write_int(self.playable_width)
        w.write_int(self.playable_height)
        w.write_int(W * H)
        flat = bytearray()
        for j in range(H):
            flat += self.heights[j]
        w.write_bytes(bytes(flat))
        w.close_chunk()

        classes, num_tiles = self._texture_class_table()
        w.open_chunk('BlendTileData', K_BLEND_TILE_VERSION)
        w.write_int(W * H)
        tile_ndxes = bytearray()
        for j in range(H):
            for i in range(W):
                cls = classes[self.textures[j][i]]
                tile_ndxes += struct.pack('<h', self._tile_ndx(cls, i, j))
        w.write_bytes(bytes(tile_ndxes))
        zeros = bytes(2 * W * H)
        w.write_bytes(zeros)  # blendTileNdxes
        w.write_bytes(zeros)  # extraBlendTileNdxes
        w.write_bytes(zeros)  # cliffInfoNdxes
        flip_w = (W + 7) // 8
        w.write_bytes(self._cliff_state_bytes(flip_w))
        w.write_int(num_tiles)   # numBitmapTiles
        w.write_int(1)           # numBlendedTiles (index 0 reserved)
        w.write_int(1)           # numCliffInfo (index 0 reserved)
        w.write_int(len(classes))
        for name, cls in classes.items():
            w.write_int(cls['firstTile'])
            w.write_int(cls['numTiles'])
            w.write_int(cls['width'])
            w.write_int(0)  # legacy
            w.write_ascii(name)
        w.write_int(0)  # numEdgeTiles
        w.write_int(0)  # numEdgeTextureClasses
        # no blended tiles, no cliff info entries
        w.close_chunk()

    def _cliff_state_bytes(self, flip_w):
        """Replicates WorldHeightMap::setCellCliffFlagFromHeights (used by
        the engine itself for pre-v7 maps): a cell is a cliff --- impassable
        to ground units, getCliffState() --- when its 4 corner heights span
        more than PATHFIND_CLIFF_SLOPE_LIMIT_F = 9.8 world units."""
        out = bytearray(flip_w * self.height)
        thresh = 16  # height bytes; smallest delta with 16*0.625 = 10 > 9.8
        for j in range(self.height - 1):
            for i in range(self.width - 1):
                h00 = self.heights[j][i]
                h10 = self.heights[j][i + 1]
                h01 = self.heights[j + 1][i]
                h11 = self.heights[j + 1][i + 1]
                if max(h00, h10, h01, h11) - min(h00, h10, h01, h11) >= thresh:
                    out[j * flip_w + i // 8] |= (1 << (i % 8))
        return bytes(out)

    def _object_dict(self, obj: MapObject):
        d = {
            'objectInitialHealth': 100,
            'objectEnabled': True,
            'objectIndestructible': False,
            'objectUnsellable': False,
            'objectPowered': True,
            'objectRecruitableAI': True,
            'objectTargetable': False,
            'originalOwner': obj.owner,
            'uniqueID': obj.unique_id or obj.name,
            'objectLayer': '',
        }
        d.update(obj.extra_props)
        return d

    def _write_objects(self, w: ChunkWriter):
        w.open_chunk('ObjectsList', K_OBJECTS_VERSION)
        for obj in self.objects:
            w.open_chunk('Object', K_OBJECTS_VERSION)
            w.write_real(obj.x)
            w.write_real(obj.y)
            w.write_real(obj.z)
            w.write_real(obj.angle)
            w.write_int(0)  # flags
            w.write_ascii(obj.name)
            w.write_dict(self._object_dict(obj))
            w.close_chunk()
        for wp in self.waypoints:
            w.open_chunk('Object', K_OBJECTS_VERSION)
            w.write_real(wp.x)
            w.write_real(wp.y)
            w.write_real(0.0)
            w.write_real(0.0)
            w.write_int(0)
            w.write_ascii('*Waypoints/Waypoint')
            w.write_dict({
                'objectInitialHealth': 100,
                'objectEnabled': True,
                'objectIndestructible': False,
                'objectUnsellable': False,
                'objectPowered': True,
                'objectRecruitableAI': True,
                'objectTargetable': False,
                'originalOwner': 'team',
                'uniqueID': wp.name,
                'objectLayer': '',
                'waypointID': wp.id,
                'objectSelectable': False,
                'waypointName': wp.name,
                'waypointPathLabel1': wp.path_label,
                'waypointPathLabel2': '',
                'waypointPathLabel3': '',
            })
            w.close_chunk()
        w.close_chunk()

    def _write_waypoint_links(self, w: ChunkWriter):
        w.open_chunk('WaypointsList', K_WAYPOINTS_VERSION)
        w.write_int(len(self.waypoint_links))
        for a, b in self.waypoint_links:
            w.write_int(a)
            w.write_int(b)
        w.close_chunk()

    def to_bytes(self) -> bytes:
        w = ChunkWriter()
        self._write_height_and_tiles(w)
        # No mapName key: MapCache then falls back to "<filename> (N)"
        # which is what we want for custom maps without a map.str.
        w.open_chunk('WorldInfo', K_WORLDDICT_VERSION)
        w.write_dict({'weather': self.weather, 'compression': 0})
        w.close_chunk()
        self._write_sides(w)       # defined in sides.py mixin section below
        self._write_objects(w)
        self._write_triggers(w)
        self._write_lighting(w)
        self._write_waypoint_links(w)
        return w.tobytes()

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    # ------------------------------------------------------------------
    # preview (Maps/<Name>/<Name>.tga, shown in the skirmish map list)
    _TEX_TINTS = (
        (('cliff', 'rock'), (110, 100, 95)),
        (('grass',), (105, 140, 90)),
        (('snow', 'ice'), (225, 225, 235)),
        (('water',), (70, 110, 150)),
        (('dirt', 'road', 'asphalt'), (140, 120, 95)),
        (('sand', 'desert', 'beach'), (190, 170, 125)),
    )

    def _tint(self, texture):
        t = texture.lower()
        for keys, rgb in self._TEX_TINTS:
            if any(k in t for k in keys):
                return rgb
        return (160, 150, 120)

    def save_preview_tga(self, path, size=128):
        """Top-down preview: texture tint shaded by height, white start
        markers. Plain uncompressed 24-bit TGA, bottom-up like the map."""
        px = bytearray()
        b = self.border
        for row in range(size):
            j = b + (row * self.playable_height) // size
            for col in range(size):
                i = b + (col * self.playable_width) // size
                h = self.heights[j][i]
                r, g, bl = self._tint(self.textures[j][i])
                shade = 0.6 + 0.4 * (h / 255.0) * 3.0
                shade = min(shade, 1.25)
                px += bytes((min(255, int(bl * shade)),
                             min(255, int(g * shade)),
                             min(255, int(r * shade))))
        for wp in self.waypoints:
            if not wp.name.endswith('_Start'):
                continue
            cx = int(wp.x / (self.playable_width * MAP_XY_FACTOR) * size)
            cy = int(wp.y / (self.playable_height * MAP_XY_FACTOR) * size)
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size and dx*dx + dy*dy <= 5:
                        o = (y * size + x) * 3
                        px[o:o+3] = b'\xff\xff\xff'
        header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0,
                             size, size, 24, 0)
        with open(path, 'wb') as f:
            f.write(header + px)

    # placeholder hooks; implemented in sides.py and merged at import time
    def _write_sides(self, w):
        raise NotImplementedError

    def _write_triggers(self, w):
        raise NotImplementedError

    def _write_lighting(self, w):
        raise NotImplementedError
