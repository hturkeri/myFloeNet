"""Projection of a tessellated CAD model onto the 2D network canvas (pure numpy, no Qt).

Coordinates
-----------
The engine axis ``a`` and the cut angle θ define the *meridional frame*

    a                       axial direction            -> canvas right
    e_r = cosθ e0 + sinθ e1 radial direction in the cut plane -> canvas up
    n   = a × e_r           cut-plane normal, toward the viewer

so that, in the default view (yaw = pitch = 0), the canvas shows the meridional section
x–r of the engine: one canvas direction is the axial coordinate and the other the radius.
Yaw / pitch turn the model for a three-dimensional impression; points of the cut plane keep
an exact (affine) relation to the canvas in every view, so radii can still be read off.

Pipeline: nodes -> meridional coordinates -> clipping by the cut plane (keep the half behind
it) and optionally by the axial plane (keep r >= 0) -> section loops of the cut plane ->
view rotation -> flat shading and depth order (painter's algorithm).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
        "-x": (-1.0, 0.0, 0.0), "-y": (0.0, -1.0, 0.0), "-z": (0.0, 0.0, -1.0)}
_REF = {"x": (0.0, 1.0, 0.0), "y": (0.0, 0.0, 1.0), "z": (1.0, 0.0, 0.0)}
LIGHT_DIR = np.array([-0.35, 0.55, 1.0]) / np.linalg.norm([-0.35, 0.55, 1.0])


@dataclass
class ViewSpec:
    axis: str = "x"                 # engine axis (x, y, z, -x, -y, -z)
    origin: tuple = (0.0, 0.0, 0.0)  # a point on the engine axis [mm]
    theta: float = 0.0              # angle of the cut plane about the axis [deg]
    yaw: float = 0.0                # view rotation about the canvas vertical [deg]
    pitch: float = 0.0              # view rotation about the canvas horizontal [deg]
    cut: bool = True                # remove the geometry in front of the cut plane
    upper_half: bool = True         # keep only r >= 0 (half-section)

    @classmethod
    def from_dict(cls, d: dict) -> "ViewSpec":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def meridional_frame(axis: str = "x", theta: float = 0.0) -> np.ndarray:
    """Rows: axial unit vector a, radial unit vector e_r in the cut plane, cut-plane normal n."""
    a = np.array(AXES[axis], float)
    e0 = np.array(_REF[axis.lstrip("-")], float)
    e1 = np.cross(a, e0)
    t = math.radians(theta)
    er = math.cos(t) * e0 + math.sin(t) * e1
    n = np.cross(a, er)
    return np.array([a, er, n])


def view_rotation(yaw: float = 0.0, pitch: float = 0.0) -> np.ndarray:
    y, p = math.radians(yaw), math.radians(pitch)
    ry = np.array([[math.cos(y), 0.0, math.sin(y)], [0.0, 1.0, 0.0], [-math.sin(y), 0.0, math.cos(y)]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(p), -math.sin(p)], [0.0, math.sin(p), math.cos(p)]])
    return rx @ ry


# ----------------------------------------------------------------------- clipping
def clip_triangles(tri: np.ndarray, f: np.ndarray, attrs: list[np.ndarray]):
    """Keep the part of each triangle where f >= 0 (f linear, given at the vertices).
    tri (N,3,D), f (N,3); attrs are per-triangle arrays carried along."""
    inside = f >= 0.0
    cnt = inside.sum(axis=1)
    keep = cnt == 3
    out_t = [tri[keep]]
    out_a = [[a[keep] for a in attrs]]
    for case in (1, 2):
        m = cnt == case
        if not m.any():
            continue
        T, F = tri[m], f[m]
        # rotate so that the odd vertex (inside for case 1, outside for case 2) is first
        k = np.argmax(inside[m], axis=1) if case == 1 else np.argmin(inside[m], axis=1)
        idx = (k[:, None] + np.arange(3)[None, :]) % 3
        T = np.take_along_axis(T, idx[:, :, None], axis=1)
        F = np.take_along_axis(F, idx, axis=1)
        A, B, C = T[:, 0], T[:, 1], T[:, 2]
        fa, fb, fc = F[:, :1], F[:, 1:2], F[:, 2:3]
        pab = A + (B - A) * (fa / (fa - fb))
        pac = A + (C - A) * (fa / (fa - fc))
        att = [a[m] for a in attrs]
        if case == 1:
            out_t.append(np.stack([A, pab, pac], axis=1))
            out_a.append(att)
        else:
            out_t.append(np.stack([pab, B, C], axis=1))
            out_t.append(np.stack([pab, C, pac], axis=1))
            out_a.append(att)
            out_a.append(att)
    tri_o = np.concatenate(out_t) if out_t else tri[:0]
    attrs_o = [np.concatenate([oa[i] for oa in out_a]) for i in range(len(attrs))]
    return tri_o, attrs_o


def subdivide_long(tri: np.ndarray, attrs: list[np.ndarray], max_len: float, max_pass: int = 6):
    """Bisect the longest edge of triangles longer than max_len (keeps the painter's algorithm
    honest for long, thin triangles such as the strips of large cylinders)."""
    for _ in range(max_pass):
        e = np.stack([np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
                      np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
                      np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)], axis=1)
        k = np.argmax(e, axis=1)
        m = e[np.arange(len(e)), k] > max_len
        if not m.any():
            break
        T = tri[m]
        idx = (k[m][:, None] + np.arange(3)[None, :]) % 3   # longest edge = (0, 1)
        T = np.take_along_axis(T, idx[:, :, None], axis=1)
        mid = 0.5 * (T[:, 0] + T[:, 1])
        t1 = np.stack([T[:, 0], mid, T[:, 2]], axis=1)
        t2 = np.stack([mid, T[:, 1], T[:, 2]], axis=1)
        tri = np.concatenate([tri[~m], t1, t2])
        attrs = [np.concatenate([a[~m], a[m], a[m]]) for a in attrs]
    return tri, attrs


def subdivide_segments(seg: np.ndarray, max_len: float, max_pass: int = 6):
    for _ in range(max_pass):
        L = np.linalg.norm(seg[:, 1] - seg[:, 0], axis=1)
        m = L > max_len
        if not m.any():
            break
        S = seg[m]
        mid = 0.5 * (S[:, 0] + S[:, 1])
        seg = np.concatenate([seg[~m], np.stack([S[:, 0], mid], axis=1), np.stack([mid, S[:, 1]], axis=1)])
    return seg


def clip_segments(seg: np.ndarray, f: np.ndarray):
    """Keep the part of each segment (N,2,D) where f >= 0."""
    ins = f >= 0.0
    both = ins.all(axis=1)
    one = ins.any(axis=1) & ~both
    out = [seg[both]]
    if one.any():
        S, F = seg[one].copy(), f[one]
        t = F[:, 0] / (F[:, 0] - F[:, 1])
        p = S[:, 0] + (S[:, 1] - S[:, 0]) * t[:, None]
        first_in = ins[one][:, 0]
        S[first_in, 1] = p[first_in]
        S[~first_in, 0] = p[~first_in]
        out.append(S)
    return np.concatenate(out)


def clip_polyline_halfplane(pts: np.ndarray, closed: bool, k: int = 1):
    """Clip a 2D polyline / polygon to pts[:, k] >= 0.  Returns a list of (points, closed)."""
    v = pts[:, k]
    if (v >= 0).all():
        return [(pts, closed)]
    if (v < 0).all():
        return []
    if closed:
        # Sutherland-Hodgman against one half-plane
        out = []
        n = len(pts)
        for i in range(n):
            p, q = pts[i], pts[(i + 1) % n]
            pin, qin = p[k] >= 0, q[k] >= 0
            if pin:
                out.append(p)
            if pin != qin:
                t = p[k] / (p[k] - q[k])
                out.append(p + (q - p) * t)
        return [(np.array(out), True)] if len(out) >= 3 else []
    pieces, cur = [], []
    for i in range(len(pts)):
        p = pts[i]
        if i:
            q = pts[i - 1]
            if (p[k] >= 0) != (q[k] >= 0):
                t = q[k] / (q[k] - p[k])
                x = q + (p - q) * t
                cur.append(x)
                if p[k] < 0:
                    pieces.append(cur)
                    cur = []
        if p[k] >= 0:
            cur.append(p)
    if cur:
        pieces.append(cur)
    return [(np.array(c), False) for c in pieces if len(c) >= 2]


# ----------------------------------------------------------------------- section
def plane_section(nodes_q: np.ndarray, tris: np.ndarray, tri_part: np.ndarray, eps: float):
    """Intersection of the triangle mesh with the plane q[:,2] = 0.
    Returns a list of (points (k,2) in (q0, q1), closed, part)."""
    if not len(tris):
        return []
    d = nodes_q[:, 2].copy()
    d[np.abs(d) < eps] = eps
    s = d[tris] > 0.0
    cnt = s.sum(axis=1)
    m = (cnt == 1) | (cnt == 2)
    if not m.any():
        return []
    T, S, C = tris[m], s[m], cnt[m]
    part = tri_part[m]
    k = np.where(C == 1, np.argmax(S, axis=1), np.argmin(S, axis=1))
    i0 = T[np.arange(len(T)), k]
    i1 = T[np.arange(len(T)), (k + 1) % 3]
    i2 = T[np.arange(len(T)), (k + 2) % 3]

    def point(a, b):
        t = d[a] / (d[a] - d[b])
        return nodes_q[a, :2] + (nodes_q[b, :2] - nodes_q[a, :2]) * t[:, None]
    pa, pb = point(i0, i1), point(i0, i2)
    nn = len(nodes_q)
    npart = int(tri_part.max()) + 1 if len(tri_part) else 1
    # key = mesh edge + part: coincident faces of touching solids must not join their loops
    ka = (np.minimum(i0, i1).astype(np.int64) * nn + np.maximum(i0, i1)) * npart + part
    kb = (np.minimum(i0, i2).astype(np.int64) * nn + np.maximum(i0, i2)) * npart + part
    # chain the segments through their shared mesh edges
    nseg = len(ka)
    keys = np.concatenate([ka, kb])
    order = np.argsort(keys, kind="stable")
    sk = keys[order]
    # map key -> list of (segment, end)
    starts = np.flatnonzero(np.concatenate([[True], sk[1:] != sk[:-1]]))
    ends = np.append(starts[1:], len(sk))
    nbr = {}
    for s0, e0 in zip(starts, ends):
        ids = order[s0:e0]
        nbr[int(sk[s0])] = [(int(i % nseg), int(i // nseg)) for i in ids]
    used = np.zeros(nseg, bool)
    pts_end = (pa, pb)
    key_end = (ka, kb)
    loops = []
    for s0 in range(nseg):
        if used[s0]:
            continue
        used[s0] = True
        chain = [pa[s0], pb[s0]]
        closed = False
        # walk forward from end 1, then backward from end 0
        for direction in (1, 0):
            cur_seg, cur_end = s0, direction
            pts = []
            while True:
                key = int(key_end[cur_end][cur_seg])
                nxt = None
                for (sg, en) in nbr.get(key, ()):
                    if sg != cur_seg and not used[sg]:
                        nxt = (sg, en)
                        break
                if nxt is None:
                    if direction == 1 and key == int(ka[s0]) and len(pts) > 0:
                        closed = True
                    break
                sg, en = nxt
                used[sg] = True
                other = 1 - en
                pts.append(pts_end[other][sg])
                cur_seg, cur_end = sg, other
            if direction == 1:
                chain.extend(pts)
                if closed:
                    break
            else:
                chain = list(reversed(pts)) + chain
        arr = np.array(chain)
        if closed and len(arr) > 3:
            arr = arr[:-1]
        loops.append((arr, closed, int(part[s0])))
    return loops


def corner_points(pts: np.ndarray, closed: bool, angle_deg: float = 25.0, min_len: float = 0.0):
    """Points of a polyline where the direction turns by more than angle_deg."""
    n = len(pts)
    if n < 3:
        return pts[[0, -1]] if n == 2 and not closed else pts
    prev = np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0)
    d1 = pts - prev
    d2 = nxt - pts
    l1 = np.linalg.norm(d1, axis=1)
    l2 = np.linalg.norm(d2, axis=1)
    ok = (l1 > 1e-12) & (l2 > 1e-12)
    c = np.ones(n)
    c[ok] = np.einsum("ij,ij->i", d1[ok], d2[ok]) / (l1[ok] * l2[ok])
    sel = c < math.cos(math.radians(angle_deg))
    if not closed:
        sel[0] = sel[-1] = True
    return pts[sel]


# ----------------------------------------------------------------------- the view
class GeometryView:
    """Everything the canvas needs to draw a CAD model, in view millimetres (u right, v up)."""

    def __init__(self, geom, spec: ViewSpec, show_faces=True, show_edges=True, show_section=True):
        self.spec = spec
        self.geom = geom
        diag = geom.diag
        eps = 1e-9 * diag
        B = meridional_frame(spec.axis, spec.theta)
        R = view_rotation(spec.yaw, spec.pitch)
        O = np.asarray(spec.origin, float)
        self.B, self.R, self.O = B, R, O
        self.plane_to_view = R[:2, :2].copy()           # (u0, v0) -> (u, v)
        Q = (geom.nodes - O) @ B.T                       # meridional coordinates
        self.Q = Q
        tri_part = geom.face_part[geom.tri_face] if len(geom.tris) else np.zeros(0, np.int32)

        # ---- faces: clip and project
        tri = Q[geom.tris] if len(geom.tris) else np.zeros((0, 3, 3))
        attrs = [tri_part]
        if show_faces and len(tri):
            if spec.cut:
                tri, attrs = clip_triangles(tri, -tri[:, :, 2], attrs)
            if spec.upper_half:
                tri, attrs = clip_triangles(tri, tri[:, :, 1], attrs)
            if len(tri):
                tri, attrs = subdivide_long(tri, attrs, diag / 25.0)
            V = tri @ R.T
            nrm = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
            area = np.linalg.norm(nrm, axis=1)
            ok = area > (1e-10 * diag * diag)
            V, nrm, area = V[ok], nrm[ok], area[ok]
            part = attrs[0][ok]
            nrm = nrm / area[:, None]
            self.tri2d = V[:, :, :2].astype(np.float32)
            self.tri_depth = V[:, :, 2].mean(axis=1)
            self.tri_shade = (0.40 + 0.60 * np.abs(nrm @ LIGHT_DIR)).astype(np.float32)
            self.tri_part = part.astype(np.int32)
        else:
            self.tri2d = np.zeros((0, 3, 2), np.float32)
            self.tri_depth = np.zeros(0)
            self.tri_shade = np.zeros(0, np.float32)
            self.tri_part = np.zeros(0, np.int32)

        # ---- CAD edges
        if show_edges and len(geom.segs):
            S = Q[geom.segs]
            if spec.cut:
                S = clip_segments(S, -S[:, :, 2])
            if spec.upper_half and len(S):
                S = clip_segments(S, S[:, :, 1])
            if len(S):
                S = subdivide_segments(S, diag / 25.0)
            V = S @ R.T
            self.seg2d = V[:, :, :2].astype(np.float32)
            self.seg_depth = V[:, :, 2].mean(axis=1) + 2e-3 * diag
        else:
            self.seg2d = np.zeros((0, 2, 2), np.float32)
            self.seg_depth = np.zeros(0)

        # ---- section of the cut plane
        self.loops_plane = []
        if spec.cut and show_section and len(geom.tris):
            for pts, closed, part in plane_section(Q, geom.tris, tri_part, eps):
                pieces = clip_polyline_halfplane(pts, closed, 1) if spec.upper_half else [(pts, closed)]
                for p2, c2 in pieces:
                    self.loops_plane.append((p2, c2, part))
        A = self.plane_to_view
        self.loops = [(p @ A.T, c, part) for p, c, part in self.loops_plane]

        # ---- painter's order (far -> near); edges carry a small bias toward the viewer
        depth = np.concatenate([self.tri_depth, self.seg_depth])
        self.order = np.argsort(depth, kind="stable")
        self.n_tri = len(self.tri_depth)

        # ---- snap points: CAD vertices that are kept + corners of the section loops
        snaps = []
        if len(geom.vertices):
            Vq = (geom.vertices - O) @ B.T
            keep = np.ones(len(Vq), bool)
            if spec.cut:                      # only vertices lying in the cut plane
                keep &= np.abs(Vq[:, 2]) <= 1e-4 * diag
            if spec.upper_half:
                keep &= Vq[:, 1] >= -1e-6 * diag
            snaps.append((Vq[keep] @ R.T)[:, :2])
        for p, c, _ in self.loops_plane:
            snaps.append(corner_points(p, c) @ A.T)
        self.snap2d = np.vstack(snaps) if snaps else np.zeros((0, 2))
        if len(self.snap2d):
            q = np.round(self.snap2d / (1e-6 * diag)).astype(np.int64)
            _, idx = np.unique(q, axis=0, return_index=True)
            self.snap2d = self.snap2d[np.sort(idx)]

        # ---- bounds
        pts = [self.tri2d.reshape(-1, 2), self.seg2d.reshape(-1, 2)] + [p for p, _, _ in self.loops]
        pts = [p for p in pts if len(p)]
        if pts:
            allp = np.vstack(pts)
            self.bounds = (float(allp[:, 0].min()), float(allp[:, 1].min()),
                           float(allp[:, 0].max()), float(allp[:, 1].max()))
        else:
            self.bounds = (0.0, 0.0, 1.0, 1.0)

    # ------------------------------------------------------------------ queries
    @property
    def is_meridional(self) -> bool:
        return abs(self.spec.yaw) < 1e-9 and abs(self.spec.pitch) < 1e-9

    def view_to_plane(self, u: float, v: float):
        """Canvas view point -> (axial, radial) coordinates in the cut plane [mm], or None."""
        A = self.plane_to_view
        det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
        if abs(det) < 1e-6:
            return None
        x0 = (A[1, 1] * u - A[0, 1] * v) / det
        y0 = (-A[1, 0] * u + A[0, 0] * v) / det
        return float(x0), float(y0)

    def plane_to_view_pt(self, axial: float, radial: float):
        A = self.plane_to_view
        return float(A[0, 0] * axial + A[0, 1] * radial), float(A[1, 0] * axial + A[1, 1] * radial)

    def nearest_snap(self, u: float, v: float, tol: float):
        if not len(self.snap2d):
            return None
        d2 = (self.snap2d[:, 0] - u) ** 2 + (self.snap2d[:, 1] - v) ** 2
        i = int(np.argmin(d2))
        if d2[i] <= tol * tol:
            return float(self.snap2d[i, 0]), float(self.snap2d[i, 1])
        return None
