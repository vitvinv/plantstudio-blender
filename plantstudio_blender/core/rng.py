"""Deterministic random number generator (port of PlantStudio's PdRandom).

Park-Miller linear congruential generator, identical to the original:
    seed = (16807 * (seed mod 127773)) - (2836 * k)  mod 2147483647

Fully deterministic given a seed — this is what makes the whole
growth simulation reproducible (same seed + params + day = same plant).
"""


def _intround(x):
    return int(round(x))


class PdRandom:
    def __init__(self):
        self.seed = 0

    def createFromTime(self):
        import time
        self.seed = intround(time.time() * 100.0)
        return self

    def setSeed(self, aSeed):
        self.seed = aSeed

    def initialize(self, aLong):
        self.seed = aLong

    def _nextSeed(self):
        k = _intround(self.seed / 127773.0)
        self.seed = _intround((16807 * (self.seed - (k * 127773))) - (k * 2846))
        if self.seed < 0.0:
            self.seed = self.seed + 2147483647
        return self.seed

    def randomNormalWithStdDev(self, mean, stdDev):
        randomNumber = 0.0
        for _ in range(12):
            randomNumber = randomNumber + self.zeroToOne()
        return (randomNumber - 6.0) * stdDev + mean

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
        k = _intround(self.seed / 127773.0)
        self.seed = _intround((16807 * (self.seed - (k * 127773))) - (k * 2846))
        if self.seed < 0.0:
            self.seed = self.seed + 2147483647
        return _intround(max(0, min(100, self.seed * 0.0000000004656612875 * 100.0)))

    def zeroToOne(self):
        k = _intround(self.seed / 127773.0)
        self.seed = _intround((16807 * (self.seed - (k * 127773))) - (k * 2846))
        if self.seed < 0.0:
            self.seed = self.seed + 2147483647
        return max(0.0, min(1.0, self.seed * 0.0000000004656612875))
