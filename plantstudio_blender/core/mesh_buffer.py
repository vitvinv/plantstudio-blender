"""Mesh buffer — accumulates triangles + per-face colors for a plant."""

import math

# Radial quads per pipe. 3 gives a triangular cross-section (cheap); raise for
# close-up/hero renders. add_pipe clamps to >= 3.
PIPE_FACES = 3


class MeshBuffer:
    def __init__(self):
        self.vertices = []   # list of (x, y, z)
        self.faces = []      # list of [i, j, k]
        self.face_colors = []  # list of (r, g, b) 0-255 per face
        # Diagnostic records are deliberately lightweight and remain available
        # to the headless audit without affecting exported mesh data.
        self.pipe_records = []
        self.triangle_set_records = []
        # Semantic records identify plant parts independently of mesh topology.
        # They are diagnostic only and do not affect exported geometry.
        self.semantic_records = []
        self._index = {}

    def clear(self):
        self.vertices = []
        self.faces = []
        self.face_colors = []
        self.pipe_records = []
        self.triangle_set_records = []
        # Semantic records identify plant parts independently of mesh topology.
        # They are diagnostic only and do not affect exported geometry.
        self.semantic_records = []
        self._index = {}

    def add_point(self, x, y, z, color):
        """Add a vertex (deduplicated) and return its index."""
        key = (round(x, 6), round(y, 6), round(z, 6))
        idx = self._index.get(key)
        if idx is None:
            idx = len(self.vertices)
            self.vertices.append((float(x), float(y), float(z)))
            self._index[key] = idx
        return idx

    def add_triangle(self, p0, p1, p2, color):
        i0 = self.add_point(p0[0], p0[1], p0[2], color)
        i1 = self.add_point(p1[0], p1[1], p1[2], color)
        i2 = self.add_point(p2[0], p2[1], p2[2], color)
        if i0 == i1 or i1 == i2 or i0 == i2:
            return
        self.faces.append([i0, i1, i2])
        self.face_colors.append(tuple(color))

    def add_quad(self, p0, p1, p2, p3, color):
        self.add_triangle(p0, p1, p2, color)
        self.add_triangle(p0, p2, p3, color)

    @staticmethod
    def _perpendicular_basis(dx, dy, dz):
        """Unit perpendicular pair (px,py,pz, qx,qy,qz) spanning the ring plane
        of a pipe whose axis runs along (dx,dy,dz)."""
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        ux, uy, uz = dx / length, dy / length, dz / length
        # build a perpendicular frame
        ref = (0.0, 1.0, 0.0) if abs(uy) < 0.9 else (1.0, 0.0, 0.0)
        px = uy * ref[2] - uz * ref[1]
        py = uz * ref[0] - ux * ref[2]
        pz = ux * ref[1] - uy * ref[0]
        pl = math.sqrt(px * px + py * py + pz * pz) or 1.0
        px, py, pz = px / pl, py / pl, pz / pl
        qx = uy * pz - uz * py
        qy = uz * px - ux * pz
        qz = ux * py - uy * px
        return (px, py, pz, qx, qy, qz)

    def _ring(self, center, radius, n, basis):
        """Ring of n vertices around center at radius, using the given basis."""
        px, py, pz, qx, qy, qz = basis
        pts = []
        for i in range(n):
            ang = i * 2.0 * math.pi / n
            ca, sa = math.cos(ang), math.sin(ang)
            rx = ca * px + sa * qx
            ry = ca * py + sa * qy
            rz = ca * pz + sa * qz
            pts.append((center[0] + rx * radius,
                        center[1] + ry * radius,
                        center[2] + rz * radius))
        return pts

    def add_pipe(self, center_start, center_end, radius_start, radius_end, faces, color,
                 basis_start=None, basis_end=None, cap_start=True, cap_end=True,
                 part_id=None, segment_index=None, segment_count=None,
                 stroke_id=None):
        """Cylinder/cone between two centers. faces = number of side quads.

        basis_start/basis_end: optional (px,py,pz, qx,qy,qz) ring orientations.
        Passing a shared basis for the end ring of one pipe and the start ring of
        the next lets consecutive pipes share (weld) their joint vertices.
        """
        if radius_start <= 0 and radius_end <= 0:
            return
        n = max(3, faces)
        self.pipe_records.append({
            "start": tuple(float(v) for v in center_start),
            "end": tuple(float(v) for v in center_end),
            "radius_start": float(radius_start),
            "radius_end": float(radius_end),
            "faces": n,
            "part_id": part_id,
            "segment_index": segment_index,
            "segment_count": segment_count,
            "stroke_id": stroke_id,
            "cap_start": bool(cap_start),
            "cap_end": bool(cap_end),
        })
        dx = center_end[0] - center_start[0]
        dy = center_end[1] - center_start[1]
        dz = center_end[2] - center_start[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-9:
            return
        if basis_start is None:
            basis = self._perpendicular_basis(dx, dy, dz)
            if basis_end is None:
                basis_end = basis
            basis_start = basis
        elif basis_end is None:
            basis_end = self._perpendicular_basis(dx, dy, dz)
        ring_start = self._ring(center_start, radius_start, n, basis_start)
        ring_end = self._ring(center_end, radius_end, n, basis_end)
        for i in range(n):
            j = (i + 1) % n
            self.add_quad(ring_start[i], ring_start[j], ring_end[j], ring_end[i], color)
        # end caps (only on open tips; interior joint rings are welded/shared)
        if cap_start and radius_start > 0.001:
            cx, cy, cz = center_start
            for i in range(1, n - 1):
                self.add_triangle((cx, cy, cz), ring_start[i], ring_start[i + 1], color)
        if cap_end and radius_end > 0.001:
            cx, cy, cz = center_end
            for i in range(1, n - 1):
                self.add_triangle((cx, cy, cz), ring_end[i + 1], ring_end[i], color)

    def to_mesh_data(self):
        """Return {vertices, faces, face_colors} for Blender."""
        return {
            "vertices": self.vertices,
            "faces": self.faces,
            "face_colors": self.face_colors,
        }

    def stats(self):
        return len(self.vertices), len(self.faces)
