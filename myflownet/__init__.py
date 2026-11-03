"""myFlowNet - 1D flow network solver for gas turbine secondary air systems."""

__version__ = "0.3.0"

from .model import Network, Chamber, ElementSpec, Rotor  # noqa: F401
from .solver import solve, Solution, SolverError  # noqa: F401
