"""Background CAD geometry: readers, section of the cut plane, view mapping, model file."""
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np
import pytest

from myflownet import cad
from myflownet.geomview import (GeometryView, ViewSpec, clip_triangles, meridional_frame, plane_section,
                                view_rotation)
from myflownet.model import Network

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(HERE, "..", "examples", "geometry", "hpt_preswirl_rig.step")


def annulus_triangles(x0=0.0, x1=10.0, r0=20.0, r1=30.0, n=64):
    """Closed triangulated ring (revolved rectangle about the X axis), outward normals."""
    prof = [(x0, r0), (x1, r0), (x1, r1), (x0, r1)]
    tris = []
    for k in range(n):
        a, b = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        for i in range(4):
            (xa, ra), (xb, rb) = prof[i], prof[(i + 1) % 4]
            p = lambda x, r, t: (x, r * math.cos(t), r * math.sin(t))
            q0, q1, q2, q3 = p(xa, ra, a), p(xb, rb, a), p(xb, rb, b), p(xa, ra, b)
            tris += [(q0, q1, q2), (q0, q2, q3)]
    return np.array(tris, float)


def write_stl(path, tri):
    rec = np.zeros(len(tri), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["v"] = tri
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(tri)))
        f.write(rec.tobytes())


def test_stl_reader_and_meridional_section(tmp_path):
    p = tmp_path / "ring.stl"
    write_stl(p, annulus_triangles())
    g = cad.read_geometry(str(p))
    assert len(g.tris) == 64 * 8
    assert len(g.nodes) == 64 * 4                       # coincident nodes merged
    v = GeometryView(g, ViewSpec(axis="x", theta=0.0, upper_half=True))
    closed = [l for l in v.loops_plane if l[1]]
    assert len(closed) == 1                             # one closed loop: the upper half-section
    pts = closed[0][0]
    assert pts[:, 0].min() == pytest.approx(0.0, abs=1e-9) and pts[:, 0].max() == pytest.approx(10.0, abs=1e-9)
    assert pts[:, 1].min() == pytest.approx(20.0, abs=1e-6) and pts[:, 1].max() == pytest.approx(30.0, abs=1e-6)
    # half way between two node rings the polygonal ring is cut at its chords
    v2 = GeometryView(g, ViewSpec(axis="x", theta=180.0 / 64))
    pts2 = [l for l in v2.loops_plane if l[1]][0][0]
    c = math.cos(math.pi / 64)
    assert pts2[:, 1].min() == pytest.approx(20.0 * c, rel=1e-6)          # STL is float32
    assert pts2[:, 1].max() == pytest.approx(30.0 * c, rel=1e-6)
    # full section (both halves): two separate loops
    v3 = GeometryView(g, ViewSpec(axis="x", upper_half=False))
    assert len([l for l in v3.loops_plane if l[1]]) == 2


def test_clipping_conserves_area():
    rng = np.random.default_rng(1)
    tri = rng.normal(size=(400, 3, 3))
    f = tri[:, :, 2] - 0.1
    keep, _ = clip_triangles(tri, f, [])
    drop, _ = clip_triangles(tri, -f, [])

    def area(t):
        return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()
    assert area(keep) + area(drop) == pytest.approx(area(tri), rel=1e-12)
    assert (keep[:, :, 2] >= 0.1 - 1e-12).all() and (drop[:, :, 2] <= 0.1 + 1e-12).all()


def test_frames_and_view_mapping():
    for axis in ("x", "y", "z", "-x"):
        for th in (0.0, 37.0, 210.0):
            B = meridional_frame(axis, th)
            assert np.allclose(B @ B.T, np.eye(3))
            assert np.linalg.det(B) == pytest.approx(1.0)
    R = view_rotation(-35.0, 22.0)
    assert np.allclose(R @ R.T, np.eye(3))
    g = cad.CadGeometry(np.zeros((0, 3)), np.zeros((0, 3), np.int32), np.zeros(0, np.int32),
                        np.zeros(0, np.int32), np.zeros(0, np.int8), np.zeros(0), np.zeros((0, 3)),
                        np.zeros((0, 3)), np.zeros((0, 2), np.int32), np.zeros((0, 3)))
    v = GeometryView(g, ViewSpec(yaw=-35.0, pitch=22.0))
    for ax, r in ((40.0, 250.0), (-62.0, 268.0), (128.0, 398.0)):
        u, w = v.plane_to_view_pt(ax, r)
        assert v.view_to_plane(u, w) == pytest.approx((ax, r), abs=1e-9)


def test_section_keeps_touching_solids_apart():
    """Two rings touching at r = 30 (shared node positions) must give two loops, one per part."""
    t1 = annulus_triangles(0, 10, 20, 30, 32)
    t2 = annulus_triangles(0, 10, 30, 40, 32)
    nodes = np.vstack([t1.reshape(-1, 3), t2.reshape(-1, 3)])
    idx = np.arange(len(nodes)).reshape(-1, 3)
    nodes, (tris,) = cad._merge_nodes(nodes, idx)
    part = np.repeat([0, 1], len(t1))
    B = meridional_frame("x", 0.0)
    loops = plane_section(nodes @ B.T, tris, part, 1e-9)
    upper = [l for l in loops if l[1] and l[0][:, 1].min() > 0]
    assert sorted(l[2] for l in upper) == [0, 1]
    r_ranges = sorted((round(l[0][:, 1].min(), 6), round(l[0][:, 1].max(), 6)) for l in upper)
    assert r_ranges == [(20.0, 30.0), (30.0, 40.0)]


def test_model_file_keeps_background_with_relative_path(tmp_path):
    geo = tmp_path / "geo" / "rig.stl"
    geo.parent.mkdir()
    write_stl(geo, annulus_triangles())
    net = Network("bg")
    net.add_chamber("boundary", "A", 0, 0, p=2e5)
    net.background = {"file": str(geo), "theta": 12.0, "scale": 2.5, "offset": [10.0, 20.0]}
    f = tmp_path / "model.json"
    net.save(str(f))
    d = json.loads(f.read_text(encoding="utf-8"))
    assert d["background"]["file"] == "geo/rig.stl"
    n2 = Network.load(str(f))
    assert os.path.samefile(n2.background["file"], geo)
    assert n2.background["theta"] == 12.0 and n2.background["offset"] == [10.0, 20.0]
    assert Network.from_dict(Network("x").to_dict()).background is None


def test_cache_round_trip(tmp_path):
    p = tmp_path / "ring.stl"
    write_stl(p, annulus_triangles())
    g = cad.read_geometry_cached(str(p))
    g2 = cad.load_cached(str(p), "normal")
    assert g2 is not None and np.array_equal(g.tris, g2.tris) and np.allclose(g.nodes, g2.nodes)


@pytest.mark.skipif(not cad.available_backends(), reason="no OpenCASCADE backend (cadquery-ocp or gmsh)")
@pytest.mark.parametrize("backend", ["ocp", "gmsh"])
def test_step_import_and_section_of_the_example_rig(backend, tmp_path):
    if backend not in cad.available_backends():
        pytest.skip(f"{backend} not installed")
    if backend == "ocp":
        g = cad.read_geometry(RIG, "normal", backend="ocp")
    else:   # gmsh brings its own OpenCASCADE: read in a child process, as the GUI does
        out = tmp_path / "rig.npz"
        r = subprocess.run([sys.executable, "-m", "myflownet.cad", RIG, str(out), "coarse", "gmsh"],
                           cwd=os.path.join(HERE, ".."), capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        g = cad.CadGeometry.load(str(out))
    lo, hi = g.bbox
    assert hi[0] - lo[0] == pytest.approx(350.0, abs=0.5)          # axial length [mm]
    assert hi[1] == pytest.approx(452.0, abs=0.5)                   # casing outer radius
    assert g.n_parts >= 5
    v = GeometryView(g, ViewSpec(axis="x", theta=0.0))
    shaft = [l for l in v.loops_plane if l[1] and l[0][:, 1].max() < 120.0]
    assert len(shaft) == 1
    assert shaft[0][0][:, 1].min() == pytest.approx(90.0, abs=1e-6)
    assert shaft[0][0][:, 1].max() == pytest.approx(110.0, abs=1e-6)
    # the cut plane at θ = 0 passes through a pre-swirl nozzle: a hole loop at r = 250 ± 3.5 mm
    holes = [l for l in v.loops_plane if l[1] and 240 < l[0][:, 1].min() and l[0][:, 1].max() < 260]
    assert holes
    if backend == "ocp":
        radii = set(np.round(g.face_radius[g.face_kind == 2], 3))
        assert {3.5, 4.0, 2.5, 90.0, 110.0, 452.0} <= radii           # nozzle, receiver, feed holes, shaft, casing
