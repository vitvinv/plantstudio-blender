"""Hand-run the original PdPlant.draw sequence for violet's first phytomer
using the port's KfMatrix (algebra-identical to the original's fast trig),
with the plant's actual stored draw inputs, and compare the seedling petiole
tip directions against (a) the reference OBJ and (b) our headless buffer."""
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from plant_census import merged_tdo_library  # noqa: E402
from plantstudio_blender.core.factory import create_plant  # noqa: E402
from plantstudio_blender.core.matrix3d import KfMatrix  # noqa: E402

MM = 1000.0


def fwd(m):
    return (m.a0, m.b0, m.c0)


def pos(m):
    return (m.position.x, m.position.y, m.position.z)


def pitch(v, up_idx=1):
    horiz = math.hypot(v[0], v[2]) if up_idx == 1 else math.hypot(v[1], v[2])
    return math.degrees(math.atan2(v[up_idx], horiz))


def main():
    lib, tdo_lib = merged_tdo_library()
    species = next(s for s in lib.species if s.name == "violet")
    plant = create_plant(species, seed=8737, tdo_library=tdo_lib)
    plant.growTo(60)
    fp = plant.firstPhytomer
    pGen = plant.params.pGeneral
    print("stored draw inputs:")
    print("  firstPhytomer.internodeAngle =", fp.internodeAngle, "(256-deg)")
    print("  xRotation/yRotation/zRotation =", pGen.xRotation, pGen.yRotation,
          pGen.zRotation)
    print("  petioleAngle =", plant.params.pLeaf.petioleAngle)
    print("  randomSway =", pGen.randomSway)
    print("  petioleLengthAtOptimal =", plant.params.pLeaf.petioleLengthAtOptimalBiomass_mm)
    print("  petioleWidthAtOptimal =", plant.params.pLeaf.petioleWidthAtOptimalBiomass_mm)
    print("  lineDivisions =", pGen.lineDivisions)
    for leaf in (fp.leftLeaf, fp.rightLeaf):
        print(f"  leaf sway={leaf.randomSwayIndex:.6f} propFullSize={leaf.propFullSize:.6f} "
              f"seedling={leaf.isSeedlingLeaf}")

    # ── original sequence: push; rotateZ(64); rotateX(xR); rotateY(yR);
    #    rotateZ(zR); [first phytomer draw] drawInternode; leaves
    m = KfMatrix()
    m.rotateZ(64)
    m.rotateX(pGen.xRotation * 256 / 360)
    m.rotateY(pGen.yRotation * 256 / 360)
    m.rotateZ(pGen.zRotation * 256 / 360)

    def draw_stem_segment(mat, length_mm, width, angle_z, angle_y,
                          divisions, taper_index=100):
        """Port of drawStemSegment export path; returns list of (start,end)
        centerlines per division (mm)."""
        real_angle_z = angle_z
        real_angle_y = angle_y
        turn_z = real_angle_z / divisions
        turn_y = real_angle_y / divisions
        draw_portion = length_mm / divisions
        segs = []
        for i in range(divisions):
            if i < divisions - 1:
                stz, sty, slen = turn_z, turn_y, draw_portion
            else:
                stz = real_angle_z - turn_z * (divisions - 1)
                sty = real_angle_y - turn_y * (divisions - 1)
                slen = length_mm - draw_portion * (divisions - 1)
            mat.rotateY(sty)
            mat.rotateZ(stz)
            start = pos(mat)
            mat.move(slen * 1.0)  # mm
            end = pos(mat)
            segs.append((start, end))
        return segs

    # internode (first phytomer)
    intern_len = max(0.0, fp.propFullLength() *
                     plant.params.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm)
    print("  first internode length =", intern_len)
    int_segs = draw_stem_segment(m, intern_len, 1.0, fp.internodeAngle, 0.0,
                                 int(pGen.lineDivisions))
    node = pos(m)
    print("  node (internode end) in export frame:", tuple(round(c, 2) for c in node))

    for leaf, side in ((fp.leftLeaf, "left"), (fp.rightLeaf, "right")):
        m2 = m.deepCopy()
        if side == "right":
            m2.rotateX(128)
        length = plant.params.pLeaf.petioleLengthAtOptimalBiomass_mm * leaf.propFullSize
        if leaf.isSeedlingLeaf:
            length = length / 2
        angle = leaf.randomSwayIndex  # placeholder, replaced below
        sway = pGen.randomSway
        angle = plant.params.pLeaf.petioleAngle + (leaf.randomSwayIndex - 0.5) * sway
        segs = draw_stem_segment(m2, length * 1.0, 1.0, angle, 0.0,
                                 int(pGen.lineDivisions))
        tip = pos(m2)
        d = tuple(tip[k] - node[k] for k in range(3))
        print(f"  {side} petiole: angle256={angle:.2f} len={length:.2f} "
              f"tip={tuple(round(c, 2) for c in tip)} "
              f"dir={tuple(round(c, 2) for c in d)} pitch={pitch(d):.1f}")

    print("\nref export-frame seedling petiole dirs (from OBJ chunks):")
    print("  seed0 dir ~ (-11.1, -31.3, -12.2) pitch", pitch((-11.1, -31.3, -12.2)))
    print("  seed1 dir ~ (18.8, -10.4, 25.5)  pitch", pitch((18.8, -10.4, 25.5)))


if __name__ == "__main__":
    main()
