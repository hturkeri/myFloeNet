"""CAD geometry import for the background of the network canvas.

STEP / IGES / BREP are read and tessellated with OpenCASCADE through one of two optional
backends (whichever is installed):

* ``cadquery-ocp``  (``python -m pip install cadquery-ocp``) - preferred: fast
  BRepMesh tessellation, exact CAD edges, cylinder radii and axes per face;
* ``gmsh``          (``python -m pip install gmsh``)         - fallback: surface mesh
  of the CAD faces, CAD curves as edges.

STL (ASCII or binary) is read natively with numpy; feature edges are taken from the
dihedral angle between neighbouring triangles.

The result is a :class:`CadGeometry` (numpy arrays, millimetres).  Reading runs in a
separate process in the GUI (``python -m myflownet.cad in.step out.npz``) so a large or
broken file never freezes or crashes the editor, and the tessellation is cached on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field

import numpy as np

CAD_EXTS = (".step", ".stp", ".iges", ".igs", ".brep", ".brp")
MESH_EXTS = (".stl",)
SUPPORTED_EXTS = CAD_EXTS + MESH_EXTS
FILE_FILTER = "CAD geometry (*.step *.stp *.iges *.igs *.brep *.stl);;STEP (*.step *.stp);;IGES (*.iges *.igs);;STL (*.stl)"
CACHE_VERSION = 3

# relative linear deflection (fraction of the bounding-box diagonal), angular deflection [rad]
QUALITY = {"coarse": (2.0e-3, 0.50), "normal": (8.0e-4, 0.30), "fine": (3.0e-4, 0.18)}

# gmsh fallback: maximum element size = diagonal / k, elements per 2π of curvature
# (very coarse sizes make gmsh's surface mesher unstable on some models)
GMSH_QUALITY = {"coarse": (18.0, 6), "normal": (25.0, 8), "fine": (40.0, 12)}

FACE_KINDS = ("other", "plane", "cylinder", "cone", "sphere", "torus", "bspline", "revolution")

INSTALL_HINT = ("Reading STEP / IGES needs an OpenCASCADE backend. Install one of them in the Python that "
                "runs myFlowNet:\n\n    python -m pip install cadquery-ocp      (recommended)\n"
                "    python -m pip install gmsh\n\nSTL files can be read without them.")


class CadError(RuntimeError):
    pass


class BackendMissing(CadError):
    pass


@dataclass
class CadGeometry:
    """Tessellated CAD model.  All coordinates in millimetres."""
    nodes: np.ndarray                      # (M, 3) float64
    tris: np.ndarray                       # (N, 3) int32 node indices
    tri_face: np.ndarray                   # (N,) int32 face index
    face_part: np.ndarray                  # (F,) int32 part (solid) index
    face_kind: np.ndarray                  # (F,) int8 index into FACE_KINDS
    face_radius: np.ndarray                # (F,) float64, cylinder / cone radius (nan otherwise)
    face_axis: np.ndarray                  # (F, 3) axis direction of cylinders (zeros otherwise)
    face_origin: np.ndarray                # (F, 3) a point on the cylinder axis
    segs: np.ndarray                       # (S, 2) int32 node indices of CAD edge segments
    vertices: np.ndarray                   # (V, 3) CAD vertices
    part_names: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------- info
    @property
    def bbox(self):
        pts = self.nodes if len(self.nodes) else self.vertices
        if not len(pts):
            return np.zeros(3), np.zeros(3)
        return pts.min(axis=0), pts.max(axis=0)

    @property
    def diag(self) -> float:
        lo, hi = self.bbox
        return float(np.linalg.norm(hi - lo)) or 1.0

    @property
    def n_parts(self) -> int:
        return int(self.face_part.max()) + 1 if len(self.face_part) else 0

    def summary(self) -> str:
        lo, hi = self.bbox
        size = " × ".join(f"{v:.0f}" for v in (hi - lo))
        if not len(self.tris):
            return (f"wireframe: {len(self.segs):,} edge segments, {len(self.vertices)} vertices; "
                    f"size {size} mm  [{self.meta.get('backend', '?')}]")
        return (f"{self.meta.get('faces', len(self.face_kind))} faces, {self.n_parts} part(s), "
                f"{len(self.tris):,} triangles; size {size} mm  [{self.meta.get('backend', '?')}]")

    def scaled(self, factor: float) -> "CadGeometry":
        if factor == 1.0:
            return self
        g = CadGeometry(**{k: getattr(self, k) for k in self.__dataclass_fields__})
        g.nodes = self.nodes * factor
        g.vertices = self.vertices * factor
        g.face_radius = self.face_radius * factor
        g.face_origin = self.face_origin * factor
        return g

    # ------------------------------------------------------------- npz
    def save(self, path: str):
        np.savez_compressed(path, nodes=self.nodes, tris=self.tris, tri_face=self.tri_face,
                            face_part=self.face_part, face_kind=self.face_kind, face_radius=self.face_radius,
                            face_axis=self.face_axis, face_origin=self.face_origin, segs=self.segs,
                            vertices=self.vertices,
                            info=np.array(json.dumps({"part_names": self.part_names, "meta": self.meta,
                                                      "cache_version": CACHE_VERSION})))

    @classmethod
    def load(cls, path: str) -> "CadGeometry":
        with np.load(path, allow_pickle=False) as d:
            info = json.loads(str(d["info"]))
            if info.get("cache_version") != CACHE_VERSION:
                raise CadError("outdated cache file")
            return cls(d["nodes"], d["tris"], d["tri_face"], d["face_part"], d["face_kind"], d["face_radius"],
                       d["face_axis"], d["face_origin"], d["segs"], d["vertices"],
                       info.get("part_names", []), info.get("meta", {}))


# ======================================================================= helpers
def _merge_nodes(nodes: np.ndarray, *index_arrays, tol_rel=1e-7):
    """Merge coincident nodes (faces of a B-rep are triangulated separately)."""
    if not len(nodes):
        return nodes, index_arrays
    span = float(np.ptp(nodes, axis=0).max()) or 1.0
    q = np.round(nodes / (span * tol_rel)).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    return nodes[first], tuple(inv[np.asarray(a, np.int64)].astype(np.int32) for a in index_arrays)


def _unique_segments(segs: np.ndarray) -> np.ndarray:
    if not len(segs):
        return np.zeros((0, 2), np.int32)
    s = np.sort(segs, axis=1)
    s = s[s[:, 0] != s[:, 1]]
    return np.unique(s, axis=0).astype(np.int32)


def feature_edges(nodes: np.ndarray, tris: np.ndarray, angle_deg: float = 30.0) -> np.ndarray:
    """Edges whose dihedral angle exceeds angle_deg, plus open (boundary) edges."""
    if not len(tris):
        return np.zeros((0, 2), np.int32)
    p = nodes[tris]
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    t = np.tile(np.arange(len(tris)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, t = key[order], t[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    out = []
    m = len(key)
    starts = np.flatnonzero(np.concatenate([[True], ~same]))
    ends = np.append(starts[1:], m)
    cos_lim = np.cos(np.radians(angle_deg))
    for s, f in zip(starts, ends):
        if f - s == 1:
            out.append(key[s])
        elif f - s == 2:
            if abs(np.dot(n[t[s]], n[t[s + 1]])) < cos_lim:
                out.append(key[s])
        else:
            out.append(key[s])
    return np.array(out, np.int32).reshape(-1, 2)


def _assemble(nodes_list, tris_list, tri_face_list, face_info, seg_list, vertices, part_names, meta):
    nodes = np.vstack(nodes_list) if nodes_list else np.zeros((0, 3))
    tris = np.vstack(tris_list).astype(np.int64) if tris_list else np.zeros((0, 3), np.int64)
    tri_face = np.concatenate(tri_face_list).astype(np.int32) if tri_face_list else np.zeros(0, np.int32)
    segs = np.vstack(seg_list).astype(np.int64) if seg_list else np.zeros((0, 2), np.int64)
    nodes, (tris, segs) = _merge_nodes(nodes, tris, segs)
    if len(tris):
        bad = (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2])
        tris, tri_face = tris[~bad], tri_face[~bad]
    segs = _unique_segments(segs)
    F = len(face_info)
    face_part = np.array([f[0] for f in face_info], np.int32).reshape(F)
    face_kind = np.array([f[1] for f in face_info], np.int8).reshape(F)
    face_radius = np.array([f[2] for f in face_info], float).reshape(F)
    face_axis = np.array([f[3] for f in face_info], float).reshape(F, 3)
    face_origin = np.array([f[4] for f in face_info], float).reshape(F, 3)
    vertices = np.array(vertices, float).reshape(-1, 3)
    if len(vertices):
        span = float(np.ptp(vertices, axis=0).max()) or 1.0
        _, idx = np.unique(np.round(vertices / (span * 1e-7)).astype(np.int64), axis=0, return_index=True)
        vertices = vertices[np.sort(idx)]
    meta = dict(meta)
    meta.setdefault("faces", F)
    return CadGeometry(nodes.astype(float), tris.astype(np.int32), tri_face, face_part, face_kind, face_radius,
                       face_axis, face_origin, segs, vertices, list(part_names), meta)


def _report(progress, frac, msg):
    if progress is not None:
        progress(frac, msg)


# ======================================================================= backends
def available_backends() -> list[str]:
    """Installed OpenCASCADE backends (found without importing them: the two ship their own
    OpenCASCADE libraries, which must not be loaded into the same process)."""
    import importlib.util
    out = []
    for name, mod in (("ocp", "OCP"), ("gmsh", "gmsh")):
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(name)
        except Exception:
            pass
    return out


def _read_ocp(path, quality, progress):
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.Bnd import Bnd_Box
    from OCP.GCPnts import GCPnts_TangentialDeflection
    from OCP.GeomAbs import GeomAbs_SurfaceType as ST
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS, TopoDS_Shape

    def cast(name):
        return getattr(TopoDS, name + "_s", None) or getattr(TopoDS, name)
    as_face, as_edge, as_vertex = cast("Face"), cast("Edge"), cast("Vertex")

    ext = os.path.splitext(path)[1].lower()
    _report(progress, 0.05, "Reading the CAD file")
    if ext in (".step", ".stp", ".iges", ".igs"):
        if ext in (".step", ".stp"):
            from OCP.STEPControl import STEPControl_Reader as Reader
        else:
            from OCP.IGESControl import IGESControl_Reader as Reader
        rd = Reader()
        if rd.ReadFile(path) != IFSelect_RetDone:
            raise CadError(f"OpenCASCADE could not read {os.path.basename(path)}")
        rd.TransferRoots()
        shape = rd.OneShape()
    else:
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, path, BRep_Builder()):
            raise CadError(f"OpenCASCADE could not read {os.path.basename(path)}")
    if shape is None or shape.IsNull():
        raise CadError("The file contains no geometry")

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    lo, hi = np.array(box.CornerMin().Coord()), np.array(box.CornerMax().Coord())
    diag = float(np.linalg.norm(hi - lo)) or 1.0
    lin_rel, ang = QUALITY.get(quality, QUALITY["normal"])
    _report(progress, 0.25, "Tessellating the faces")
    BRepMesh_IncrementalMesh(shape, lin_rel * diag, False, ang, True)

    kinds = {ST.GeomAbs_Plane: 1, ST.GeomAbs_Cylinder: 2, ST.GeomAbs_Cone: 3, ST.GeomAbs_Sphere: 4,
             ST.GeomAbs_Torus: 5, ST.GeomAbs_BSplineSurface: 6, ST.GeomAbs_BezierSurface: 6,
             ST.GeomAbs_SurfaceOfRevolution: 7}
    nodes_l, tris_l, tf_l, seg_l, face_info = [], [], [], [], []
    state = {"off": 0}

    def add_face(f, part):
        fi = len(face_info)
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        kind, rad, axis, origin = 0, np.nan, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        try:
            ad = BRepAdaptor_Surface(f)
            st = ad.GetType()
            kind = kinds.get(st, 0)
            if st == ST.GeomAbs_Cylinder:
                c = ad.Cylinder()
                rad = c.Radius()
                axis = c.Axis().Direction().Coord()
                origin = c.Location().Coord()
            elif st == ST.GeomAbs_Cone:
                c = ad.Cone()
                rad = c.RefRadius()
                axis = c.Axis().Direction().Coord()
                origin = c.Location().Coord()
        except Exception:
            pass
        face_info.append((part, kind, rad, axis, origin))
        if tri is None:
            return
        trsf = loc.Transformation()
        n = tri.NbNodes()
        pts = np.array([tri.Node(i).Transformed(trsf).Coord() for i in range(1, n + 1)], float)
        t = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], np.int64).reshape(-1, 3) - 1
        if f.Orientation() == TopAbs_REVERSED:
            t = t[:, [0, 2, 1]]
        off = state["off"]
        nodes_l.append(pts)
        tris_l.append(t + off)
        tf_l.append(np.full(len(t), fi, np.int32))
        ex = TopExp_Explorer(f, TopAbs_EDGE)
        while ex.More():
            e = as_edge(ex.Current())
            try:
                pol = BRep_Tool.PolygonOnTriangulation_s(e, tri, loc)
            except Exception:
                pol = None
            if pol is not None and pol.NbNodes() > 1:
                ids = np.array([pol.Node(i) for i in range(1, pol.NbNodes() + 1)], np.int64) - 1 + off
                seg_l.append(np.column_stack([ids[:-1], ids[1:]]))
            ex.Next()
        state["off"] += n

    part_names = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        part = len(part_names)
        part_names.append(f"Solid {part + 1}")
        fx = TopExp_Explorer(ex.Current(), TopAbs_FACE)
        while fx.More():
            add_face(as_face(fx.Current()), part)
            fx.Next()
        ex.Next()
        _report(progress, 0.3 + 0.5 * min(1.0, len(part_names) / 50.0), f"Faces of part {part + 1}")
    # faces that do not belong to a solid (open shells, surface models)
    fx = TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SOLID)
    free = False
    while fx.More():
        if not free:
            part_names.append("Surfaces")
            free = True
        add_face(as_face(fx.Current()), len(part_names) - 1)
        fx.Next()
    # free curves (wireframe IGES, sketches)
    _report(progress, 0.85, "Edges and vertices")
    ex = TopExp_Explorer(shape, TopAbs_EDGE, TopAbs_FACE)
    while ex.More():
        e = as_edge(ex.Current())
        try:
            if not BRep_Tool.Degenerated_s(e):
                cur = BRepAdaptor_Curve(e)
                tdf = GCPnts_TangentialDeflection(cur, ang, lin_rel * diag)
                pts = np.array([tdf.Value(i).Coord() for i in range(1, tdf.NbPoints() + 1)], float)
                if len(pts) > 1:
                    off = state["off"]
                    nodes_l.append(pts)
                    ids = np.arange(len(pts)) + off
                    seg_l.append(np.column_stack([ids[:-1], ids[1:]]))
                    state["off"] += len(pts)
        except Exception:
            pass
        ex.Next()
    verts = []
    ex = TopExp_Explorer(shape, TopAbs_VERTEX)
    while ex.More():
        verts.append(BRep_Tool.Pnt_s(as_vertex(ex.Current())).Coord())
        ex.Next()
    return _assemble(nodes_l, tris_l, tf_l, face_info, seg_l, verts, part_names,
                     {"backend": "OpenCASCADE (OCP)", "faces": len(face_info)})


def _read_gmsh(path, quality, progress):
    import gmsh
    try:
        gmsh.initialize(readConfigFiles=False, interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        _report(progress, 0.05, "Reading the CAD file (gmsh)")
        gmsh.model.add("background")
        gmsh.model.occ.importShapes(path)
        gmsh.model.occ.synchronize()
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = float(np.linalg.norm(np.array(bb[3:]) - np.array(bb[:3]))) or 1.0
        k, ncurv = GMSH_QUALITY.get(quality, GMSH_QUALITY["normal"])
        gmsh.option.setNumber("Mesh.MeshSizeMax", diag / k)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", ncurv)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Optimize", 0)
        gmsh.option.setNumber("Mesh.MaxNumThreads2D", os.cpu_count() or 1)
        _report(progress, 0.2, "Meshing the faces (gmsh)")
        surfaces = gmsh.model.getEntities(2)
        try:
            gmsh.model.mesh.generate(2 if surfaces else 1)
        except Exception:
            pass
        _report(progress, 0.8, "Collecting the mesh")
        tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.asarray(coords, float).reshape(-1, 3)
        tags = np.asarray(tags, np.int64)
        lut = np.zeros(int(tags.max()) + 1 if len(tags) else 1, np.int64)
        lut[tags] = np.arange(len(tags))
        vols = [t for _, t in gmsh.model.getEntities(3)]
        part_of = {}
        for k, v in enumerate(vols):
            _, down = gmsh.model.getAdjacencies(3, v)
            for s in down:
                part_of.setdefault(int(s), k)
        part_names = [f"Solid {k + 1}" for k in range(len(vols))]
        tris_l, tf_l, face_info, seg_l = [], [], [], []
        kindmap = {"Plane": 1, "Cylinder": 2, "Cone": 3, "Sphere": 4, "Torus": 5, "BSpline surface": 6,
                   "Bezier surface": 6, "Surface of Revolution": 7}
        free_part = None
        for _, s in surfaces:
            part = part_of.get(int(s))
            if part is None:
                if free_part is None:
                    free_part = len(part_names)
                    part_names.append("Surfaces")
                part = free_part
            fi = len(face_info)
            face_info.append((part, kindmap.get(gmsh.model.getType(2, s), 0), np.nan, (0, 0, 0), (0, 0, 0)))
            types, _, ntags = gmsh.model.mesh.getElements(2, s)
            for t, nn in zip(types, ntags):
                nn = lut[np.asarray(nn, np.int64)]
                if t == 2:
                    tri = nn.reshape(-1, 3)
                elif t == 3:
                    q = nn.reshape(-1, 4)
                    tri = np.vstack([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
                else:
                    continue
                tris_l.append(tri)
                tf_l.append(np.full(len(tri), fi, np.int32))
        for _, c in gmsh.model.getEntities(1):
            types, _, ntags = gmsh.model.mesh.getElements(1, c)
            for t, nn in zip(types, ntags):
                if t == 1:
                    seg_l.append(lut[np.asarray(nn, np.int64)].reshape(-1, 2))
        verts = [gmsh.model.getValue(0, p, []) for _, p in gmsh.model.getEntities(0)]
        return _assemble([coords], tris_l, tf_l, face_info, seg_l, verts, part_names,
                         {"backend": "gmsh " + getattr(gmsh, "__version__", ""), "faces": len(face_info)})
    finally:
        gmsh.finalize()


def read_stl(path) -> CadGeometry:
    with open(path, "rb") as f:
        data = f.read()
    tri = None
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=n, offset=84)
            tri = rec["v"].astype(float)
    if tri is None:
        txt = data.decode("latin-1")
        vals = []
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("vertex"):
                vals.append([float(x) for x in line.split()[1:4]])
        if not vals:
            raise CadError("No triangles found in the STL file")
        tri = np.array(vals, float).reshape(-1, 3, 3)
    nodes = tri.reshape(-1, 3)
    idx = np.arange(len(nodes)).reshape(-1, 3)
    nodes, (tris,) = _merge_nodes(nodes, idx, tol_rel=1e-6)
    bad = (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2])
    tris = tris[~bad]
    segs = feature_edges(nodes, tris, 30.0)
    return CadGeometry(nodes, tris.astype(np.int32), np.zeros(len(tris), np.int32), np.zeros(1, np.int32),
                       np.zeros(1, np.int8), np.full(1, np.nan), np.zeros((1, 3)), np.zeros((1, 3)),
                       segs, np.zeros((0, 3)), ["STL"], {"backend": "STL", "faces": 1})


def read_geometry(path: str, quality: str = "normal", backend: str = "auto", progress=None) -> CadGeometry:
    """Read and tessellate a CAD / STL file (in-process)."""
    if not os.path.isfile(path):
        raise CadError(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in MESH_EXTS:
        _report(progress, 0.1, "Reading the STL file")
        return read_stl(path)
    if ext not in CAD_EXTS:
        raise CadError(f"Unsupported file type '{ext}'. Supported: " + ", ".join(SUPPORTED_EXTS))
    avail = available_backends()
    order = [backend] if backend != "auto" else ["ocp", "gmsh"]
    order = [b for b in order if b in avail]
    if not order:
        raise BackendMissing(INSTALL_HINT)
    last = None
    for b in order:
        try:
            return (_read_ocp if b == "ocp" else _read_gmsh)(path, quality, progress)
        except BackendMissing:
            raise
        except Exception as ex:  # try the next backend
            last = ex
    raise CadError(str(last))


# ======================================================================= cache
def cache_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "myflownet-cad-cache")
    os.makedirs(d, exist_ok=True)
    return d


def cache_file(path: str, quality: str) -> str:
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}|{quality}|{CACHE_VERSION}"
    return os.path.join(cache_dir(), hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".npz")


def load_cached(path: str, quality: str):
    try:
        f = cache_file(path, quality)
        if os.path.isfile(f):
            return CadGeometry.load(f)
    except Exception:
        pass
    return None


def read_geometry_cached(path: str, quality: str = "normal", progress=None) -> CadGeometry:
    g = load_cached(path, quality)
    if g is None:
        g = read_geometry(path, quality, progress=progress)
        try:
            g.save(cache_file(path, quality))
        except Exception:
            pass
    return g


# ======================================================================= CLI (used by the GUI)
def main(argv=None):
    """python -m myflownet.cad <input> <output.npz> [quality] [ocp|gmsh]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(main.__doc__)
        return 2

    def prog(frac, msg):
        print(f"PROGRESS {frac:.2f} {msg}", flush=True)
    src, out = argv[0], argv[1]
    if sys.stdout is None or sys.stderr is None:      # pythonw.exe without pipes: log to a file
        logf = open(out + ".log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or logf
        sys.stderr = sys.stderr or logf
    quality = argv[2] if len(argv) > 2 else "normal"
    backend = argv[3] if len(argv) > 3 else "auto"
    avail = available_backends()
    if backend == "auto" and os.path.splitext(src)[1].lower() in CAD_EXTS and avail:
        backend = avail[0]
    t0 = time.time()
    try:
        g = read_geometry(src, quality, backend=backend, progress=prog)
    except BackendMissing as ex:
        print("BACKEND_MISSING " + str(ex).replace("\n", "\\n"), flush=True)
        return 3
    except Exception as ex:
        rest = avail[avail.index(backend) + 1:] if backend in avail else []
        if rest:          # the other backend has its own OpenCASCADE: run it in a fresh process
            import subprocess
            print(f"PROGRESS 0.05 {backend} failed ({ex}); trying {rest[0]}", flush=True)
            return subprocess.call([sys.executable, "-m", "myflownet.cad", src, out, quality, rest[0]])
        print("ERROR " + str(ex).replace("\n", " "), flush=True)
        return 1
    g.meta["seconds"] = round(time.time() - t0, 2)
    g.save(out)
    print(f"OK {len(g.tris)} {g.meta['seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
