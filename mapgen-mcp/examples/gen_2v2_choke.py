#!/usr/bin/env python3
"""Generate "Choke Point Clash" — a 2v2 map with a single central choke.

Layout (3000x3000 world units playable):
  - Two south bases (P1, P2) and two north bases (P3, P4).
  - An impassable cliff ridge across the middle of the map with a single
    260-wu-wide gap in the center: the choke.
  - One supply dock per base, two contested docks guarding the choke
    approaches, and four neutral oil derricks on the flanks.
  - AI attack paths (Center1/Flank1/Backdoor1) threaded through the choke
    so skirmish AI behaves like on retail maps.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from generalsmap import GeneralsMap

BASE_H = 20        # height bytes (12.5 wu)
RIDGE_H = 100      # +80 bytes = +50 wu: sheer cliff walls
RIDGE_Y0, RIDGE_Y1 = 1350.0, 1650.0
GAP_X0, GAP_X1 = 1370.0, 1630.0
FEATHER = 30.0     # 3 cells of slope -> ~27 height bytes per cell: cliff

m = GeneralsMap(playable_width=300, playable_height=300, border=30,
                base_height=BASE_H, default_texture='SandMediumType1',
                map_name='Choke Point Clash', time_of_day=2)

# --- terrain ------------------------------------------------------------
# Ridge across the middle, in two pieces so the gap stays at base height.
m.raise_rect(-300, RIDGE_Y0, GAP_X0, RIDGE_Y1, RIDGE_H, feather=FEATHER)
m.raise_rect(GAP_X1, RIDGE_Y0, 3300, RIDGE_Y1, RIDGE_H, feather=FEATHER)

# Textures: cliff faces on the ridge, packed dirt through the choke.
m.paint_rect(-300, RIDGE_Y0 - FEATHER, GAP_X0, RIDGE_Y1 + FEATHER,
             'CliffLargeType3b')
m.paint_rect(GAP_X1, RIDGE_Y0 - FEATHER, 3300, RIDGE_Y1 + FEATHER,
             'CliffLargeType3b')
m.paint_rect(GAP_X0, RIDGE_Y0 - 200, GAP_X1, RIDGE_Y1 + 200,
             'DirtMediumType10')

# --- player starts (contiguous Player_1..4_Start = 4-player map) --------
starts = [(600, 600), (2400, 600), (600, 2400), (2400, 2400)]
for n, (x, y) in enumerate(starts, 1):
    m.add_waypoint('Player_%d_Start' % n, x, y)
m.add_waypoint('InitialCameraPosition', 1500, 1500)

# --- economy -------------------------------------------------------------
# One supply dock per base (toward the map edge, out of base-building room).
for (x, y) in starts:
    dy = -280 if y < 1500 else 280
    m.add_object('SupplyDock', x + 280, y + dy, angle=0.0)

# Two contested docks on the choke approaches.
m.add_object('SupplyDock', 1500, 1050)
m.add_object('SupplyDock', 1500, 1950)

# Neutral oil derricks on each flank (180-degree symmetric).
for (x, y) in [(200, 1000), (2800, 1000), (200, 2000), (2800, 2000)]:
    m.add_object('TechOilDerrick', x, y, owner='team')

# --- AI attack paths through the choke (both directions) -----------------
for label, cx in [('Center1', 1500.0), ('Flank1', 1450.0),
                  ('Backdoor1', 1550.0)]:
    prev = None
    for wy in (700.0, 1150.0, 1500.0, 1850.0, 2300.0):
        wp = m.add_waypoint('%s_%d' % (label, int(wy)), cx, wy,
                            path_label=label)
        if prev is not None:
            m.link_waypoints(prev, wp)
        prev = wp

out = sys.argv[1] if len(sys.argv) > 1 else 'Choke Point Clash.map'
m.save(out)
print('wrote %s (%d bytes)' % (out, os.path.getsize(out)))
