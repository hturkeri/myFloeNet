"""Build the demonstration CAD model used as background geometry by the
'HPT pre-swirl system on CAD geometry' example (examples/geometry/hpt_preswirl_rig.step).

A simplified HP-turbine pre-swirl cooling arrangement, engine axis = X, units mm:

  stator : pre-swirl wall with a nozzle boss (24 nozzles, 70 deg), inner / outer seal lands,
           bearing housing, NGV platform + 24 vanes + outer casing
  rotor  : shaft, turbine disc (bore, web, rim, 36 blades), cover plate with 48 receiver holes,
           inner / outer seal arms with labyrinth teeth, 36 radial blade-feed holes

Radii follow the 'HPT pre-swirl cooling system' network (nozzles and receiver holes at r = 250 mm,
inner seal r = 200 mm, outer seal r = 280 mm, blade feed r = 300 mm, rim seal r = 340-350 mm).

Run:  python make_hpt_preswirl_rig.py   (needs:  python -m pip install gmsh)
"""
import math
import os

import gmsh

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "hpt_preswirl_rig.step")

occ = None


def profile(rects):
    """Union of (x0, x1, r0, r1) rectangles in the x-r plane -> list of surface dimTags."""
    tags = [(2, occ.addRectangle(x0, r0, 0.0, x1 - x0, r1 - r0)) for x0, x1, r0, r1 in rects]
    if len(tags) == 1:
        return tags
    out, _ = occ.fuse(tags[:1], tags[1:])
    return out


def revolve(rects):
    surf = profile(rects)
    out = occ.revolve(surf, 0, 0, 0, 1, 0, 0, 2 * math.pi)
    occ.remove(surf)                      # drop the 2D profile, keep only the solid
    return [dt for dt in out if dt[0] == 3]


def ring_copies(dimtags, n, phase=0.0):
    """n copies of dimtags around the X axis (the original is kept as copy 0)."""
    allt = list(dimtags)
    for k in range(1, n):
        c = occ.copy(dimtags)
        occ.rotate(c, 0, 0, 0, 1, 0, 0, phase + 2 * math.pi * k / n)
        allt += c
    if phase:
        occ.rotate(dimtags, 0, 0, 0, 1, 0, 0, phase)
    return allt


def teeth(x0, x1, r_root, r_tip, pitch, width):
    rects, x = [], x0
    while x + width <= x1:
        rects.append((x, x + width, r_root, r_tip))
        x += pitch
    return rects


def main():
    global occ
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("hpt_preswirl_rig")
    occ = gmsh.model.occ

    # ------------------------------------------------------------ stator
    pre_wall = revolve([(0, 16, 201, 345),                 # pre-swirl wall
                        (-14, 22, 235, 265),               # nozzle boss
                        (16, 58, 201, 207),                # inner seal land (r = 200 mm)
                        (16, 58, 281, 287),                # outer seal land (r = 280 mm)
                        (-10, 0, 150, 201),                # flange to the bearing housing
                        (-150, -10, 150, 160)])            # bearing housing
    noz = []
    a = math.radians(70.0)
    for k in range(24):
        phi = 2 * math.pi * k / 24
        er = (0.0, math.cos(phi), math.sin(phi))
        et = (0.0, -math.sin(phi), math.cos(phi))
        d = (math.cos(a), math.sin(a) * et[1], math.sin(a) * et[2])
        L = 150.0
        p = (4.0 - d[0] * L / 2, 250 * er[1] - d[1] * L / 2, 250 * er[2] - d[2] * L / 2)
        noz.append((3, occ.addCylinder(*p, d[0] * L, d[1] * L, d[2] * L, 3.5)))
    pre_wall, _ = occ.cut(pre_wall, noz)

    ngv = revolve([(-60, 50, 345, 355),                    # NGV inner platform (rim-seal overlap)
                   (-150, 200, 440, 452)])                 # outer casing
    vane = occ.addBox(-45, 353, -4, 64, 89, 8)
    occ.rotate([(3, vane)], -13, 397, 0, 0, 1, 0, math.radians(-50))
    vanes = ring_copies([(3, vane)], 24)
    ngv, _ = occ.fuse(ngv, vanes)

    # ------------------------------------------------------------ rotor
    shaft = revolve([(-150, 200, 90, 110)])
    disc = revolve([(80, 130, 110, 150),                   # bore
                    (96, 114, 149, 331),                   # web
                    (70, 140, 330, 352),                   # rim (blade platform)
                    (60, 96, 322, 331)])                   # cover-plate flange
    blade = occ.addBox(88, 350, -3.5, 34, 75, 7)
    occ.rotate([(3, blade)], 105, 387, 0, 0, 1, 0, math.radians(35))
    blades = ring_copies([(3, blade)], 36, phase=math.pi / 36)
    disc, _ = occ.fuse(disc, blades)
    feed = []
    for k in range(36):
        phi = math.pi / 36 + 2 * math.pi * k / 36
        feed.append((3, occ.addCylinder(82, 312 * math.cos(phi), 312 * math.sin(phi),
                                        0, 46 * math.cos(phi), 46 * math.sin(phi), 2.5)))
    disc, _ = occ.cut(disc, feed)

    cover = revolve([(60, 68, 186, 322),                   # cover plate (ends at the disc flange)
                     (16, 68, 186, 194),                   # inner seal arm
                     (60, 96, 186, 194)]                   # inner joint to the disc web
                    + teeth(20, 56, 193, 199.6, 8, 2)      # inner labyrinth teeth (4)
                    + [(22, 68, 268, 274)]                 # outer seal arm
                    + teeth(26, 50, 273, 279.6, 8, 2))     # outer labyrinth teeth (3)
    rec = [(3, occ.addCylinder(55, 250 * math.cos(2 * math.pi * k / 48), 250 * math.sin(2 * math.pi * k / 48),
                               20, 0, 0, 4.0)) for k in range(48)]
    cover, _ = occ.cut(cover, rec)

    occ.synchronize()
    names = [("Pre-swirl stator", pre_wall), ("NGV and casing", ngv), ("Shaft", shaft),
             ("Turbine disc", disc), ("Cover plate", cover)]
    for name, dts in names:
        for d, t in dts:
            gmsh.model.setEntityName(d, t, name)
    gmsh.write(OUT)
    print("written", OUT, os.path.getsize(OUT) // 1024, "kB")
    gmsh.finalize()


if __name__ == "__main__":
    main()
