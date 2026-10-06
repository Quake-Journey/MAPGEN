#!/usr/bin/env python3
"""Independent reference for MAPGEN-1's PRNG.

Written from the published SplitMix64 and xoshiro256** definitions, not from
the C. Where the C and this agree, two people made the same reading of the same
paper; where they disagree, one of them is wrong and the guard says so.

The rejection bound in `below` is the part worth having twice. Modulo bias is
invisible in a spot check and changes every learned distribution the generator
samples from.
"""

from __future__ import annotations

M64 = (1 << 64) - 1
M32 = (1 << 32) - 1

TOPOLOGY, BRUSHES, MATERIALS, ITEMS, SPAWNS, ENTITIES, LIGHTING, DECORATION = range(1, 9)


def rotl(x: int, k: int) -> int:
    x &= M64
    return ((x << k) | (x >> (64 - k))) & M64


class SplitMix64:
    def __init__(self, seed: int) -> None:
        self.x = seed & M64

    def next(self) -> int:
        self.x = (self.x + 0x9E3779B97F4A7C15) & M64
        z = self.x
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)


class Random:
    """xoshiro256**, seeded exactly the way MapGenRandom_Stream seeds it."""

    def __init__(self, seed: int, attempt: int, purpose: int) -> None:
        sm = SplitMix64(seed)
        x = sm.next() ^ ((attempt * 0xD1342543DE82EF95) & M64)
        sm.x = x
        x = sm.next() ^ ((purpose * 0xA24BAED4963EE407) & M64)
        sm.x = x
        self.s = [sm.next() for _ in range(4)]
        if not any(self.s):
            self.s[0] = 0x9E3779B97F4A7C15

    def next(self) -> int:
        result = (rotl((self.s[1] * 5) & M64, 7) * 9) & M64
        t = (self.s[1] << 17) & M64
        self.s[2] ^= self.s[0]
        self.s[3] ^= self.s[1]
        self.s[1] ^= self.s[2]
        self.s[0] ^= self.s[3]
        self.s[2] ^= t
        self.s[3] = rotl(self.s[3], 45)
        return result

    def below(self, bound: int) -> int:
        if bound <= 1:
            return 0
        limit = (1 << 32) - ((1 << 32) % bound)
        while True:
            value = self.next() >> 32
            if value < limit:
                return value % bound

    def range(self, lo: int, hi: int) -> int:
        if lo > hi:
            lo, hi = hi, lo
        span = hi - lo + 1
        if span >= (1 << 32):
            return lo + (self.next() >> 32)
        return lo + self.below(span)

    def weighted(self, weights: list[int]) -> int:
        count = len(weights)
        if not count:
            return count
        total = sum(weights)
        if not total:
            return count
        if total <= M32:
            pick = self.below(total)
        else:
            limit = M64 - (M64 % total)
            while True:
                pick = self.next()
                if pick < limit:
                    break
            pick %= total
        seen = 0
        for i, w in enumerate(weights):
            seen += w
            if pick < seen:
                return i
        return count - 1

    def shuffle(self, items: list) -> list:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out

    def chance(self, permille: int) -> bool:
        if permille <= 0:
            return False
        if permille >= 1000:
            return True
        return self.below(1000) < permille


def naive_below(seed: int, attempt: int, purpose: int, bound: int, count: int) -> list[int]:
    """What a modulo-folding implementation would have produced.

    Kept so the guard can prove the two differ: a rejection loop nobody can
    tell from a modulo is a rejection loop nobody has tested.
    """
    r = Random(seed, attempt, purpose)
    return [(r.next() >> 32) % bound for _ in range(count)]
