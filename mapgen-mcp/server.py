#!/usr/bin/env python3
"""MCP server for authoring C&C Generals: Zero Hour maps.

Stdio JSON-RPC server (no third-party dependencies). Exposes tools to
create terrain, paint textures, place objects/waypoints, and save playable
.map files, using the generalsmap library (formats reverse-engineered from
the GeneralsGameCode engine source and validated against retail maps).

Register with Claude Code:
    claude mcp add generals-mapgen -- python3 /path/to/mapgen-mcp/server.py
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generalsmap import GeneralsMap, TEXTURE_CATALOG, MAP_XY_FACTOR

PROTOCOL_VERSION = '2024-11-05'

USER_DATA_LEAF = 'Command and Conquer Generals Zero Hour Data'


def _steam_library_roots():
    """Steam library steamapps dirs, from the default location plus any
    extra libraries listed in libraryfolders.vdf."""
    import re
    home = os.path.expanduser('~')
    roots = []
    for base in (home + '/.steam/steam/steamapps',
                 home + '/.local/share/Steam/steamapps'):
        if os.path.isdir(base):
            roots.append(base)
    for base in list(roots):
        vdf = os.path.join(base, 'libraryfolders.vdf')
        if os.path.isfile(vdf):
            with open(vdf, errors='replace') as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    p = os.path.join(m.group(1), 'steamapps')
                    if os.path.isdir(p):
                        roots.append(p)
    return sorted(set(roots))


def detect_install_dirs():
    """Locate every game user-data Maps dir on this machine, in priority
    order. Override/extend with GENERALS_MAPS_DIR (multiple paths separated
    by the OS path separator). Only dirs whose parent user-data folder
    already exists (i.e. the game has run there) are returned."""
    import glob
    candidates = []
    env = os.environ.get('GENERALS_MAPS_DIR', '')
    candidates += [d for d in env.split(os.pathsep) if d]
    home = os.path.expanduser('~')
    # Native Windows / plain Wine
    candidates.append(os.path.join(home, 'Documents', USER_DATA_LEAF, 'Maps'))
    candidates.append(os.path.join(home, USER_DATA_LEAF, 'Maps'))
    # Steam Proton prefixes in every Steam library
    for root in _steam_library_roots():
        pat = os.path.join(root, 'compatdata', '*', 'pfx', 'drive_c',
                           'users', 'steamuser', 'Documents', USER_DATA_LEAF)
        for d in glob.glob(pat):
            candidates.append(os.path.join(d, 'Maps'))
    out, seen = [], set()
    for d in candidates:
        d = os.path.abspath(d)
        real = os.path.realpath(d)
        if real in seen or not os.path.isdir(os.path.dirname(d)):
            continue
        seen.add(real)
        out.append(d)
    return out


INSTALL_DIRS = detect_install_dirs()

STATE = {'map': None, 'name': None}


def _require_map():
    if STATE['map'] is None:
        raise ValueError('no map open - call create_map first')
    return STATE['map']


# ---------------------------------------------------------------------------
# tool implementations

def create_map(name, playable_width=300, playable_height=300, border=30,
               base_height=20, default_texture='SandMediumType1',
               time_of_day=2, weather=0):
    if default_texture not in TEXTURE_CATALOG:
        raise ValueError('unknown texture %r; use list_textures' % default_texture)
    STATE['map'] = GeneralsMap(
        playable_width=int(playable_width), playable_height=int(playable_height),
        border=int(border), base_height=int(base_height),
        default_texture=default_texture, map_name=name,
        time_of_day=int(time_of_day), weather=int(weather))
    STATE['name'] = name
    w, h = STATE['map'].playable_world
    return ('created map %r: playable %dx%d world units (%dx%d cells), '
            'base height %d. World origin (0,0) is the SW corner of the '
            'playable area.' % (name, w, h, playable_width, playable_height,
                                base_height))


def set_terrain_height(x0, y0, x1, y1, height, feather=0.0):
    m = _require_map()
    m.raise_rect(float(x0), float(y0), float(x1), float(y1), int(height),
                 feather=float(feather))
    return ('set rect (%g,%g)-(%g,%g) to height %d (feather %g wu). '
            'Cells whose corner heights span >16 height units become '
            'impassable cliffs.' % (x0, y0, x1, y1, height, feather))


def paint_texture(x0, y0, x1, y1, texture):
    m = _require_map()
    if texture not in TEXTURE_CATALOG:
        raise ValueError('unknown texture %r; use list_textures' % texture)
    m.paint_rect(float(x0), float(y0), float(x1), float(y1), texture)
    return 'painted rect with %s' % texture


def add_player_start(player_number, x, y):
    m = _require_map()
    n = int(player_number)
    if not 1 <= n <= 8:
        raise ValueError('player_number must be 1..8')
    name = 'Player_%d_Start' % n
    if any(wp.name == name for wp in m.waypoints):
        raise ValueError('%s already placed' % name)
    m.add_waypoint(name, float(x), float(y))
    return ('placed %s at (%g,%g). Starts must be contiguous from '
            'Player_1_Start; the count defines the map player count.'
            % (name, x, y))


def set_initial_camera(x, y):
    m = _require_map()
    m.waypoints = [wp for wp in m.waypoints
                   if wp.name != 'InitialCameraPosition']
    m.add_waypoint('InitialCameraPosition', float(x), float(y))
    return 'camera start set to (%g,%g)' % (x, y)


def place_object(name, x, y, angle=0.0, owner='teamPlyrCivilian'):
    m = _require_map()
    m.add_object(name, float(x), float(y), angle=float(angle), owner=owner)
    return 'placed %s at (%g,%g)' % (name, x, y)


def add_waypoint_path(label, points):
    m = _require_map()
    prev = None
    for idx, pt in enumerate(points):
        wp = m.add_waypoint('%s_%d' % (label, idx + 1),
                            float(pt['x']), float(pt['y']), path_label=label)
        if prev is not None:
            m.link_waypoints(prev, wp)
        prev = wp
    return 'added path %r with %d waypoints' % (label, len(points))


def add_water_area(name, points, water_height):
    m = _require_map()
    m.triggers.append({
        'name': name, 'id': len(m.triggers) + 1, 'is_water': True,
        'points': [(int(p['x']), int(p['y']), int(water_height))
                   for p in points],
    })
    return 'added water area %r (%d points, z=%s)' % (name, len(points),
                                                      water_height)


def list_textures(contains=''):
    names = [n for n in sorted(TEXTURE_CATALOG)
             if contains.lower() in n.lower()]
    return json.dumps(names)


def get_map_info():
    m = _require_map()
    w, h = m.playable_world
    return json.dumps({
        'name': STATE['name'],
        'playable_world_units': [w, h],
        'border_cells': m.border,
        'objects': [{'name': o.name, 'x': o.x, 'y': o.y, 'owner': o.owner}
                    for o in m.objects],
        'waypoints': [{'name': p.name, 'x': p.x, 'y': p.y,
                       'path': p.path_label} for p in m.waypoints],
        'water_areas': [t['name'] for t in m.triggers],
    }, indent=1)


def save_map(install=True, path=None):
    m = _require_map()
    name = STATE['name']
    data = m.to_bytes()
    starts = sorted(p.name for p in m.waypoints if p.name.endswith('_Start'))
    written = []
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        written.append(path)
    if install:
        if not INSTALL_DIRS and not path:
            raise ValueError(
                'no game user-data directory found on this machine; set the '
                'GENERALS_MAPS_DIR environment variable to your "...\\Command '
                'and Conquer Generals Zero Hour Data\\Maps" folder, or pass '
                'an explicit path')
        for d in INSTALL_DIRS:
            target = os.path.join(d, name)
            os.makedirs(target, exist_ok=True)
            out = os.path.join(target, name + '.map')
            with open(out, 'wb') as f:
                f.write(data)
            m.save_preview_tga(os.path.join(target, name + '.tga'))
            written.append(out)
    return ('saved %d bytes; player starts: %s; wrote: %s. Restart the game '
            'to rescan maps, then look under Unofficial/User maps.'
            % (len(data), starts or 'NONE (not a multiplayer map!)',
               '; '.join(written) or 'nowhere - pass path or install=true'))


TOOLS = [
    {'name': 'create_map',
     'description': 'Start a new Zero Hour skirmish map. Coordinates for all '
        'later calls are world units; 1 terrain cell = 10 world units. '
        'A 300x300-cell map is 3000x3000 world units. Heights are bytes, '
        '0.625 world units each. The standard skirmish player list is '
        'added automatically.',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'description': 'map name = folder and file name'},
         'playable_width': {'type': 'integer', 'default': 300, 'description': 'playable cells in x (multiplayer standard: 250-450)'},
         'playable_height': {'type': 'integer', 'default': 300},
         'border': {'type': 'integer', 'default': 30, 'description': 'non-playable border cells around the map'},
         'base_height': {'type': 'integer', 'default': 20, 'description': 'ground level in height bytes (0-255)'},
         'default_texture': {'type': 'string', 'default': 'SandMediumType1'},
         'time_of_day': {'type': 'integer', 'default': 2, 'description': '1 morning, 2 afternoon, 3 evening, 4 night'},
         'weather': {'type': 'integer', 'default': 0, 'description': '0 normal, 1 snowy'},
     }, 'required': ['name']}},
    {'name': 'set_terrain_height',
     'description': 'Set terrain height inside a world-unit rectangle, with '
        'optional feathered slope outside it. Height deltas >16 bytes within '
        'one 10-wu cell create impassable cliff cells (use feather <= 40 for '
        'walls, >= 80 for walkable hills).',
     'inputSchema': {'type': 'object', 'properties': {
         'x0': {'type': 'number'}, 'y0': {'type': 'number'},
         'x1': {'type': 'number'}, 'y1': {'type': 'number'},
         'height': {'type': 'integer', 'description': 'target height byte 0-255'},
         'feather': {'type': 'number', 'default': 0},
     }, 'required': ['x0', 'y0', 'x1', 'y1', 'height']}},
    {'name': 'paint_texture',
     'description': 'Paint a terrain texture over a world-unit rectangle. '
        'Texture names must come from list_textures.',
     'inputSchema': {'type': 'object', 'properties': {
         'x0': {'type': 'number'}, 'y0': {'type': 'number'},
         'x1': {'type': 'number'}, 'y1': {'type': 'number'},
         'texture': {'type': 'string'},
     }, 'required': ['x0', 'y0', 'x1', 'y1', 'texture']}},
    {'name': 'add_player_start',
     'description': 'Place a player start position (Player_N_Start waypoint). '
        'Place 1..N contiguously; N>=2 makes the map multiplayer/skirmish.',
     'inputSchema': {'type': 'object', 'properties': {
         'player_number': {'type': 'integer'},
         'x': {'type': 'number'}, 'y': {'type': 'number'},
     }, 'required': ['player_number', 'x', 'y']}},
    {'name': 'set_initial_camera',
     'description': 'Set the initial camera waypoint.',
     'inputSchema': {'type': 'object', 'properties': {
         'x': {'type': 'number'}, 'y': {'type': 'number'},
     }, 'required': ['x', 'y']}},
    {'name': 'place_object',
     'description': 'Place a map object by ThingTemplate name. Useful: '
        'SupplyDock (30k resources), TechOilDerrick, TechReinforcementPad, '
        'GuardTower, trees (TreeFir01, TreeDogwood1), Rocks1-6. Neutral '
        'owner teamPlyrCivilian; tech buildings traditionally use "team".',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string'},
         'x': {'type': 'number'}, 'y': {'type': 'number'},
         'angle': {'type': 'number', 'default': 0, 'description': 'radians'},
         'owner': {'type': 'string', 'default': 'teamPlyrCivilian'},
     }, 'required': ['name', 'x', 'y']}},
    {'name': 'add_waypoint_path',
     'description': 'Add a linked waypoint path with a label. Skirmish AI '
        'uses labeled paths (Center1, Flank1, Backdoor1, Center2, ...) as '
        'attack routes between bases - add at least one per map.',
     'inputSchema': {'type': 'object', 'properties': {
         'label': {'type': 'string'},
         'points': {'type': 'array', 'items': {'type': 'object', 'properties': {
             'x': {'type': 'number'}, 'y': {'type': 'number'}},
             'required': ['x', 'y']}},
     }, 'required': ['label', 'points']}},
    {'name': 'add_water_area',
     'description': 'Add a water polygon (points in world units, '
        'water_height in world units - terrain below it is underwater).',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string'},
         'points': {'type': 'array', 'items': {'type': 'object', 'properties': {
             'x': {'type': 'number'}, 'y': {'type': 'number'}},
             'required': ['x', 'y']}},
         'water_height': {'type': 'number'},
     }, 'required': ['name', 'points', 'water_height']}},
    {'name': 'list_textures',
     'description': 'List valid terrain texture names (232 retail-verified), '
        'optionally filtered by substring (e.g. "cliff", "grass", "snow").',
     'inputSchema': {'type': 'object', 'properties': {
         'contains': {'type': 'string', 'default': ''}}}},
    {'name': 'get_map_info',
     'description': 'Summarize the current map: size, objects, waypoints.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'save_map',
     'description': 'Serialize the map and (by default) install it into the '
        'game user Maps directories so it appears in the skirmish list.',
     'inputSchema': {'type': 'object', 'properties': {
         'install': {'type': 'boolean', 'default': True},
         'path': {'type': 'string', 'description': 'optional extra output path'},
     }}},
]

HANDLERS = {
    'create_map': create_map,
    'set_terrain_height': set_terrain_height,
    'paint_texture': paint_texture,
    'add_player_start': add_player_start,
    'set_initial_camera': set_initial_camera,
    'place_object': place_object,
    'add_waypoint_path': add_waypoint_path,
    'add_water_area': add_water_area,
    'list_textures': list_textures,
    'get_map_info': get_map_info,
    'save_map': save_map,
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing

def _reply(msg_id, result):
    _send({'jsonrpc': '2.0', 'id': msg_id, 'result': result})


def _error(msg_id, code, message):
    _send({'jsonrpc': '2.0', 'id': msg_id,
           'error': {'code': code, 'message': message}})


def _send(obj):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get('method')
        msg_id = msg.get('id')
        if method == 'initialize':
            _reply(msg_id, {
                'protocolVersion': PROTOCOL_VERSION,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'generals-mapgen', 'version': '0.1.0'},
            })
        elif method == 'notifications/initialized':
            pass
        elif method == 'tools/list':
            _reply(msg_id, {'tools': TOOLS})
        elif method == 'tools/call':
            params = msg.get('params', {})
            tool = params.get('name')
            args = params.get('arguments') or {}
            fn = HANDLERS.get(tool)
            if fn is None:
                _error(msg_id, -32602, 'unknown tool %r' % tool)
                continue
            try:
                text = fn(**args)
                _reply(msg_id, {'content': [{'type': 'text', 'text': text}]})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                _reply(msg_id, {'content': [{'type': 'text',
                                             'text': 'ERROR: %s' % e}],
                                'isError': True})
        elif msg_id is not None:
            _error(msg_id, -32601, 'method %r not supported' % method)


if __name__ == '__main__':
    main()
