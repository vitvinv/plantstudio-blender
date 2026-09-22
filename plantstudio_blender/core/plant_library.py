"""Species library: load .pla files, group by category, list species."""

import os
import glob
from .pla_parser import parse_pla_file
from .tdo_parser import Tdo


def iter_embedded_tdos(params):
    """Yield every Tdo embedded anywhere in a species' params.

    Species .pla files carry inline 'start 3D object' blocks; the parser
    stores them as Tdo instances directly on the params (not as library
    name strings). Walk the params structure and collect them so the UI
    can offer the species' own object names and the drawing library can
    resolve them by name as a fallback.
    """
    seen = set()

    def walk(obj, depth):
        if obj is None or depth > 6 or id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, Tdo):
            if obj.name:
                yield obj
            return
        if isinstance(obj, dict):
            for value in list(obj.values()):
                yield from walk(value, depth + 1)
            return
        d = getattr(obj, "__dict__", None)
        if d:
            for value in list(d.values()):
                yield from walk(value, depth + 1)

    yield from walk(params, 0)


class SpeciesLibrary:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.species = []
        self._by_name = {}
        self.categories = {}  # category name (pla file basename) -> [species]
        self.embedded_tdos = {}  # TDO name -> embedded Tdo (first species wins)
        self.load()

    def load(self):
        self.species = []
        self._by_name = {}
        self.categories = {}
        self.embedded_tdos = {}
        if not os.path.isdir(self.data_dir):
            raise FileNotFoundError(
                f"cannot load species library: data directory "
                f"'{self.data_dir}' does not exist")
        for path in sorted(glob.glob(os.path.join(self.data_dir, "*.pla"))):
            category = os.path.splitext(os.path.basename(path))[0]
            try:
                species = parse_pla_file(path)
                # normalize each species so params read the same snake_case
                # attributes whether they come from defaults or a .pla
                from .normalize import normalize_params

                for s in species:
                    normalize_params(s.params)
                self.categories[category] = species
                for s in species:
                    s.category = category
                    self.species.append(s)
                    self._by_name[s.name] = s
                    for tdo in iter_embedded_tdos(s.params):
                        self.embedded_tdos.setdefault(tdo.name, tdo)
            except Exception as e:
                raise RuntimeError(
                    f"failed to parse species file '{path}' "
                    f"(category '{category}'): {e}") from e

    def names(self):
        return [s.name for s in self.species]

    def names_by_category(self):
        """Return {category: [species names]}."""
        return {cat: [s.name for s in sps] for cat, sps in self.categories.items()}

    def embedded_tdo_names(self):
        """Names of species-embedded 3D objects (may exceed library names)."""
        return list(self.embedded_tdos.keys())

    def get(self, name):
        return self._by_name.get(name)

    def __len__(self):
        return len(self.species)

    def __repr__(self):
        return f"SpeciesLibrary({len(self.species)} species, {len(self.categories)} categories)"
