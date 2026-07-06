"""
Artificial Shakashaka instances from Demaine et al. (Figure 9).

For each n >= 2, a 2n x 2n board whose four corners are filled with black
staircases; the staircase boundaries carry the clue "2".  Formally, with
inner coordinates (r, c) in {1,...,2n}^2:
    black     iff  r+c <= n  or  c-r >= n+1  or  r-c >= n+1  or  r+c >= 3n+2
    clue "2"  iff  equality holds in the corresponding inequality
Each instance has a unique solution (a large 45-degree rotated white square
surrounded by triangles).
"""

from __future__ import annotations

from puzzle import ShakashakaPuzzle


def artificial_instance(n: int) -> ShakashakaPuzzle:
    size = 2 * n
    black: set[tuple[int, int]] = set()
    indexed: dict[tuple[int, int], int] = {}
    for r in range(1, size + 1):
        for c in range(1, size + 1):
            conds = (r + c <= n, c - r >= n + 1,
                     r - c >= n + 1, r + c >= 3 * n + 2)
            eqs = (r + c == n, c - r == n + 1,
                   r - c == n + 1, r + c == 3 * n + 2)
            if any(conds):
                pos = (r + 1, c + 1)          # +1 for the border offset
                black.add(pos)
                if any(eqs):
                    indexed[pos] = 2
    return ShakashakaPuzzle(nrows=size + 2, ncols=size + 2,
                            black_cells=black, indexed_cells=indexed)


if __name__ == "__main__":
    p = artificial_instance(5)
    print(p.display_puzzle())
