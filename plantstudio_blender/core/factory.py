"""Plant factory — build a simulation-ready PdPlant from a parsed species."""

import os
from .pla_parser import PlantSpecies
from .normalize import normalize_params
from .plant import PdPlant
from .tdo_parser import TdoLibrary

DEFAULT_TDO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "data", "3D object library.tdo")


def create_plant(species, seed=None, maxPartsPerPlant=20000, tdo_library=None):
    """
    Build a PdPlant from a PlantSpecies, a named params wrapper, or raw params.
    """
    if isinstance(species, PlantSpecies):
        params = species.params
        name = species.name
    elif hasattr(species, 'params') and hasattr(species, 'name'):
        params = species.params
        name = species.name
    else:
        params = species
        name = getattr(params, "name", "plant")
    normalize_params(params)
    plant = PdPlant(params, seed=seed, maxPartsPerPlant=maxPartsPerPlant)
    plant.name = name
    if tdo_library is not None:
        if isinstance(tdo_library, str):
            tdo_library = TdoLibrary.from_file(tdo_library)
        plant.tdoLibrary = tdo_library
    return plant


def grow_species(species, day, seed=None, maxPartsPerPlant=20000, tdo_library=None):
    """Convenience: create plant and grow to a day. Returns the PdPlant."""
    plant = create_plant(species, seed=seed, maxPartsPerPlant=maxPartsPerPlant,
                         tdo_library=tdo_library)
    plant.growTo(day)
    return plant
