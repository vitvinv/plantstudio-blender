"""QEM edge-collapse mesh simplification (Garland-Heckbert), pure stdlib.

simplify_mesh reduces the face count of an indexed triangle mesh — the same
{vertices, faces, face_colors} shape MeshBuffer.to_mesh_data returns — to
max(min_faces, floor(n * ratio)) faces using greedy quadric-error edge
collapses.

Locked edges are never collapsed: an edge with exactly 1 or more than 2
adjacent faces (boundary / non-manifold) or whose two faces have different
colors (color seam). Per-face colors therefore never bleed across part seams.

Each collapse moves the surviving vertex to the quadric-optimal point for the
pair clamped to the collapsed edge segment (midpoint fallback on singular or
worse-than-midpoint solves), and keeps the endpoint nearest it — the surface
reshapes along existing edges instead of folding or pulling inward (which
would shrivel stems and petals). This matches the behaviour of Blender's
Decimate modifier.

The greedy order is deterministic: a min-heap keyed by (cost, edge_id) where
edge_id is a stable integer rank per undirected edge, so pop order never
depends on set/dict iteration order.
"""

import heapq

__all__ = ["simplify_mesh"]


def _plane_quadric(ax, ay, az, bx, by, bz, cx, cy, cz):
    """Area-weighted plane quadric for a face (p0, p1, p2).

    Stored as the upper triangle of a symmetric 4x4 matrix, row-major:
    indices 0..9 map to [00, 01, 02, 03, 11, 12, 13, 22, 23, 33].
    """
    ux = bx - ax
    uy = by - ay
    uz = bz - az
    vx = cx - ax
    vy = cy - ay
    vz = cz - az
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    d = -(nx * ax + ny * ay + nz * az)
    return (nx * nx, nx * ny, nx * nz, nx * d,
            ny * ny, ny * nz, ny * d,
            nz * nz, nz * d,
            d * d)


def _face_normal(p0, p1, p2):
    """Normal of the triangle (p0, p1, p2) in face order (not normalized)."""
    ux = p1[0] - p0[0]
    uy = p1[1] - p0[1]
    uz = p1[2] - p0[2]
    vx = p2[0] - p0[0]
    vy = p2[1] - p0[1]
    vz = p2[2] - p0[2]
    return (uy * vz - uz * vy,
            uz * vx - ux * vz,
            ux * vy - uy * vx)


def _quadric_error_at(q0, q1, q2, q3, q4, q5, q6, q7, q8, q9, x, y, z):
    """p^T Q p with p = (x, y, z, 1) for a symmetric quadric Q."""
    return (q0 * x * x + 2.0 * q1 * x * y + 2.0 * q2 * x * z + 2.0 * q3 * x
            + q4 * y * y + 2.0 * q5 * y * z + 2.0 * q6 * y
            + q7 * z * z + 2.0 * q8 * z + q9)


class _Decimator:
    def __init__(self, vertices, faces, face_colors):
        self.verts = [tuple(v) for v in vertices]
        self.faces = [list(f) for f in faces]
        self.colors = list(face_colors)
        self.alive = [True] * len(self.faces)
        self.active = len(self.faces)
        self.vdead = [False] * len(self.verts)
        self.vadj = [set() for _ in self.verts]
        for fi, f in enumerate(self.faces):
            for vi in f:
                self.vadj[vi].add(fi)
        self.vq = [[0.0] * 10 for _ in self.verts]
        for fi, f in enumerate(self.faces):
            a = self.verts[f[0]]
            b = self.verts[f[1]]
            c = self.verts[f[2]]
            q = _plane_quadric(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2])
            for vi in f:
                target = self.vq[vi]
                for k in range(10):
                    target[k] += q[k]
        self.heap = []
        self.edge_ids = {}
        self._edge_counter = 0
        edge_faces = {}
        for fi, f in enumerate(self.faces):
            i, j, k = f
            for e in ((i, j), (j, k), (i, k)):
                lo, hi = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])
                edge_faces.setdefault((lo, hi), []).append(fi)
        for (lo, hi), flist in edge_faces.items():
            if len(flist) == 2 and self.colors[flist[0]] == self.colors[flist[1]]:
                self._push(lo, hi)

    def _edge_cost(self, a, b):
        shared = self.vadj[a] & self.vadj[b]
        if len(shared) != 2:
            return None
        flist = list(shared)
        if self.colors[flist[0]] != self.colors[flist[1]]:
            return None
        return self._pair_error(a, b)

    def _pair_optimum(self, a, b):
        """Best collapse cost and target for edge (a, b).

        Returns (cost, keep, px, py, pz): the quadric error at the optimal
        point (midpoint fallback on singular solve), the endpoint to keep
        (the one nearest the optimal point; lowest id on ties), and the
        optimal point itself.
        """
        qa = self.vq[a]
        qb = self.vq[b]
        q0 = qa[0] + qb[0]
        q1 = qa[1] + qb[1]
        q2 = qa[2] + qb[2]
        q3 = qa[3] + qb[3]
        q4 = qa[4] + qb[4]
        q5 = qa[5] + qb[5]
        q6 = qa[6] + qb[6]
        q7 = qa[7] + qb[7]
        q8 = qa[8] + qb[8]
        q9 = qa[9] + qb[9]
        ax, ay, az = self.verts[a]
        bx, by, bz = self.verts[b]
        mx = (ax + bx) * 0.5
        my = (ay + by) * 0.5
        mz = (az + bz) * 0.5
        mid_err = _quadric_error_at(q0, q1, q2, q3, q4, q5, q6, q7, q8, q9,
                                    mx, my, mz)
        px, py, pz = mx, my, mz
        a00, a01, a02 = q0, q1, q2
        a10, a11, a12 = q1, q4, q5
        a20, a21, a22 = q2, q5, q7
        b0 = -q3
        b1 = -q6
        b2 = -q8
        det = (a00 * (a11 * a22 - a12 * a21)
               - a01 * (a10 * a22 - a12 * a20)
               + a02 * (a10 * a21 - a11 * a20))
        cost = mid_err
        if det != 0.0:
            detx = (b0 * (a11 * a22 - a12 * a21)
                    - a01 * (b1 * a22 - a12 * b2)
                    + a02 * (b1 * a21 - a11 * b2))
            dety = (a00 * (b1 * a22 - a12 * b2)
                    - b0 * (a10 * a22 - a12 * a20)
                    + a02 * (a10 * b2 - b1 * a20))
            detz = (a00 * (a11 * b2 - b1 * a21)
                    - a01 * (a10 * b2 - b1 * a20)
                    + b0 * (a10 * a21 - a11 * a20))
            inv = 1.0 / det
            sx = detx * inv
            sy = dety * inv
            sz = detz * inv
            ex = bx - ax
            ey = by - ay
            ez = bz - az
            seg_len2 = ex * ex + ey * ey + ez * ez
            if seg_len2 > 0.0:
                t = ((sx - ax) * ex + (sy - ay) * ey
                     + (sz - az) * ez) / seg_len2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                sx = ax + t * ex
                sy = ay + t * ey
                sz = az + t * ez
            s_err = _quadric_error_at(q0, q1, q2, q3, q4, q5, q6, q7, q8, q9,
                                      sx, sy, sz)
            if s_err < mid_err:
                px, py, pz = sx, sy, sz
                cost = s_err
        da = ((px - ax) * (px - ax) + (py - ay) * (py - ay)
              + (pz - az) * (pz - az))
        db = ((px - bx) * (px - bx) + (py - by) * (py - by)
              + (pz - bz) * (pz - bz))
        if da <= db:
            keep = a
        else:
            keep = b
        return cost, keep, px, py, pz

    def _edge_cost(self, a, b):
        shared = self.vadj[a] & self.vadj[b]
        if len(shared) != 2:
            return None
        flist = list(shared)
        if self.colors[flist[0]] != self.colors[flist[1]]:
            return None
        cost, _keep, _px, _py, _pz = self._pair_optimum(a, b)
        return cost

    def _push(self, a, b):
        cost = self._edge_cost(a, b)
        if cost is None:
            return
        lo, hi = (a, b) if a < b else (b, a)
        eid = self.edge_ids.get((lo, hi))
        if eid is None:
            eid = self._edge_counter
            self._edge_counter += 1
            self.edge_ids[(lo, hi)] = eid
        heapq.heappush(self.heap, (cost, eid, lo, hi))

    def _neighbors(self, v):
        neighbors = set()
        for fi in self.vadj[v]:
            for w in self.faces[fi]:
                if w != v:
                    neighbors.add(w)
        return neighbors

    def _collapse_valid(self, keep, remove, target_pos):
        """True if collapsing remove -> keep onto target_pos keeps every
        face in the star (incident to either endpoint) unflipped and
        non-degenerate."""
        star_faces = set(self.vadj[keep]) | set(self.vadj[remove])
        for fi in star_faces:
            f = self.faces[fi]
            if keep in f and remove in f:
                continue
            orig = [self.verts[v] for v in f]
            n_old = _face_normal(orig[0], orig[1], orig[2])
            points = [
                target_pos if (v == keep or v == remove) else self.verts[v]
                for v in f
            ]
            n_new = _face_normal(points[0], points[1], points[2])
            dot = (n_old[0] * n_new[0] + n_old[1] * n_new[1]
                   + n_old[2] * n_new[2])
            if dot <= 0.0:
                return False
            old_len2 = (n_old[0] * n_old[0] + n_old[1] * n_old[1]
                        + n_old[2] * n_old[2])
            new_len2 = (n_new[0] * n_new[0] + n_new[1] * n_new[1]
                        + n_new[2] * n_new[2])
            if new_len2 < old_len2 * 1e-10:
                return False
        return True

    def _collapse_keeps_connectivity(self, keep, remove):
        """True if collapsing `remove` into `keep` leaves the star's internal
        connectivity unchanged.

        The star (all faces incident to either endpoint) is the only region
        whose topology can change. We compare the component partition of its
        surviving vertices computed from the star before versus from the same
        faces after the collapse's rewrite; any difference means the collapse
        would tear the mesh apart and is rejected.
        """
        star_faces = set(self.vadj[keep]) | set(self.vadj[remove])
        shared = self.vadj[keep] & self.vadj[remove]
        if len(shared) != 2:
            return False
        star_verts = set()
        for fi in star_faces:
            star_verts.update(self.faces[fi])
        star_verts.discard(remove)

        def partition(new_star_faces):
            parent = {v: v for v in star_verts}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                ra = find(a)
                rb = find(b)
                if ra != rb:
                    parent[ra] = rb

            for f in new_star_faces:
                for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                    if a in star_verts and b in star_verts:
                        union(a, b)
            groups = {}
            for v in star_verts:
                groups.setdefault(find(v), []).append(v)
            return frozenset(
                frozenset(verts) for verts in groups.values())

        before = partition([self.faces[fi] for fi in star_faces])
        after_star = []
        for fi in star_faces:
            if fi in shared:
                continue
            f = self.faces[fi]
            if remove in f:
                after_star.append([keep if v == remove else v for v in f])
            else:
                after_star.append(f)
        after = partition(after_star)
        return before == after

    def _collapse(self, keep, remove, target_pos):
        self.verts[keep] = target_pos
        shared = self.vadj[keep] & self.vadj[remove]
        for fi in list(self.vadj[remove]):
            if fi in shared:
                continue
            f = self.faces[fi]
            f[:] = [keep if v == remove else v for v in f]
            self.vadj[keep].add(fi)
        for fi in shared:
            for vi in self.faces[fi]:
                if vi != keep and vi != remove:
                    self.vadj[vi].discard(fi)
            self.faces[fi] = None
            self.alive[fi] = False
            self.active -= 1
        self.vadj[keep].difference_update(shared)
        self.vadj[remove] = set()
        self.vdead[remove] = True
        qa = self.vq[keep]
        qb = self.vq[remove]
        for k in range(10):
            qa[k] += qb[k]

    def run(self, target):
        cap = max(200000, len(self.faces) * 4)
        steps = 0
        while self.active > target and self.heap and steps < cap:
            _cost, _eid, lo, hi = heapq.heappop(self.heap)
            if self.vdead[lo] or self.vdead[hi]:
                continue
            if self._edge_cost(lo, hi) is None:
                continue
            _c, first_keep, px, py, pz = self._pair_optimum(lo, hi)
            target_pos = (px, py, pz)
            first_remove = hi if first_keep == lo else lo
            candidate = [(first_keep, first_remove)]
            if not self._collapse_valid(first_keep, first_remove, target_pos):
                candidate = [(first_remove, first_keep)]
                if not self._collapse_valid(first_remove, first_keep,
                                            target_pos):
                    continue
            keep, remove = candidate[0]
            if not self._collapse_keeps_connectivity(keep, remove):
                continue
            self._collapse(keep, remove, target_pos)
            steps += 1
            for w in self._neighbors(keep):
                self._push(keep, w)

    def result(self):
        alive_faces = []
        for fi, f in enumerate(self.faces):
            if self.alive[fi]:
                alive_faces.append((fi, f))
        used = set()
        for _fi, f in alive_faces:
            used.update(f)
        vmap = {}
        new_verts = []
        for old in sorted(used):
            vmap[old] = len(new_verts)
            new_verts.append(self.verts[old])
        new_faces = [[vmap[v] for v in f] for _fi, f in alive_faces]
        new_colors = [self.colors[fi] for fi, _f in alive_faces]
        return {"vertices": new_verts, "faces": new_faces,
                "face_colors": new_colors}


def simplify_mesh(vertices, faces, face_colors, ratio=0.2, min_faces=100):
    """QEM edge-collapse simplification.

    Returns {"vertices": [...], "faces": [...], "face_colors": [...]} in the
    same shape as MeshBuffer.to_mesh_data(). Small or already-cheap meshes are
    returned unchanged.
    """
    vertex_list = list(vertices)
    face_list = list(faces)
    color_list = list(face_colors)
    n = len(face_list)
    if n <= min_faces or ratio >= 1.0:
        return {"vertices": vertex_list, "faces": face_list,
                "face_colors": color_list}
    target = max(min_faces, int(n * ratio))
    if target >= n:
        return {"vertices": vertex_list, "faces": face_list,
                "face_colors": color_list}
    decimator = _Decimator(vertex_list, face_list, color_list)
    decimator.run(target)
    return decimator.result()