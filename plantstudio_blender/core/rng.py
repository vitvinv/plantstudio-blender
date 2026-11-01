"""Deterministic random number generator (port of PlantStudio's PdRandom).

Park-Miller linear congruential generator, identical to the original:
    seed = (16807 * (seed mod 127773)) - (2846 * k)  mod 2147483647

(The original Delphi source says 2836; the actual constant used there is
2846 — reference-OBJ parity tests pass with 2846.)

Fully deterministic given a seed — this is what makes the whole
growth simulation reproducible (same seed + params + day = same plant).
"""


def _intround(x):
    return int(round(x))


class PdRandom:
    def __init__(self):
        self.seed = 0

    def setSeed(self, aSeed):
        self.seed = aSeed

    def _nextSeed(self):
        k = _intround(self.seed / 127773.0)
        self.seed = _intround((16807 * (self.seed - (k * 127773))) - (k * 2846))
        if self.seed < 0.0:
            self.seed = self.seed + 2147483647
        return self.seed

    def randomNormal(self, mean):
        """Normal random number based on mean (std dev = half mean)."""
        randomNumber = 0.0
        for _ in range(12):
            randomNumber = randomNumber + self.zeroToOne()
        return (randomNumber - 6.0) * (mean / 2.0) + mean

    def randomNormalBoundedZeroToOne(self, mean):
        return max(0.0, min(1.0, self.randomNormal(mean)))

    def randomNormalPercent(self, mean):
        return max(0, min(100, _intround(self.randomNormal(mean / 100.0) * 100.0)))

    def randomPercent(self):
        return _intround(max(0, min(100, self._nextSeed() * 0.0000000004656612875 * 100.0)))

    def zeroToOne(self):
        return max(0.0, min(1.0, self._nextSeed() * 0.0000000004656612875))
