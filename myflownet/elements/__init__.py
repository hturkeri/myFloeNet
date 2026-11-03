"""Element library.  Importing this package registers all element types."""
from .base import REGISTRY, ChamberState, Context, Element, ElementResult, make_element  # noqa: F401
from . import orifice, loss, pipe, labyrinth, vortex, source  # noqa: F401

# Order used by the GUI palette
PALETTE_ORDER = ["orifice", "kloss", "pipe", "labyrinth", "vortex", "cavity", "fixedflow", "discpump"]
