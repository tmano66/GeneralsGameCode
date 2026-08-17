# mapgen-mcp — let Claude build C&C Generals: Zero Hour maps

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any
MCP client) author playable **Command & Conquer Generals: Zero Hour**
skirmish maps by talking to it — no WorldBuilder required. It writes `.map`
files directly and installs them where the game picks them up.

> "Make me a 2v2 map with one choke point in the middle" → a playable map
> in your skirmish list, complete with player starts, supply docks, oil
> derricks, AI attack paths, cliffs, and a preview thumbnail.

The map format was reverse-engineered from the engine source in this
repository (every chunk layout is documented with `file:line` references
in the module docstrings) and validated against all 116 retail maps.

## Requirements

- Python 3.8+ (standard library only — no packages to install)
- Zero Hour installed, run at least once (so its user-data folder exists)

## Setup

**Claude Code** — from a clone of this repo, the server is already
registered via the project's `.mcp.json`; just open Claude Code in the
repo and approve the `generals-mapgen` server. To register it globally
instead:

```
claude mcp add generals-mapgen -- python3 /path/to/GeneralsGameCode/mapgen-mcp/server.py
```

(on Windows use `python` instead of `python3`)

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "generals-mapgen": {
      "command": "python3",
      "args": ["/path/to/GeneralsGameCode/mapgen-mcp/server.py"]
    }
  }
}
```

## Using it

Just describe the map you want:

- *"Create a 1v1 map called Canyon Duel: two bases in opposite corners
  separated by a canyon with two crossings, extra supply docks in the
  middle."*
- *"Make a 4-player snow map, open center, oil derricks on the flanks."*
- *"Add a water area along the south edge and move Player 2's start away
  from it."*

Claude drives these tools:

| Tool | Purpose |
|---|---|
| `create_map` | Start a new map (size, base height, ground texture, time of day, weather) |
| `set_terrain_height` | Raise/lower a rectangle, with feathered slopes; steep = impassable cliffs |
| `paint_texture` | Paint terrain textures (232 retail-verified names via `list_textures`) |
| `add_player_start` | Place `Player_N_Start` positions (2-8 players) |
| `set_initial_camera` | Set the starting camera |
| `place_object` | Place anything by ThingTemplate name: `SupplyDock`, `TechOilDerrick`, trees, rocks, ... |
| `add_waypoint_path` | Labeled waypoint paths (`Center1`, `Flank1`, ...) that skirmish AI uses as attack routes |
| `add_water_area` | Water polygons |
| `list_textures` / `get_map_info` | Inspect available textures / current map state |
| `save_map` | Write the `.map` + preview `.tga` and install into the game |

`save_map` auto-detects your game user-data folder — native Windows
(`Documents\Command and Conquer Generals Zero Hour Data`), Steam/Proton
prefixes in any Steam library, and plain Wine. If yours isn't found, set
`GENERALS_MAPS_DIR` to your `...Zero Hour Data/Maps` folder.

**Then restart the game** (it scans for maps at startup) and pick the map
under Skirmish → Select Map → **Unofficial Maps**.

## Scripting without an AI

The underlying library is usable directly — see
`examples/gen_2v2_choke.py`, which generates the bundled "Choke Point
Clash" 2v2 map:

```python
from generalsmap import GeneralsMap

m = GeneralsMap(playable_width=300, playable_height=300,
                default_texture='SandMediumType1', map_name='My Map')
m.raise_rect(0, 1400, 3000, 1600, 100, feather=30)   # cliff wall
m.add_waypoint('Player_1_Start', 600, 600)
m.add_waypoint('Player_2_Start', 2400, 2400)
m.add_object('SupplyDock', 900, 600)
m.save('My Map.map')
```

## Map-format crash course

- 1 terrain cell = 10 world units; heights are bytes, 0.625 world units
  each. A 300×300-cell map is 3000×3000 world units.
- A cell whose corner heights span more than 9.8 world units (16 height
  bytes) is an **impassable cliff** (`PATHFIND_CLIFF_SLOPE_LIMIT_F`).
  Use `feather ≤ 40` for walls, `≥ 80` for walkable hills.
- A map is multiplayer iff it has contiguous `Player_1_Start..N` waypoints
  (N ≥ 2). Maps must live at `Maps/<Name>/<Name>.map`.
- Generated maps carry the standard skirmish player list and per-side
  script stubs, so skirmish AI and MP victory conditions work; labeled
  waypoint paths give the AI its attack routes.
- Texture names must match `generalsmap/texture_catalog.json` — each
  entry's tile count must agree with the game's shipped texture size, or
  it renders black (the catalog was harvested from the retail maps).

## What's not supported (yet)

- Smooth texture blending between materials (edges are hard; WorldBuilder
  computes blend tiles the library doesn't yet emit)
- Roads, bridges, and scripted missions (single-player `.map` scripts)
- Editing existing maps in place (the reader can parse them; the builder
  currently only writes maps it created)

Everything a generated map contains loads fine in WorldBuilder, so you can
always hand-finish a generated map there.

## Layout

- `generalsmap/chunkio.py` — CkMp chunk container + RefPack decompression
- `generalsmap/mapbuilder.py` — heightmap, tiles, objects, waypoints, preview
- `generalsmap/sides.py` — players/teams (standard skirmish side list)
- `generalsmap/worldchunks.py` — lighting (retail values) + water polygons
- `generalsmap/texture_catalog.json` — 232 valid terrain textures
- `server.py` — the MCP server (stdio, dependency-free)
- `examples/` — sample generator + the finished sample map

Licensed under the same terms as this repository (GPLv3).
