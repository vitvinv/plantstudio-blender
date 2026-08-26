"""3D matrix and point — port of PlantStudio's u3dsupport KfMatrix/KfPoint3D.

Angles are in 256-degree turtle units (as in the original).
Uses exact trig instead of the cached tables (same values, deterministic).
"""

import math


def _trig(angle):
    """cos/sin for an angle in 256-degree units."""
    rad = angle * 2.0 * math.pi / 256.0
    return math.cos(rad), math.sin(rad)


class KfPoint3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def copy(self):
        return KfPoint3D(self.x, self.y, self.z)

    def __repr__(self):
        return f"KfPoint3D({self.x:.3f},{self.y:.3f},{self.z:.3f})"


class KfMatrix:
    def __init__(self):
        self.a0 = 1.0
        self.a1 = 0.0
        self.a2 = 0.0
        self.b0 = 0.0
        self.b1 = 1.0
        self.b2 = 0.0
        self.c0 = 0.0
        self.c1 = 0.0
        self.c2 = 1.0
        self.position = KfPoint3D()

    def initializeAsUnitMatrix(self):
        self.a0, self.a1, self.a2 = 1.0, 0.0, 0.0
        self.b0, self.b1, self.b2 = 0.0, 1.0, 0.0
        self.c0, self.c1, self.c2 = 0.0, 0.0, 1.0
        self.position.x = self.position.y = self.position.z = 0.0

    def deepCopy(self):
        m = KfMatrix()
        m.position.x, m.position.y, m.position.z = self.position.x, self.position.y, self.position.z
        m.a0, m.a1, m.a2 = self.a0, self.a1, self.a2
        m.b0, m.b1, m.b2 = self.b0, self.b1, self.b2
        m.c0, m.c1, m.c2 = self.c0, self.c1, self.c2
        return m

    def move(self, distance):
        self.position.x += distance * self.a0
        self.position.y += distance * self.b0
        self.position.z += distance * self.c0

    def transform(self, p):
        x, y, z = p.x, p.y, p.z
        p.x = x * self.a0 + y * self.a1 + z * self.a2 + self.position.x
        p.y = x * self.b0 + y * self.b1 + z * self.b2 + self.position.y
        p.z = x * self.c0 + y * self.c1 + z * self.c2 + self.position.z

    def rotateX(self, angle):
        cosA, sinA = _trig(angle)
        t1 = (self.a1 * cosA) - (self.a2 * sinA)
        self.a2 = (self.a1 * sinA) + (self.a2 * cosA)
        self.a1 = t1
        t1 = (self.b1 * cosA) - (self.b2 * sinA)
        self.b2 = (self.b1 * sinA) + (self.b2 * cosA)
        self.b1 = t1
        t1 = (self.c1 * cosA) - (self.c2 * sinA)
        self.c2 = (self.c1 * sinA) + (self.c2 * cosA)
        self.c1 = t1

    def rotateY(self, angle):
        cosA, sinA = _trig(angle)
        t0 = (self.a0 * cosA) + (self.a2 * sinA)
        self.a2 = (self.a2 * cosA) - (self.a0 * sinA)
        self.a0 = t0
        t0 = (self.b0 * cosA) + (self.b2 * sinA)
        self.b2 = (self.b2 * cosA) - (self.b0 * sinA)
        self.b0 = t0
        t0 = (self.c0 * cosA) + (self.c2 * sinA)
        self.c2 = (self.c2 * cosA) - (self.c0 * sinA)
        self.c0 = t0

    def rotateZ(self, angle):
        cosA, sinA = _trig(angle)
        t0 = (self.a0 * cosA) - (self.a1 * sinA)
        self.a1 = (self.a0 * sinA) + (self.a1 * cosA)
        self.a0 = t0
        t0 = (self.b0 * cosA) - (self.b1 * sinA)
        self.b1 = (self.b0 * sinA) + (self.b1 * cosA)
        self.b0 = t0
        t0 = (self.c0 * cosA) - (self.c1 * sinA)
        self.c1 = (self.c0 * sinA) + (self.c1 * cosA)
        self.c0 = t0
