"""3D turtle — port of PlantStudio's KfTurtle drawing into a MeshBuffer.

Matches the original API: matrix stack, push/pop, rotateX/Y/Z (256-degree
units), moveInMillimeters, and drawing primitives (line -> pipe,
polygon -> triangles). The drawingSurface is replaced by a MeshBuffer.
"""

from .matrix3d import KfMatrix, KfPoint3D
from .mesh_buffer import MeshBuffer, PIPE_FACES


class MeshTurtle:
    def __init__(self, mesh_buffer=None):
        self.mesh_buffer = mesh_buffer if mesh_buffer is not None else MeshBuffer()
        self.matrixStack = []
        self.currentMatrix = KfMatrix()
        self.currentMatrix.initializeAsUnitMatrix()
        self.matrixStack.append(self.currentMatrix)
        self.numMatrixesUsed = 1
        self.scale_pixelsPerMm = 1.0
        self.currentColor = (100, 200, 100)
        self.currentLineWidth = 1.0
        self.lineDivisions = 3
        self._stroke_counter = 0

    def reset(self):
        self.matrixStack = []
        self.currentMatrix = KfMatrix()
        self.currentMatrix.initializeAsUnitMatrix()
        self.matrixStack.append(self.currentMatrix)
        self.numMatrixesUsed = 1
        self.scale_pixelsPerMm = 1.0
        self._stroke_counter = 0

    def next_stroke_id(self):
        """Return a stable id for one logical stem/pipe draw call."""
        stroke_id = self._stroke_counter
        self._stroke_counter += 1
        return stroke_id

    # ── matrix stack ──

    def push(self):
        self.currentMatrix = self.currentMatrix.deepCopy()
        self.matrixStack.append(self.currentMatrix)
        self.numMatrixesUsed += 1

    def pop(self):
        if self.numMatrixesUsed > 1:
            self.matrixStack.pop()
            self.numMatrixesUsed -= 1
        self.currentMatrix = self.matrixStack[-1]

    def stackSize(self):
        return self.numMatrixesUsed

    # ── positioning ──

    def xyz(self, x, y, z):
        self.currentMatrix.position.x = x
        self.currentMatrix.position.y = y
        self.currentMatrix.position.z = z

    def moveInMillimeters(self, mm):
        self.currentMatrix.move(mm * self.scale_pixelsPerMm)

    def moveInMillimetersAndRecord(self, mm):
        self.currentMatrix.move(mm * self.scale_pixelsPerMm)

    def moveInPixels(self, pixels):
        self.currentMatrix.move(pixels)

    def position(self):
        p = self.currentMatrix.position
        return KfPoint3D(p.x, p.y, p.z)

    def setScale_pixelsPerMm(self, s):
        self.scale_pixelsPerMm = s

    def setLineColor(self, color):
        self.currentColor = tuple(color)

    def setLineWidth(self, width):
        self.currentLineWidth = width

    # ── rotation (256-degree units) ──

    def rotateX(self, angle):
        self.currentMatrix.rotateX(angle)

    def rotateY(self, angle):
        self.currentMatrix.rotateY(angle)

    def rotateZ(self, angle):
        self.currentMatrix.rotateZ(angle)

    # ── drawing ──

    def ring_basis(self):
        """Cross-section basis (px,py,pz, qx,qy,qz) from the turtle's local
        Y/Z frame, perpendicular to the current forward direction."""
        m = self.currentMatrix
        return (m.a1, m.b1, m.c1, m.a2, m.b2, m.c2)

    def drawInMillimeters(self, mm, partID=0, cap_start=True, cap_end=True,
                          segment_index=None, segment_count=None, stroke_id=None):
        """Draw a line segment of the current width as a pipe."""
        start = self.position()
        self.currentMatrix.move(mm * self.scale_pixelsPerMm)
        end = self.position()
        radius = self.currentLineWidth * self.scale_pixelsPerMm * 0.5
        self.mesh_buffer.add_pipe(
            (start.x, start.y, start.z),
            (end.x, end.y, end.z),
            radius, radius, PIPE_FACES, self.currentColor,
            cap_start=cap_start, cap_end=cap_end, part_id=partID,
            segment_index=segment_index, segment_count=segment_count,
            stroke_id=stroke_id)
        return None

    def drawPipe(self, start, end, radiusStart, radiusEnd, faces, color,
                 basis_start=None, basis_end=None, cap_start=True, cap_end=True,
                 part_id=None, segment_index=None, segment_count=None,
                 stroke_id=None):
        self.mesh_buffer.add_pipe(
            (start.x, start.y, start.z),
            (end.x, end.y, end.z),
            radiusStart, radiusEnd, faces, color,
            basis_start=basis_start, basis_end=basis_end,
            cap_start=cap_start, cap_end=cap_end, part_id=part_id,
            segment_index=segment_index, segment_count=segment_count,
            stroke_id=stroke_id)

    def drawPolygon(self, points, color):
        """Triangulate a polygon (list of KfPoint3D) into the buffer."""
        pts = []
        for p in points:
            tp = p.copy()
            # convert to meters BEFORE transform: matrix position is in meters
            tp.x *= self.scale_pixelsPerMm
            tp.y *= self.scale_pixelsPerMm
            tp.z *= self.scale_pixelsPerMm
            self.currentMatrix.transform(tp)
            pts.append((tp.x, tp.y, tp.z))
        if len(pts) < 3:
            return
        # fan triangulation
        for i in range(1, len(pts) - 1):
            self.mesh_buffer.add_triangle(pts[0], pts[i], pts[i + 1], color)

    def drawTriangleSet(self, tdo_points, triangles, scale, color, part_id=None,
                         part_key=None, lifecycle_stage=None, semantic_id=None):
        """Draw a TDO mesh (points + 1-based triangle indices) transformed.

        Points are in mm × scale; the matrix position is in meters
        (moveInMillimeters applies scale_pixelsPerMm). Convert to meters
        BEFORE the transform so rotation doesn't amplify ~1000x.
        """
        self.mesh_buffer.triangle_set_records.append({
            "scale": float(scale),
            "part_id": part_id,
            "part_key": part_key,
            "lifecycle_stage": lifecycle_stage,
            "semantic_id": semantic_id,
            "points": len(tdo_points),
            "triangles": len(triangles),
        })
        transformed = []
        for p in tdo_points:
            tp = KfPoint3D(p[0] * scale * self.scale_pixelsPerMm,
                           p[1] * scale * self.scale_pixelsPerMm,
                           p[2] * scale * self.scale_pixelsPerMm)
            self.currentMatrix.transform(tp)
            transformed.append((tp.x, tp.y, tp.z))
        for (i, j, k) in triangles:
            self.mesh_buffer.add_triangle(transformed[i - 1], transformed[j - 1],
                                          transformed[k - 1], color)
