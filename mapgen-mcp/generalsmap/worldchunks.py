"""GlobalLighting and PolygonTriggers chunk writers.

Lighting values are lifted from the retail BarrenBadlands.map (a desert
multiplayer map) so generated maps light like stock ones. The map file
overrides GameData.ini lighting, so these must be non-zero.

GlobalLighting v3 layout (WHeightMapEdit.cpp:724-775, parser
WorldHeightMap.cpp:742-816): int32 timeOfDay, then for each of the 4 times
of day (morning, afternoon, evening, night) six 9-float records:
terrain[0], objects[0], objects[1], objects[2], terrain[1], terrain[2];
each record = ambient rgb, diffuse rgb, lightPos xyz. Trailing int32
shadow color (ARGB) is optional.
"""

from .mapbuilder import GeneralsMap, K_LIGHTING_VERSION, K_TRIGGERS_VERSION

_Z = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0)  # disabled light

# per time-of-day: [terrain0, objects0, objects1, objects2, terrain1, terrain2]
RETAIL_LIGHTING = {
    1: [(0.5, 0.39, 0.3, 0.9, 0.71, 0.6, -0.96, 0.05, -0.29),
        (0.5, 0.4, 0.3, 0.9, 0.7, 0.6, -0.96, 0.05, -0.29),
        _Z, _Z, _Z, _Z],
    2: [(0.2157, 0.2, 0.1686, 1.0, 1.0, 0.8706, -0.8211, 0.4005, -0.4067),
        (0.2157, 0.2, 0.1686, 1.0, 1.0, 0.8706, -0.8211, 0.4005, -0.4067),
        (0.0, 0.0, 0.0, 0.2353, 0.2353, 0.3451, 0.8011, 0.5821, -0.1392),
        (0.0, 0.0, 0.0, 0.1725, 0.1137, 0.2588, 0.1651, -0.9366, -0.309),
        (0.0, 0.0, 0.0, 0.2353, 0.2353, 0.3451, 0.8011, 0.5821, -0.1392),
        (0.0, 0.0, 0.0, 0.1725, 0.1137, 0.2588, 0.1651, -0.9366, -0.309)],
    3: [(0.25, 0.23, 0.2, 0.6, 0.5, 0.4, -1.0, 0.0, -0.2),
        (0.25, 0.23, 0.2, 0.6, 0.5, 0.4, -1.0, 0.0, -0.2),
        _Z, _Z, _Z, _Z],
    4: [(0.1, 0.1, 0.15, 0.2, 0.2, 0.3, -1.0, 1.0, -2.0),
        (0.1, 0.1, 0.15, 0.2, 0.2, 0.3, -1.0, 1.0, -2.0),
        _Z, _Z, _Z, _Z],
}

SHADOW_COLOR_ARGB = 0xFFA7A0C9


def _write_lighting(self, w):
    w.open_chunk('GlobalLighting', K_LIGHTING_VERSION)
    w.write_int(self.time_of_day)
    for tod in (1, 2, 3, 4):
        for record in RETAIL_LIGHTING[tod]:
            for v in record:
                w.write_real(v)
    w.write_int(SHADOW_COLOR_ARGB - (1 << 32 if SHADOW_COLOR_ARGB >= (1 << 31) else 0))
    w.close_chunk()


def _write_triggers(self, w):
    w.open_chunk('PolygonTriggers', K_TRIGGERS_VERSION)
    w.write_int(len(self.triggers))
    for t in self.triggers:
        w.write_ascii(t['name'])
        w.write_ascii(t.get('layer', ''))
        w.write_int(t['id'])
        w.write_byte(1 if t.get('is_water') else 0)
        w.write_byte(1 if t.get('is_river') else 0)
        w.write_int(t.get('river_start', 0))
        pts = t['points']
        w.write_int(len(pts))
        for (x, y, z) in pts:
            w.write_int(int(x))
            w.write_int(int(y))
            w.write_int(int(z))
    w.close_chunk()


GeneralsMap._write_lighting = _write_lighting
GeneralsMap._write_triggers = _write_triggers
