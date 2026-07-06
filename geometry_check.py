"""
Independent geometric validator for Shakashaka solutions.

Checks, from first principles (no SAT clauses, no IP constraints), that:
  1. every numbered black cell has exactly its number of triangle neighbours;
  2. every maximal connected white region is a rectangle, either axis-aligned
     or rotated by 45 degrees.

Method: each cell is split by its two diagonals into 4 sub-triangles
(N, E, S, W).  The white part of each motif is a union of sub-triangles:
    WHITE: {N,E,S,W}        TRI_UL(1): {S,E}     TRI_BL(2): {N,E}
    TRI_BR(3): {N,W}        TRI_UR(4): {S,W}     BLACK: {}
Two white sub-triangles are connected iff they share a segment of positive
length.  A maximal white region R of area A is a rectangle iff
    A == width(R) * height(R)                      (axis-aligned), or
    2A == width_uv(R) * height_uv(R)               (45-degree, u=x+y, v=x-y).
since equality of area with the bounding-box area forces R to fill its box.
"""

from __future__ import annotations

from puzzle import ShakashakaPuzzle, Motif

# white sub-triangles per motif value
WHITE_PARTS = {
    1: ("S", "E"),          # black fills upper-left
    2: ("N", "E"),          # black fills lower-left
    3: ("N", "W"),          # black fills lower-right
    4: ("S", "W"),          # black fills upper-right
    5: ("N", "E", "S", "W"),
    6: (),
}

# vertices of each sub-triangle of the unit cell with top-left corner (x, y)
# (x to the right = column j-1, y downwards = row i-1)
def _verts(x, y, part):
    c = (x + .5, y + .5)
    tl, tr = (x, y), (x + 1, y)
    bl, br = (x, y + 1), (x + 1, y + 1)
    return {"N": (tl, tr, c), "E": (tr, br, c),
            "S": (bl, br, c), "W": (tl, bl, c)}[part]


# pairs of sub-triangles inside one cell that share a half-diagonal,
# and the diagonal that separates them having to be "uncut" (i.e. the cell's
# motif does not place its hypotenuse there).  In a white cell all four are
# mutually connected through the centre halves; in a b/w cell the two white
# sub-triangles always share a half-diagonal not covered by the hypotenuse.
_IN_CELL = {
    5: [("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")],
    1: [("S", "E")], 2: [("N", "E")], 3: [("N", "W")], 4: [("S", "W")],
    6: [],
}


def check_solution(puzzle: ShakashakaPuzzle,
                   solution: dict[tuple[int, int], Motif]) -> list[str]:
    """Return a list of rule violations (empty list = valid solution)."""
    errors: list[str] = []
    m, n = puzzle.nrows, puzzle.ncols

    def motif(i, j) -> int:
        if puzzle.is_black(i, j):
            return 6
        mo = solution.get((i, j))
        return int(mo) if mo is not None else 0

    # ---- rule 1: clue counts ----------------------------------------- #
    for (i, j), k in puzzle.indexed_cells.items():
        cnt = sum(1 for (a, b) in puzzle.neighbors(i, j)
                  if motif(a, b) in (1, 2, 3, 4))
        if cnt != k:
            errors.append(f"clue ({i},{j})={k} but {cnt} triangle neighbours")

    # every playable cell must carry a motif
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if puzzle.is_playable(i, j) and motif(i, j) not in (1, 2, 3, 4, 5):
                errors.append(f"cell ({i},{j}) unassigned")
                return errors

    # ---- rule 2: white regions are rectangles ------------------------- #
    # nodes: (i, j, part); union-find over white sub-triangles
    parent: dict = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    nodes = []
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            for p in WHITE_PARTS[motif(i, j)]:
                node = (i, j, p)
                parent[node] = node
                nodes.append(node)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            mo = motif(i, j)
            for (p, q) in _IN_CELL[mo]:
                union((i, j, p), (i, j, q))
            # across cells: E_(i,j) ~ W_(i,j+1), S_(i,j) ~ N_(i+1,j)
            if j < n and (i, j, "E") in parent and (i, j + 1, "W") in parent:
                union((i, j, "E"), (i, j + 1, "W"))
            if i < m and (i, j, "S") in parent and (i + 1, j, "N") in parent:
                union((i, j, "S"), (i + 1, j, "N"))

    from collections import defaultdict
    regions = defaultdict(list)
    for node in nodes:
        regions[find(node)].append(node)

    for root, members in regions.items():
        area = len(members) * 0.25
        xs, ys, us, vs = [], [], [], []
        for (i, j, p) in members:
            for (x, y) in _verts(j - 1, i - 1, p):
                xs.append(x); ys.append(y)
                us.append(x + y); vs.append(x - y)
        bbox_xy = (max(xs) - min(xs)) * (max(ys) - min(ys))
        bbox_uv = (max(us) - min(us)) * (max(vs) - min(vs))
        ok_axis = abs(area - bbox_xy) < 1e-9
        ok_diag = abs(2 * area - bbox_uv) < 1e-9
        if not (ok_axis or ok_diag):
            (i, j, p) = members[0]
            errors.append(
                f"white region at ({i},{j}) [{len(members)} sub-triangles, "
                f"area {area}] is not a rectangle "
                f"(bbox_xy={bbox_xy}, bbox_uv/2={bbox_uv/2})")

    return errors
