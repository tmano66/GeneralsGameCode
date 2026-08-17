"""SidesList chunk writer.

Layout from SidesList::WriteSidesDataChunk (SidesList.cpp:330-389), always
version 3. In multiplayer/skirmish the engine replaces the map's player
list with slot players ("player0".."player7"), but SkirmishScripts.scb
binds its per-faction AI script lists BY NAME against the map's skirmish
sides — so a skirmish map must carry the standard WorldBuilder "skirmish
players" set (playerlistdlg.cpp:871-889) or AI opponents are inert.

Also: GameLogic appends MultiplayerScripts.scb to side 0's ScriptList only
if that ScriptList exists, so we write one (empty) ScriptList sub-chunk per
side inside the nested PlayerScriptsList chunk.
"""

from .mapbuilder import GeneralsMap, K_SIDES_VERSION

K_SCRIPTS_DATA_VERSION = 5   # "PlayerScriptsList" (Scripts.cpp enum tail)
K_SCRIPT_LIST_VERSION = 1

# (factionTemplate, playerName) — order matches WorldBuilder's
# "Add Skirmish Players" button; neutral ("") must be side 0.
SKIRMISH_SIDES = [
    ('', ''),
    ('FactionCivilian', 'PlyrCivilian'),
    ('FactionAmerica', 'SkirmishAmerica'),
    ('FactionChina', 'SkirmishChina'),
    ('FactionGLA', 'SkirmishGLA'),
    ('FactionAmericaAirForceGeneral', 'SkirmishAmericaAirForceGeneral'),
    ('FactionAmericaLaserGeneral', 'SkirmishAmericaLaserGeneral'),
    ('FactionAmericaSuperWeaponGeneral', 'SkirmishAmericaSuperWeaponGeneral'),
    ('FactionChinaTankGeneral', 'SkirmishChinaTankGeneral'),
    ('FactionChinaNukeGeneral', 'SkirmishChinaNukeGeneral'),
    ('FactionChinaInfantryGeneral', 'SkirmishChinaInfantryGeneral'),
    ('FactionGLADemolitionGeneral', 'SkirmishGLADemolitionGeneral'),
    ('FactionGLAToxinGeneral', 'SkirmishGLAToxinGeneral'),
    ('FactionGLAStealthGeneral', 'SkirmishGLAStealthGeneral'),
]


def add_skirmish_players(self):
    """Populate players/teams with the standard skirmish set."""
    self.players = []
    self.teams = []
    for faction, name in SKIRMISH_SIDES:
        display = 'Neutral' if name == '' else name
        self.players.append({
            'playerName': name,
            'playerIsHuman': False,
            'playerDisplayName': ('unicode', display),
            'playerFaction': faction,
            'playerAllies': '',
            'playerEnemies': '',
        })
        self.teams.append({
            'teamName': 'team' + name,
            'teamOwner': name,
            'teamIsSingleton': True,
        })


def _write_sides(self, w):
    if not self.players:
        add_skirmish_players(self)
    w.open_chunk('SidesList', K_SIDES_VERSION)
    w.write_int(len(self.players))
    for p in self.players:
        w.write_dict(p)
        w.write_int(0)  # build list count
    w.write_int(len(self.teams))
    for t in self.teams:
        w.write_dict(t)
    w.open_chunk('PlayerScriptsList', K_SCRIPTS_DATA_VERSION)
    for _ in self.players:
        w.open_chunk('ScriptList', K_SCRIPT_LIST_VERSION)
        w.close_chunk()
    w.close_chunk()
    w.close_chunk()


GeneralsMap.add_skirmish_players = add_skirmish_players
GeneralsMap._write_sides = _write_sides
