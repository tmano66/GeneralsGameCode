"""generalsmap — programmatic C&C Generals: Zero Hour map authoring.

Formats reverse-engineered from the GeneralsGameCode source (see module
docstrings for exact file:line references) and validated by round-trip
decoding all 116 retail maps in MapsZH.big.
"""

from .chunkio import ChunkReader, ChunkWriter
from .mapbuilder import GeneralsMap, MAP_XY_FACTOR, MAP_HEIGHT_SCALE, TEXTURE_CATALOG
from . import sides       # noqa: F401  (installs _write_sides)
from . import worldchunks  # noqa: F401  (installs _write_lighting/_write_triggers)

__all__ = ['GeneralsMap', 'ChunkReader', 'ChunkWriter',
           'MAP_XY_FACTOR', 'MAP_HEIGHT_SCALE', 'TEXTURE_CATALOG']
