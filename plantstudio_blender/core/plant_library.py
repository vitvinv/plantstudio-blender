"""Species library: load .pla files, group by category, list species."""

import os
import glob
from .pla_parser import parse_pla_file


class SpeciesLibrary:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.species = []
        self._by_name = {}
        self.categories = {}  # category name (pla file basename) -> [species]
        self.load()

    def load(self):
        self.species = []
        self._by_name = {}
        self.categories = {}
        if not os.path.isdir(self.data_dir):
            raise FileNotFoundError(
                f"cannot load species library: data directory "
                f"'{self.data_dir}' does not exist")
        for path in sorted(glob.glob(os.path.join(self.data_dir, "*.pla"))):
            category = os.path.splitext(os.path.basename(path))[0]
            try:
                species = parse_pla_file(path)
                self.categories[category] = species
                for s in species:
                    s.category = category
                    self.species.append(s)
                    self._by_name[s.name] = s
            except Exception as e:
                raise RuntimeError(
                    f"failed to parse species file '{path}' "
                    f"(category '{category}'): {e}") from e

    def names(self):
        return [s.name for s in self.species]

    def names_by_category(self):
        """Return {category: [species names]}."""
        return {cat: [s.name for s in sps] for cat, sps in self.categories.items()}

    def get(self, name):
        return self._by_name.get(name)

    def __len__(self):
        return len(self.species)

    def __repr__(self):
        return f"SpeciesLibrary({len(self.species)} species, {len(self.categories)} categories)"
