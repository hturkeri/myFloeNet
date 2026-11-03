"""Command line entry point.

    python -m myflownet                 -> start the GUI
    python -m myflownet model.json      -> open a model in the GUI
    python -m myflownet solve model.json [results.json]   -> batch solve, print a summary
"""
from __future__ import annotations

import json
import sys


def _batch(path, out=None):
    from .model import Network
    from .solver import solve
    from .units import fmt
    net = Network.load(path)
    sol = solve(net)
    print(f"{net.title}: {sol.message} ({sol.elapsed:.2f} s)")
    print(f"{'Chamber':28s} {'p [bar]':>10s} {'pt [bar]':>10s} {'Tt [K]':>9s} {'K':>7s}")
    for c in sol.chambers.values():
        print(f"{c['name'][:28]:28s} {c['p'] / 1e5:10.5f} {c['pt'] / 1e5:10.5f} {c['Tt']:9.2f} {c['K']:7.4f}")
    print(f"\n{'Element':28s} {'mdot [kg/s]':>12s} {'Tt out [K]':>10s}")
    for e in sol.elements.values():
        print(f"{e['name'][:28]:28s} {e['mdot']:12.6f} {e['Tt_out']:10.2f}{'  choked' if e['choked'] else ''}")
    for w in sol.warnings:
        print("warning:", w)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"message": sol.message, "converged": sol.converged,
                       "chambers": {str(k): v for k, v in sol.chambers.items()},
                       "elements": {str(k): v for k, v in sol.elements.items()}}, f, indent=2, default=float)
    return 0 if sol.converged else 1


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) >= 3 and argv[1] == "solve":
        return _batch(argv[2], argv[3] if len(argv) > 3 else None)
    from .gui import run
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
