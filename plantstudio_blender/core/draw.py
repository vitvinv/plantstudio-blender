"""Part drawing — ports the PlantStudio part draw() methods to the MeshTurtle.

Each part draws itself into the turtle's mesh buffer:
- internode: stem pipe (tapered, curved segments)
- leaf: petiole pipe + leaf TDO (or compound leaflets)
- meristem/inflorescence/flower: TDO objects (buds, petals)
"""

from . import math3d as umath
from .meristem import (kDirectionLeft, kDirectionRight, kArrangementOpposite,
                       kActivityDraw)
from .traverser import PdTraverser
from .mesh_buffer import PIPE_FACES

kDontTaper = 0
kUseAmendment = 1

# plant part export indices (used for material naming)
kExportPartInternode = 1
kExportPartLeaf = 2
kExportPartLeafStipule = 3
kExportPartPetiole = 4
kExportPartMeristem = 5
kExportPartRootTop = 6
kExportPartInflorescence = 7
kExportPartFlower = 8
kExportPartFruit = 9

PART_NAMES = {
    kExportPartInternode: "internode",
    kExportPartLeaf: "leaf",
    kExportPartLeafStipule: "stipule",
    kExportPartPetiole: "petiole",
    kExportPartMeristem: "meristem",
    kExportPartRootTop: "root",
    kExportPartInflorescence: "inflorescence",
    kExportPartFlower: "flower",
    kExportPartFruit: "fruit",
}


def _gp(obj, name, default=0.0):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def require_color(color, owner):
    """Return the faceColor or raise AssetError naming the missing asset."""
    from .tdo_parser import AssetError
    if color is None:
        raise AssetError(
            f"missing faceColor for {owner} — the .pla file does not "
            f"define a face color for this 3D object")
    return color


def resolve_tdo(plant, tdo, owner=None):
    """Resolve a TDO reference (Tdo object or name string) via the library.

    Raises AssetError for missing/broken references — no silent fallback
    to a primitive placeholder. owner names where the reference came from.
    """
    from .tdo_parser import AssetError
    if tdo is None:
        raise AssetError(
            f"cannot load 3D object: reference is None"
            + (f" (referenced by {owner})" if owner else ""))
    if isinstance(tdo, str):
        lib = getattr(plant, "tdoLibrary", None)
        if lib is None:
            raise AssetError(
                f"cannot load 3D object '{tdo}': plant has no TDO library attached"
                + (f" (referenced by {owner})" if owner else ""))
        return lib.require(tdo, owner=owner)
    return tdo


class DrawContext:
    """Holds state while drawing a plant."""

    def __init__(self, turtle):
        self.turtle = turtle
        self.materials = {}  # name -> color


def draw_plant(plant, turtle):
    """Draw the whole plant into the turtle's mesh buffer."""
    plant.turtle = turtle
    if plant.firstPhytomer is not None:
        traverser = PdTraverser(plant)
        traverser.traverseWholePlant(kActivityDraw)
    plant.turtle = None


# ── internode drawing ──

def draw_internode(part):
    turtle = part.plant.turtle
    if turtle is None:
        return
    zAngle = part.internodeAngle
    if part.phytomerAttachedTo is not None:
        if part.phytomerAttachedTo.leftBranchPlantPart is part:
            zAngle = zAngle + part.plant.pMeristem.branchingAngle
        elif part.phytomerAttachedTo.rightBranchPlantPart is part:
            zAngle = zAngle + part.plant.pMeristem.branchingAngle
            turtle.rotateX(128)
    length = umath.max(0.0, part.propFullLength() *
                       part.plant.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm)
    width = umath.max(0.0, part.propFullWidth() *
                      part.plant.pInternode.widthAtOptimalFinalBiomassAndExpansion_mm)
    # Species with a 0 internode-length param (e.g. maiden grass) would draw
    # every node at the origin — leaves pile at the bottom. Fall back to a
    # fraction of the petiole length so the plant still has structure.
    if length <= 0 and not part.isFirstPhytomer:
        petiole = getattr(part.plant.pLeaf, "petioleLengthAtOptimalBiomass_mm", 30.0)
        if not petiole:
            petiole = 30.0
        length = petiole * 0.25 * umath.max(0.1, part.propFullLength())
    color = require_color(part.internodeColor,
                          f"species '{part.plant.name}' internode faceColor")
    _draw_stem_segment(part, length, width, zAngle, 0, color, kDontTaper,
                       kExportPartInternode)


def _draw_stem_segment(part, length, width, angleZ, angleY, color, taperIndex, dxfIndex,
                       cap_start=True, cap_end=True):
    turtle = part.plant.turtle
    if turtle is None or length <= 0:
        return
    pGeneral = part.plant.pGeneral
    lineDivisions = max(1, int(getattr(pGeneral, "lineDivisions", 3)))
    realAngleZ = angleZ
    realAngleY = angleY
    if lineDivisions > 1:
        turnPortionZ = realAngleZ / lineDivisions
        turnPortionY = realAngleY / lineDivisions
        drawPortion = length / lineDivisions
    else:
        turnPortionZ = realAngleZ
        turnPortionY = realAngleY
        drawPortion = length
    startWidth = width
    if taperIndex > 0:
        endWidth = startWidth * taperIndex / 100.0
    else:
        endWidth = width

    turtle.setLineColor(color)
    # Reuse each division's exit ring as the next division's entry ring. This
    # keeps curved stems welded instead of creating duplicate internal shells.
    prev_basis = turtle.ring_basis()
    stroke_id = turtle.next_stroke_id()
    for i in range(lineDivisions):
        isLast = (i >= lineDivisions - 1)
        if not isLast:
            segmentTurnZ = turnPortionZ
            segmentTurnY = turnPortionY
            segmentLength = drawPortion
        else:
            segmentTurnZ = realAngleZ - (turnPortionZ * (lineDivisions - 1))
            segmentTurnY = realAngleY - (turnPortionY * (lineDivisions - 1))
            segmentLength = length - (drawPortion * (lineDivisions - 1))
        if taperIndex > 0 and lineDivisions > 1:
            startPortionWidth = startWidth - (i / (lineDivisions - 1)) * (startWidth - endWidth)
            if not isLast:
                endPortionWidth = startWidth - ((i + 1) / (lineDivisions - 1)) * (startWidth - endWidth)
            else:
                endPortionWidth = endWidth
        else:
            startPortionWidth = width
            endPortionWidth = width
        turtle.rotateY(segmentTurnY)
        turtle.rotateZ(segmentTurnZ)
        end_basis = turtle.ring_basis()
        start_basis = prev_basis
        prev_basis = end_basis
        # draw pipe for this segment
        start_pos = turtle.position()
        turtle.setLineWidth(startPortionWidth)
        turtle.moveInMillimeters(segmentLength)
        end_pos = turtle.position()
        turtle.drawPipe(start_pos, end_pos,
                        startPortionWidth * turtle.scale_pixelsPerMm * 0.5,
                        endPortionWidth * turtle.scale_pixelsPerMm * 0.5,
                        PIPE_FACES, color,
                        basis_start=start_basis, basis_end=end_basis,
                        cap_start=cap_start and (i == 0),
                        cap_end=cap_end and isLast,
                        part_id=dxfIndex,
                        segment_index=i, segment_count=lineDivisions,
                        stroke_id=stroke_id)


# ── leaf drawing ──

def _semantic_leaf_record(leaf):
    """Create a topology-independent diagnostic record for one leaf draw."""
    plant = leaf.plant
    turtle = getattr(plant, "turtle", None)
    if turtle is None or not hasattr(turtle, "mesh_buffer"):
        return None
    if not hasattr(leaf, "_semantic_id"):
        counter = getattr(plant, "_semantic_counter", 0) + 1
        plant._semantic_counter = counter
        leaf._semantic_id = f"leaf-{counter}"
    record = {
        "semantic_id": leaf._semantic_id,
        "kind": "seedling_leaf" if leaf.isSeedlingLeaf else "leaf",
        "status": "draw_started",
        "has_fallen_off": bool(leaf.hasFallenOff),
        "is_seedling": bool(leaf.isSeedlingLeaf),
    }
    turtle.mesh_buffer.semantic_records.append(record)
    return record


def _finish_semantic_leaf_record(leaf, record):
    if record is None:
        return
    turtle = getattr(leaf.plant, "turtle", None)
    records = getattr(getattr(turtle, "mesh_buffer", None), "triangle_set_records", [])
    emitted = any(
        item.get("semantic_id") == record["semantic_id"]
        and item.get("part_id") == kExportPartLeaf
        and item.get("scale", 0) > 0
        and item.get("triangles", 0) > 0
        for item in records
    )
    record["has_geometry"] = emitted
    record["status"] = "visible" if emitted else "suppressed_draw"


def draw_leaf(leaf, direction):
    record = _semantic_leaf_record(leaf)
    turtle = leaf.plant.turtle
    if turtle is None or leaf.hasFallenOff:
        if record is not None:
            record["status"] = "suppressed_fallen"
        return
    turtle.push()
    if direction == kDirectionRight:
        turtle.rotateX(128)
    pLeaf = leaf.plant.pLeaf
    propFullSize = umath.min(1.0, leaf.liveBiomass_pctMPB /
                             max(0.001, pLeaf.optimalBiomass_pctMPB))
    length = pLeaf.petioleLengthAtOptimalBiomass_mm * propFullSize
    if leaf.isSeedlingLeaf:
        length = length / 2
    width = pLeaf.petioleWidthAtOptimalBiomass_mm * propFullSize
    angle = pLeaf.petioleAngle
    petioleColor = require_color(pLeaf.petioleColor,
                                 f"species '{leaf.plant.name}' petioleColor")

    if leaf.isSeedlingLeaf:
        _draw_stem_segment(leaf, length, width, angle, 0, petioleColor,
                           pLeaf.petioleTaperIndex, kExportPartPetiole,
                           cap_start=False)
        st = getattr(leaf.plant.params, "seedlingTdoParams", None)
        seed_scale = getattr(st, "scaleAtFullSize", 0) or \
            getattr(leaf.plant.pSeedlingLeaf, "scaleAtFullSize", 20) or 20
        scale = propFullSize * (seed_scale / 100.0)
        _draw_leaf_tdo(leaf, scale)
    else:
        if getattr(pLeaf, "stipuleTdoParams", None) is not None and \
                getattr(leaf.plant.params.stipuleTdoParams, "scaleAtFullSize", 0) > 0:
            _draw_stipule(leaf)
        if pLeaf.compoundNumLeaflets <= 1:
            _draw_stem_segment(leaf, length, width, angle, 0, petioleColor,
                               pLeaf.petioleTaperIndex, kExportPartPetiole,
                               cap_start=False)
            _draw_leaflet(leaf, _leaf_scale(leaf))
        else:
            _draw_compound_leaf(leaf, length, width, angle, petioleColor)
    turtle.pop()
    _finish_semantic_leaf_record(leaf, record)


def _draw_leaf_tdo(leaf, scale):
    """Draw a seedling leaf: reuse the regular leaf TDO unless the species
    defines a specific seedling leaf object (params.seedlingTdoParams)."""
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    tdo = getattr(leaf.plant.params, "seedlingTdoParams", None)
    if tdo is None or tdo.object3D is None:
        tdo = leaf.plant.params.leafTdoParams
    if tdo is None or tdo.object3D is None:
        from .tdo_parser import AssetError
        raise AssetError(
            f"seedling leaf 3D object reference missing for species "
            f"'{leaf.plant.name}' (seedlingTdoParams.object3D "
            f"and pLeaf.leafTdoParams.object3D are both unset)")
    faceColor = require_color(tdo.faceColor,
                             f"species '{leaf.plant.name}' seedling leafTdoParams.faceColor")
    turtle.rotateX(_angle_with_sway(leaf, tdo.xRotationBeforeDraw))
    turtle.rotateY(_angle_with_sway(leaf, tdo.yRotationBeforeDraw))
    turtle.rotateZ(_angle_with_sway(leaf, tdo.zRotationBeforeDraw))
    turtle.rotateZ(-64)
    r_tdo = resolve_tdo(leaf.plant, tdo.object3D,
                        owner=f"species '{leaf.plant.name}' leafTdoParams.object3D")
    turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, faceColor,
                            part_id=kExportPartLeaf,
                            semantic_id=getattr(leaf, "_semantic_id", None))


def _draw_stipule(leaf):
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    pLeaf = leaf.plant.pLeaf
    tdoParams = leaf.plant.params.stipuleTdoParams
    turtle.push()
    turtle.rotateX(_angle_with_sway(leaf, tdoParams.xRotationBeforeDraw))
    turtle.rotateY(_angle_with_sway(leaf, tdoParams.yRotationBeforeDraw))
    turtle.rotateZ(_angle_with_sway(leaf, tdoParams.zRotationBeforeDraw))
    propFullSize = umath.min(1.0, leaf.liveBiomass_pctMPB /
                             max(0.001, pLeaf.optimalBiomass_pctMPB))
    scale = propFullSize * (tdoParams.scaleAtFullSize / 100.0)
    if tdoParams.object3D is not None:
        color = require_color(tdoParams.faceColor,
                              f"species '{leaf.plant.name}' stipuleTdoParams.faceColor")
        r_tdo = resolve_tdo(leaf.plant, tdoParams.object3D,
                            owner=f"species '{leaf.plant.name}' stipuleTdoParams.object3D")
        turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
    turtle.pop()


def _prop_full_size(leaf):
    pLeaf = leaf.plant.pLeaf
    return umath.min(1.0, leaf.liveBiomass_pctMPB /
                     max(0.001, pLeaf.optimalBiomass_pctMPB))


def _leaf_scale(leaf):
    """scale = propFullSize * leafTdoParams.scaleAtFullSize / 100 (original)."""
    from .tdo_parser import AssetError
    pfs = _prop_full_size(leaf)
    tdo = leaf.plant.params.leafTdoParams
    if tdo is None:
        raise AssetError(
            f"leaf TDO params missing for species '{leaf.plant.name}' "
            f"(pLeaf.leafTdoParams is None)")
    scale_at_full = tdo.scaleAtFullSize
    if not scale_at_full:
        raise AssetError(
            f"leaf TDO scale missing for species '{leaf.plant.name}' "
            f"(pLeaf.leafTdoParams.scaleAtFullSize is {scale_at_full!r})")
    return pfs * scale_at_full / 100.0


def _draw_leaflet(leaf, scale):
    """DrawLeafOrLeaflet port: TDO at scale with rotations + rotateZ(-64)."""
    from .tdo_parser import AssetError
    turtle = leaf.plant.turtle
    pLeaf = leaf.plant.pLeaf
    tdo = leaf.plant.params.leafTdoParams
    if tdo is None:
        raise AssetError(
            f"leaf TDO params missing for leaf on species "
            f"'{leaf.plant.name}' (pLeaf.leafTdoParams is None)")
    if tdo.object3D is None:
        raise AssetError(
            f"leaf 3D object reference is None for species "
            f"'{leaf.plant.name}' (pLeaf.leafTdoParams.object3D not set)")
    r_tdo = resolve_tdo(leaf.plant, tdo.object3D,
                        owner=f"species '{leaf.plant.name}' leafTdoParams.object3D")
    turtle.rotateX(_angle_with_sway(leaf, tdo.xRotationBeforeDraw))
    turtle.rotateY(_angle_with_sway(leaf, tdo.yRotationBeforeDraw))
    turtle.rotateZ(_angle_with_sway(leaf, tdo.zRotationBeforeDraw))
    turtle.rotateZ(-64)  # pull leaf up to plane of petiole
    faceColor = require_color(tdo.faceColor,
                              f"species '{leaf.plant.name}' leafTdoParams.faceColor")
    turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, faceColor,
                            part_id=kExportPartLeaf,
                            semantic_id=getattr(leaf, "_semantic_id", None))


def _draw_compound_leaf(leaf, length, width, angle, petioleColor):
    """Faithful port of drawCompoundLeafPinnate/Palmate (original uleaf.py)."""
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    pLeaf = leaf.plant.pLeaf
    numLeaflets = int(pLeaf.compoundNumLeaflets)
    if numLeaflets <= 1:
        return
    scale = _leaf_scale(leaf)
    pfs = _prop_full_size(leaf)
    rachis_ratio = getattr(pLeaf, "compoundRachisToPetioleRatio", 30.0)
    pinnate = int(getattr(pLeaf, "compoundPinnateOrPalmate", 0))
    rachis_len = pLeaf.petioleLengthAtOptimalBiomass_mm * pfs * rachis_ratio / 100.0
    rachis_wid = pLeaf.petioleWidthAtOptimalBiomass_mm * pfs

    def _bend_angle(count):
        """bendAngleForCompoundLeaf: curve the leaf as leaflets accumulate."""
        start = getattr(pLeaf, "compoundCurveAngleAtStart", 0.0) or 0.0
        full = getattr(pLeaf, "compoundCurveAngleAtFullSize", 4.0) or 4.0
        difference = abs(full - start)
        leaflet_effect = 0.75 + 0.25 * umath.safedivExcept(count, numLeaflets - 1, 0)
        pfs_this = umath.max(0.0, umath.min(1.0, (0.25 + 0.75 * pfs) * leaflet_effect))
        if full > start:
            return start + difference * pfs_this
        return start - difference * pfs_this

    if pinnate == 0:  # pinnate: rachis with alternating leaflets
        for i in range(numLeaflets, 0, -1):
            if i != 1:
                # draw the rachis segment to this leaflet
                bend = _bend_angle(i)
                _draw_stem_segment(leaf, rachis_len, rachis_wid, bend, 0,
                                   petioleColor, kDontTaper, kExportPartPetiole,
                                   cap_start=False)
            turtle.push()
            # petiole off the rachis: ±32°, alternating; terminal leaflet straight
            if i == 1:
                lf_angle = 0
            elif i % 2 == 1:
                lf_angle = 32
            else:
                lf_angle = -32
            _draw_stem_segment(leaf, scale * pLeaf.petioleLengthAtOptimalBiomass_mm * pfs,
                               scale * pLeaf.petioleWidthAtOptimalBiomass_mm * pfs,
                               0, lf_angle, petioleColor,
                               pLeaf.petioleTaperIndex, kExportPartPetiole,
                               cap_start=False)
            _draw_leaflet(leaf, scale)
            turtle.pop()
    else:  # palmate: leaflets radiate from a point
        angle_one = umath.safedivExcept(64, numLeaflets, 0)
        for i in range(numLeaflets, 0, -1):
            turtle.push()
            if i == 1:
                leaflet_angle = 0
            elif i % 2 == 1:
                leaflet_angle = angle_one * i * -1
            else:
                leaflet_angle = angle_one * i
            _draw_stem_segment(leaf, rachis_len, rachis_wid, 0, leaflet_angle,
                               petioleColor, kDontTaper, kExportPartPetiole,
                               cap_start=False)
            _draw_leaflet(leaf, scale)
            turtle.pop()


def _angle_with_sway(part, angle):
    """Add random sway to a draw angle (deterministic via plant RNG)."""
    rng = part.plant.randomNumberGenerator
    sway = getattr(part.plant.pGeneral, "randomSway", 0.0)
    if sway == 0:
        return angle
    return angle + (rng.zeroToOne() - 0.5) * 2.0 * sway * 256 / 360


# ── meristem / inflorescence TDO drawing ──

def draw_meristem(meristem):
    plant = meristem.plant
    turtle = plant.turtle
    if turtle is None or meristem.isApical:
        return
    bud = plant.pAxillaryBud
    if bud is None or bud.scaleAtFullSize == 0 or bud.object3D is None:
        return
    daysToFullSize = 5
    scale = (bud.scaleAtFullSize / 100.0) * umath.min(1.0, meristem.age / daysToFullSize)
    if scale <= 0:
        return
    numParts = 5
    color = require_color(bud.faceColor,
                          f"species '{plant.name}' pAxillaryBud.faceColor")
    for i in range(numParts):
        turtle.rotateX(256 / numParts)
        turtle.push()
        turtle.rotateZ(-64)
        turtle.rotateX(bud.xRotationBeforeDraw)
        turtle.rotateY(bud.yRotationBeforeDraw)
        turtle.rotateZ(bud.zRotationBeforeDraw)
        r_tdo = resolve_tdo(plant, bud.object3D)
        if r_tdo is not None:
            turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
        turtle.pop()


# ── inflorescence / flower drawing ──

# flower row order (matches the original kFirstPetals..kSepals layer loop)
_FLOWER_ROW_ORDER = ["kFirstPetals", "kSecondPetals", "kThirdPetals",
                     "kFourthPetals", "kFifthPetals", "kSepals"]

kDrawNoBud = 0
kDrawSingleTdoBud = 1
kDrawOpeningFlower = 2


def _flower_row(p, key):
    """Get a flower TDO row (TdoParamsCompat) from inflorescence params."""
    if not isinstance(p, dict):
        return None
    return p.get("tdoParams", {}).get(key)


def _prop_full_size_inflor(inflor, p):
    return umath.safedivExcept(inflor.liveBiomass_pctMPB,
                               _gp(p, "optimalBiomass_pctMPB", 1.0), 0)


def _all_flowers_drawn(inflor):
    return all(getattr(f, "hasBeenDrawn", False) for f in inflor.flowers)


def _length_or_width_at_age(inflor, p, starting, fraction):
    daysAll = _gp(p, "daysToAllFlowersCreated", 10)
    ageBounded = umath.min(daysAll, inflor.daysSinceStartedMakingFlowers)
    if daysAll != 0:
        return umath.safedivExcept(starting * ageBounded, daysAll, 0) * fraction
    return starting * ageBounded * fraction


def _row_color(row, plant, key):
    color = getattr(row, "faceColor", None)
    if color is None:
        from .tdo_parser import AssetError
        raise AssetError(
            f"flower row '{key}' for species '{plant.name}' has no faceColor "
            f"(pFlower tdoParams['{key}'].faceColor is None)")
    return color


def _draw_circle_of_tdos(part, tdo, color, pullBackAngle, scale, numParts,
                         partsArranged, open_, isFruit=False, part_id=None):
    """Faithful port of PdFlowerFruit.drawCircleOfTdos (ufruit.py).

    open_: petals are pulled up to the plane of the stalk (rotateY(32));
    isFruit: closed fruit sections align with rotateZ(-64) instead of the
    pull-back angle.
    """
    if scale <= 0.0:
        return
    turtle = part.plant.turtle
    if turtle is None:
        return
    turtle.push()
    if partsArranged and numParts > 0:
        turnPortion = 256 / numParts
        leftOverDegrees = 256 - turnPortion * numParts
        addition = umath.safedivExcept(leftOverDegrees, numParts, 0) \
            if leftOverDegrees > 0 else 0
        carryOver = 0
        for i in range(1, numParts + 1):
            addThisTime = int(addition + carryOver)
            carryOver = carryOver + addition - addThisTime
            if carryOver < 0:
                carryOver = 0
            turtle.rotateX(turnPortion + addThisTime)
            turtle.push()
            # aligns the object as stored in the file to how it draws on the plant
            turtle.rotateZ(-64)
            if open_:
                # pulls the petal up to the plane of the stalk (perpendicular)
                turtle.rotateY(32)
            turtle.rotateX(pullBackAngle)
            turtle.drawTriangleSet(
                tdo.points, tdo.triangles, scale, color,
                part_id=part_id,
                lifecycle_stage=getattr(part, "stage", None),
            )
            turtle.pop()
    else:
        turtle.push()
        if isFruit:
            turtle.rotateZ(-64)
        else:
            turtle.rotateZ(-pullBackAngle)
        turtle.drawTriangleSet(
            tdo.points, tdo.triangles, scale, color,
            part_id=part_id,
            lifecycle_stage=getattr(part, "stage", None),
        )
        turtle.pop()
    turtle.pop()


def draw_inflorescence(inflor):
    """Port of PdInflorescence.draw + drawApex/drawHead/drawBracts/
    drawPeduncle/drawFlower (uinflor.py)."""
    plant = inflor.plant
    turtle = plant.turtle
    if turtle is None:
        return
    p = plant.pInflor[inflor.gender]
    if not p or not inflor.flowers:
        return
    for flower in inflor.flowers:
        flower.hasBeenDrawn = False
    turtle.push()
    _draw_inflor_bracts(inflor, p)
    _draw_peduncle(inflor, p)
    if _gp(p, "isHead", False):
        _draw_head(inflor, p)
    else:
        _draw_apex(inflor, p, int(_gp(p, "numFlowersOnMainBranch", 1) or 1),
                   0, True)
    turtle.pop()


def _draw_inflor_bracts(inflor, p):
    """Port of drawBracts: radial circle of bract TDOs around the stalk."""
    turtle = inflor.plant.turtle
    bract = p.get("bractTdoParams") if isinstance(p, dict) else None
    if bract is None or _gp(bract, "scaleAtFullSize", 0.0) <= 0:
        return
    tdo = getattr(bract, "object3D", None)
    if tdo is None:
        return
    r_tdo = resolve_tdo(inflor.plant, tdo,
                        owner=f"species '{inflor.plant.name}' bractTdoParams.object3D")
    scale = (_gp(bract, "scaleAtFullSize", 0.0) / 100.0) * _prop_full_size_inflor(inflor, p)
    color = _row_color(bract, inflor.plant, "bractTdoParams")
    reps = max(1, int(_gp(bract, "repetitions", 1) or 1))
    radial = _gp(bract, "radiallyArranged", True)
    pull = _gp(bract, "pullBackAngle", 0.0) or 0.0
    turtle.push()
    turtle.rotateX(_angle_with_sway(inflor, _gp(bract, "xRotationBeforeDraw", 0.0)))
    turtle.rotateY(_angle_with_sway(inflor, _gp(bract, "yRotationBeforeDraw", 0.0)))
    turtle.rotateZ(_angle_with_sway(inflor, _gp(bract, "zRotationBeforeDraw", 0.0)))
    if radial:
        turn = 256 / reps
        for _ in range(reps):
            turtle.push()
            # aligns the object as stored in the file
            turtle.rotateY(-64)
            turtle.rotateX(64)
            turtle.rotateX(pull)
            turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
            turtle.pop()
            turtle.rotateX(turn)
    else:
        turtle.push()
        turtle.rotateY(-64)
        turtle.rotateX(64)
        turtle.rotateX(pull)
        turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
        turtle.pop()
    turtle.pop()


def _draw_peduncle(inflor, p):
    """Port of drawPeduncle: the inflorescence's main stalk segment."""
    turtle = inflor.plant.turtle
    zAngle = 0.0
    if inflor.phytomerAttachedTo is not None:
        if inflor.phytomerAttachedTo.leftBranchPlantPart is inflor:
            zAngle = _gp(p, "peduncleAngleFromVegetativeStem", 0.0)
        elif inflor.phytomerAttachedTo.rightBranchPlantPart is inflor:
            zAngle = _gp(p, "peduncleAngleFromVegetativeStem", 0.0)
            turtle.rotateX(128)
        elif inflor.isApical:
            zAngle = _gp(p, "apicalStalkAngleFromVegetativeStem", 0.0)
    propFullSize = _prop_full_size_inflor(inflor, p)
    if inflor.isApical:
        length = _length_or_width_at_age(inflor, p,
                                         _gp(p, "terminalStalkLength_mm", 0.0),
                                         propFullSize)
    else:
        length = _length_or_width_at_age(inflor, p,
                                         _gp(p, "peduncleLength_mm", 0.0),
                                         propFullSize)
    width = _length_or_width_at_age(inflor, p, _gp(p, "internodeWidth_mm", 0.0),
                                    propFullSize)
    color = _gp(p, "stalkColor", None)
    if color is None:
        from .tdo_parser import AssetError
        raise AssetError(
            f"inflorescence stalk color missing for species "
            f"'{inflor.plant.name}' (pInflor stalkColor is None)")
    _draw_stem_segment(inflor, length, width, zAngle, 0, color, kDontTaper,
                       kExportPartInternode)


def _draw_inflor_internode(inflor, p):
    """Port of drawInternode: stalk segment between successive flowers."""
    if _all_flowers_drawn(inflor):
        return
    if _gp(p, "internodeLength_mm", 0.0) == 0.0:
        return
    propFullSize = _prop_full_size_inflor(inflor, p)
    length = _length_or_width_at_age(inflor, p, _gp(p, "internodeLength_mm", 0.0),
                                     propFullSize)
    width = _length_or_width_at_age(inflor, p, _gp(p, "internodeWidth_mm", 0.0),
                                    propFullSize)
    zAngle = _angle_with_sway(inflor, _gp(p, "angleBetweenInternodes", 0.0))
    yAngle = _angle_with_sway(inflor, 0.0)
    color = _gp(p, "stalkColor", None)
    if color is None:
        from .tdo_parser import AssetError
        raise AssetError(
            f"inflorescence stalk color missing for species "
            f"'{inflor.plant.name}' (pInflor stalkColor is None)")
    _draw_stem_segment(inflor, length, width, zAngle, yAngle, color, kDontTaper,
                       kExportPartInternode)


def _draw_apex(inflor, p, internodeCount, flowerIndexOffset, mainBranch):
    """Port of drawApex: raceme/panicle — flowers on the main stem plus
    optional side branches."""
    turtle = inflor.plant.turtle
    if turtle is None:
        return
    numBranches = int(_gp(p, "numBranches", 0) or 0)
    flowersPerBranch = int(_gp(p, "numFlowersPerBranch", 1) or 1)
    flowersOnMain = int(_gp(p, "numFlowersOnMainBranch", 1) or 1)
    branchesDrawn = 0
    if internodeCount > 0:
        if mainBranch:
            turtle.push()
        if mainBranch:
            while branchesDrawn < numBranches:
                _draw_inflor_internode(inflor, p)
                branchesDrawn += 1
        i = internodeCount
        while i >= 1:
            if _gp(p, "flowersSpiralOnStem", False):
                turtle.rotateX(98)
            _draw_inflor_internode(inflor, p)
            turtle.push()
            _draw_inflor_flower(inflor, p, flowerIndexOffset + i)
            turtle.pop()
            i -= 1
        if mainBranch:
            turtle.pop()
    branchesDrawn = 0
    if mainBranch:
        while branchesDrawn < numBranches:
            if _gp(p, "flowersSpiralOnStem", False):
                turtle.rotateX(98)
            _draw_inflor_internode(inflor, p)
            _draw_axillary_bud(inflor, p, flowersPerBranch,
                               flowersOnMain + branchesDrawn * flowersPerBranch)
            branchesDrawn += 1
            if (not _gp(p, "branchesAreAlternate", False)) and branchesDrawn < numBranches:
                turtle.push()
                turtle.rotateX(128)
                _draw_axillary_bud(inflor, p, flowersPerBranch,
                                   flowersOnMain + branchesDrawn * flowersPerBranch)
                branchesDrawn += 1
                turtle.pop()


def _draw_axillary_bud(inflor, p, internodeCount, flowerIndexOffset):
    """Port of drawAxillaryBud: a side branch of the inflorescence."""
    if _all_flowers_drawn(inflor):
        return
    turtle = inflor.plant.turtle
    angle = _angle_with_sway(inflor, _gp(p, "branchAngle", 0.0))
    turtle.push()
    turtle.rotateZ(angle)
    _draw_apex(inflor, p, internodeCount, flowerIndexOffset, False)
    turtle.pop()


def _draw_inflor_flower(inflor, p, internodeCount):
    """Port of drawFlower: pedicel + the flower/fruit object itself."""
    if _all_flowers_drawn(inflor):
        return
    propFullSize = _prop_full_size_inflor(inflor, p)
    length = _length_or_width_at_age(inflor, p, _gp(p, "pedicelLength_mm", 0.0),
                                     propFullSize)
    width = _length_or_width_at_age(inflor, p, _gp(p, "internodeWidth_mm", 0.0),
                                    propFullSize)
    angle = _angle_with_sway(inflor, _gp(p, "pedicelAngle", 0.0))
    if _gp(p, "flowersDrawTopToBottom", False):
        flowerIndex = internodeCount
    else:
        flowerIndex = len(inflor.flowers) - internodeCount + 1
    color = _gp(p, "pedicelColor", None)
    if color is None:
        from .tdo_parser import AssetError
        raise AssetError(
            f"pedicel color missing for species '{inflor.plant.name}' "
            f"(pInflor pedicelColor is None)")
    _draw_stem_segment(inflor, length, width, angle, 0, color,
                       _gp(p, "pedicelTaperIndex", 100), kExportPartPetiole)
    if 0 <= flowerIndex - 1 < len(inflor.flowers):
        _draw_flower_fruit(inflor.flowers[flowerIndex - 1])


def _draw_head(inflor, p):
    """Port of drawHead: radial head (e.g. sunflower)."""
    turtle = inflor.plant.turtle
    turtle.rotateY(64)
    turtle.rotateZ(64)
    # give a little angle down to make it look more natural
    turtle.rotateY(32)
    if len(inflor.flowers) > 0:
        turnPortion = 256 / len(inflor.flowers)
        leftOverDegrees = 256 - turnPortion * len(inflor.flowers)
        addition = umath.safedivExcept(leftOverDegrees, len(inflor.flowers), 0) \
            if leftOverDegrees > 0 else 0
        carryOver = 0
        for i in range(len(inflor.flowers) - 1, -1, -1):
            addThisTime = int(addition + carryOver)
            carryOver = carryOver + addition - addThisTime
            if carryOver < 0:
                carryOver = 0
            turtle.rotateZ(turnPortion + addThisTime)
            turtle.push()
            _draw_inflor_flower(inflor, p, i + 1)
            turtle.pop()


def _draw_flower_fruit(flower):
    """Port of PdFlowerFruit.draw (ufruit.py): bud stage, open flower,
    or fruit when the flower has set fruit."""
    plant = flower.plant
    turtle = plant.turtle
    if turtle is None:
        return
    p = plant.pFlower[flower.gender]
    if not p:
        return
    flower.hasBeenDrawn = True
    # The flower's propFullSize is relative to the FLOWER's own optimal
    # biomass (pFlower.optimalBiomass_pctMPB), clamped to [0,1] like the
    # original — NOT the inflorescence's optimalBiomass.
    if getattr(flower, "stage", "bud") in ("unripe_fruit", "ripe_fruit"):
        fruit_params = getattr(plant.params, "pFruit", None)
        propFullSize = umath.min(1.0, umath.safedivExcept(
            flower.liveBiomass_pctMPB + flower.deadBiomass_pctMPB,
            _gp(fruit_params, "optimalBiomass_pctMPB", 1.0), 0))
    else:
        propFullSize = umath.min(1.0, umath.safedivExcept(
            flower.liveBiomass_pctMPB, _gp(p, "optimalBiomass_pctMPB", 1.0), 0))
    turtle.push()
    stage = getattr(flower, "stage", None)
    if stage is None:
        stage = "open" if flower.isOpen and not flower.hasSetFruit else "bud"
    if stage == "bud":
        budOption = int(_gp(p, "budDrawingOption", kDrawSingleTdoBud) or kDrawSingleTdoBud)
        if budOption == kDrawNoBud:
            pass
        elif budOption == kDrawSingleTdoBud:
            bud = _flower_row(p, "kBud")
            if bud is not None and _gp(bud, "scaleAtFullSize", 0.0) > 0:
                _draw_bud_row(flower, bud, propFullSize, "kBud")
        else:  # kDrawOpeningFlower
            _draw_open_flower(flower, p, propFullSize, True)
    elif stage in ("unripe_fruit", "ripe_fruit") or flower.hasSetFruit:
        draw_fruit(flower, plant)
    else:
        _draw_open_flower(flower, p, propFullSize, False)
    turtle.pop()


def _draw_bud_row(flower, row, propFullSize, key):
    """Draw a single TDO row as a closed circle (bud petals)."""
    turtle = flower.plant.turtle
    scale = (_gp(row, "scaleAtFullSize", 0.0) / 100.0) * propFullSize
    if scale <= 0:
        return
    tdo = getattr(row, "object3D", None)
    if tdo is None:
        return
    r_tdo = resolve_tdo(flower.plant, tdo,
                        owner=f"species '{flower.plant.name}' flower row '{key}' object3D")
    turtle.rotateX(_angle_with_sway(flower, _gp(row, "xRotationBeforeDraw", 0.0)))
    turtle.rotateY(_angle_with_sway(flower, _gp(row, "yRotationBeforeDraw", 0.0)))
    turtle.rotateZ(_angle_with_sway(flower, _gp(row, "zRotationBeforeDraw", 0.0)))
    _draw_circle_of_tdos(flower, r_tdo, _row_color(row, flower.plant, key),
                         _gp(row, "pullBackAngle", 0.0) or 0.0, scale,
                         max(1, int(_gp(row, "repetitions", 1) or 1)),
                         _gp(row, "radiallyArranged", True), False,
                         part_id=kExportPartFlower)


def _draw_open_flower(flower, p, propFullSize, drawAsOpening):
    """Port of drawFlower: pistils, stamens, then petal/other rows."""
    turtle = flower.plant.turtle
    _draw_floral_axis(flower, p, propFullSize, drawAsOpening, isStamen=False)
    _draw_floral_axis(flower, p, propFullSize, drawAsOpening, isStamen=True)
    for key in _FLOWER_ROW_ORDER:
        row = _flower_row(p, key)
        if row is None:
            continue
        scale = (_gp(row, "scaleAtFullSize", 0.0) / 100.0) * propFullSize
        if scale <= 0:
            continue
        tdo = getattr(row, "object3D", None)
        if tdo is None:
            continue
        r_tdo = resolve_tdo(flower.plant, tdo,
                            owner=f"species '{flower.plant.name}' flower row '{key}' object3D")
        angle = _angle_with_sway(flower, _gp(row, "pullBackAngle", 0.0) or 0.0)
        if drawAsOpening:
            angle = angle * propFullSize * 2
            if angle > (_gp(row, "pullBackAngle", 0.0) or 0.0):
                angle = _gp(row, "pullBackAngle", 0.0) or 0.0
        turtle.push()
        turtle.rotateX(_angle_with_sway(flower, _gp(row, "xRotationBeforeDraw", 0.0)))
        turtle.rotateY(_angle_with_sway(flower, _gp(row, "yRotationBeforeDraw", 0.0)))
        turtle.rotateZ(_angle_with_sway(flower, _gp(row, "zRotationBeforeDraw", 0.0)))
        _draw_circle_of_tdos(flower, r_tdo, _row_color(row, flower.plant, key),
                             angle, scale,
                             max(1, int(_gp(row, "repetitions", 1) or 1)),
                             _gp(row, "radiallyArranged", True), True,
                             part_id=kExportPartFlower)
        turtle.pop()


def _draw_floral_axis(flower, p, propFullSize, drawAsOpening, isStamen):
    """Port of drawPistilsAndStamens: styles/filaments + stigma/anther TDOs."""
    turtle = flower.plant.turtle
    row_key = "kStamens" if isStamen else "kPistils"
    row = _flower_row(p, row_key)
    num = int(_gp(p, "numStamens", 0) or 0) if isStamen else \
        int(_gp(p, "numPistils", 0) or 0)
    if num <= 0:
        return
    line_len = _gp(p, "filamentLength_mm", 0.0) if isStamen else \
        _gp(p, "styleLength_mm", 0.0)
    line_wid = _gp(p, "filamentWidth_mm", 0.0) if isStamen else \
        _gp(p, "styleWidth_mm", 0.0)
    line_color = _gp(p, "filamentColor", None) if isStamen else \
        _gp(p, "styleColor", None)
    taper = _gp(p, "filamentTaperIndex", 100) if isStamen else \
        _gp(p, "styleTaperIndex", 100)
    turtle.push()
    if row is not None:
        turnPortion = 256 / num
        leftOverDegrees = 256 - turnPortion * num
        addition = umath.safedivExcept(leftOverDegrees, num, 0) \
            if leftOverDegrees > 0 else 0
        carryOver = 0
        for _ in range(num):
            turtle.push()
            if line_len > 0 and line_wid > 0:
                length = umath.max(0.0, propFullSize * line_len)
                width = umath.max(0.0, propFullSize * line_wid)
                angle = _angle_with_sway(flower, _gp(row, "pullBackAngle", 0.0) or 0.0)
                if drawAsOpening:
                    angle = angle * propFullSize
                if line_color is not None:
                    _draw_stem_segment(flower, length, width, angle, 0,
                                       line_color, taper, kExportPartMeristem)
            scale = (_gp(row, "scaleAtFullSize", 0.0) / 100.0) * propFullSize
            tdo = getattr(row, "object3D", None)
            if tdo is not None:
                r_tdo = resolve_tdo(flower.plant, tdo,
                                    owner=f"species '{flower.plant.name}' "
                                          f"flower row '{row_key}' object3D")
                turtle.rotateX(_angle_with_sway(flower, _gp(row, "xRotationBeforeDraw", 0.0)))
                turtle.rotateY(_angle_with_sway(flower, _gp(row, "yRotationBeforeDraw", 0.0)))
                turtle.rotateZ(_angle_with_sway(flower, _gp(row, "zRotationBeforeDraw", 0.0)))
                _draw_circle_of_tdos(flower, r_tdo,
                                     _row_color(row, flower.plant, row_key),
                                     0.0, scale,
                                     max(1, int(_gp(row, "repetitions", 1) or 1)),
                                     _gp(row, "radiallyArranged", True), True,
                                     part_id=kExportPartFlower)
            turtle.pop()
            addThisTime = int(addition + carryOver)
            carryOver = carryOver + addition - addThisTime
            if carryOver < 0:
                carryOver = 0
            turtle.rotateX(turnPortion + addThisTime)
    turtle.pop()


def draw_fruit(flower, plant):
    """Draw the fruit TDO for a flower that has set fruit.

    Faithful port: scale = (scaleAtFullSize/100) * flower propFullSize,
    circle-of-TDOs radial arrangement. Color follows stage: unripe fruit
    (isRipe False) uses alternateFaceColor, ripe fruit uses faceColor
    (matching ufruit.py draw: unripe = alternate color, ripe = regular).
    """
    turtle = plant.turtle
    if turtle is None:
        return
    from .tdo_parser import AssetError
    fruit_params = getattr(plant.params, "pFruit", None)
    if fruit_params is None:
        raise AssetError(
            f"cannot draw fruit for species '{plant.name}': pFruit params missing")
    tdo_container = getattr(fruit_params, "tdoParams", None)
    if tdo_container is None:
        raise AssetError(
            f"cannot draw fruit for species '{plant.name}': "
            f"pFruit.tdoParams missing (fruit 3D object reference not set)")
    if tdo_container.object3D is None:
        raise AssetError(
            f"cannot draw fruit for species '{plant.name}': "
            f"pFruit.tdoParams.object3D is None")
    r_tdo = resolve_tdo(plant, tdo_container.object3D,
                        owner=f"species '{plant.name}' pFruit.tdoParams.object3D")
    # Fruit propFullSize is relative to the FRUIT's own optimal biomass
    # (pFruit.optimalBiomass_pctMPB), clamped to [0,1] like the original
    # (ufruit.py draw: min(1.0, totalBiomass / pFruit.optimalBiomass)).
    fruit_optimal = _gp(fruit_params, "optimalBiomass_pctMPB", 1.0) or 1.0
    prop_full_size = min(
        1.0,
        (flower.liveBiomass_pctMPB + flower.deadBiomass_pctMPB)
        / max(0.001, fruit_optimal),
    )
    scale_at_full = getattr(tdo_container, "scaleAtFullSize", 0.0)
    if not scale_at_full:
        raise AssetError(
            f"cannot draw fruit for species '{plant.name}': "
            f"pFruit.tdoParams.scaleAtFullSize is {scale_at_full!r}")
    scale = (scale_at_full / 100.0) * prop_full_size
    # stage color: ripe uses faceColor, unripe uses alternateFaceColor
    # (fall back to faceColor if the alternate color is unset)
    if getattr(flower, "isRipe", False):
        color = tdo_container.faceColor
    else:
        color = getattr(tdo_container, "alternateFaceColor", None)
        if color is None:
            color = tdo_container.faceColor
    if color is None:
        raise AssetError(
            f"cannot draw fruit for species '{plant.name}': "
            f"pFruit.tdoParams.faceColor is None "
            f"(ripe section front face color not set in .pla)")
    reps = max(1, int(getattr(tdo_container, "repetitions", 1) or 1))
    radial = getattr(tdo_container, "radiallyArranged", True)
    pull_back = getattr(tdo_container, "pullBackAngle", 0.0) or 0.0
    turtle.push()
    turtle.rotateX(getattr(tdo_container, "xRotationBeforeDraw", 0.0) or 0.0)
    turtle.rotateY(getattr(tdo_container, "yRotationBeforeDraw", 0.0) or 0.0)
    turtle.rotateZ(getattr(tdo_container, "zRotationBeforeDraw", 0.0) or 0.0)
    _draw_circle_of_tdos(flower, r_tdo, color, pull_back, scale, reps, radial,
                         False, isFruit=True, part_id=kExportPartFruit)
    turtle.pop()
