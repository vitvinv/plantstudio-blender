"""Parse PlantStudio .tdo 3D object files.

Format (text):
    Name=Tutorial leaf
      Point=0 0 0
      Triangle=1 2 3
"""


class AssetError(Exception):
    """Raised when a required asset (TDO / 3D object) cannot be loaded.

    The message names the exact asset and the reason it failed, so
    missing/broken references surface instead of silently falling
    back to a primitive placeholder.
    """


class Tdo:
    def __init__(self, name, points, triangles):
        self.name = name
        self.points = points          # list of (x, y, z)
        self.triangles = triangles    # list of (i, j, k) 1-based indices

    def __repr__(self):
        return f"Tdo({self.name!r}, {len(self.points)} pts, {len(self.triangles)} tris)"


def parse_tdo_file(path):
    """Parse a .tdo file into a list of Tdo objects."""
    tdos = []
    current = None
    with open(path, encoding="latin-1") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("Name="):
                current = Tdo(line[len("Name="):].strip(), [], [])
                tdos.append(current)
            elif line.startswith("Point=") and current is not None:
                vals = line[len("Point="):].split()
                current.points.append((float(vals[0]), float(vals[1]), float(vals[2])))
            elif line.startswith("Triangle=") and current is not None:
                vals = line[len("Triangle="):].split()
                current.triangles.append((int(vals[0]), int(vals[1]), int(vals[2])))
    return tdos


def parse_tdo_text(text):
    """Parse .tdo content from a string (used for embedded TDOs in .pla)."""
    tdos = []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Name="):
            current = Tdo(line[len("Name="):].strip(), [], [])
            tdos.append(current)
        elif line.startswith("Point=") and current is not None:
            vals = line[len("Point="):].split()
            current.points.append((float(vals[0]), float(vals[1]), float(vals[2])))
        elif line.startswith("Triangle=") and current is not None:
            vals = line[len("Triangle="):].split()
            current.triangles.append((int(vals[0]), int(vals[1]), int(vals[2])))
    return tdos


def parse_tdo_compact(text):
    """Parse the original PlantStudio inline TDO format.

    'N[name],P[x y z],P[x y z],T[i j k],T[i j k],...' — this is how
    parameters.tab / umakepm.py store the default 3D objects. Returns a
    Tdo (or None if the text is not in this format).
    """
    raw = str(text).strip()
    if not raw or not raw[0].isalpha():
        return None
    tdo = None
    for tok in raw.split(","):
        tok = tok.strip()
        if len(tok) < 2:
            continue
        body = tok[2:-1]
        if tok[0] == "N":
            tdo = Tdo(body, [], [])
        elif tok[0] == "P" and tdo is not None:
            vals = body.split()
            if len(vals) >= 3:
                tdo.points.append((float(vals[0]), float(vals[1]), float(vals[2])))
        elif tok[0] == "T" and tdo is not None:
            vals = body.split()
            if len(vals) >= 3:
                tdo.triangles.append((int(vals[0]), int(vals[1]), int(vals[2])))
    return tdo


class TdoLibrary:
    """Named 3D object library loaded from a .tdo file."""

    def __init__(self, tdos=None):
        self._by_name = {}
        for t in (tdos or []):
            self._by_name[t.name] = t

    def get(self, name):
        return self._by_name.get(name)

    def require(self, name, owner=None):
        """Return the named TDO or raise AssetError naming it.

        owner: where the reference came from (e.g. 'species gilia /
        pLeaf.leafTdoParams.object3D'), included in the error message.
        """
        if name is None:
            raise AssetError(
                f"cannot load 3D object: reference is None"
                + (f" (referenced by {owner})" if owner else ""))
        result = self._by_name.get(name)
        if result is None:
            raise AssetError(
                f"3D object '{name}' not found in the TDO library"
                + (f" (referenced by {owner})" if owner else "")
                + f"; library has {len(self._by_name)} objects")
        return result

    def names(self):
        return list(self._by_name.keys())

    def __len__(self):
        return len(self._by_name)

    @classmethod
    def from_file(cls, path):
        return cls(parse_tdo_file(path))
