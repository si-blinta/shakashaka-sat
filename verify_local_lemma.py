"""
verify_local_lemma.py
=====================
Mechanical verification of the case inspection used in the completeness half
of the correctness theorem of the paper (every valid solution satisfies all
local rectangularity clauses).

Two facts are checked.

FACT 1 (window inspection, exhaustive).
    For every one of the 6^4 = 1296 motif assignments of a 2x2 window:
    if the window falsifies any local clause OTHER than the four opposed
    pairs (2a)-(2d) -- i.e. any binary exclusion, L-shape closure clause
    (3a)-(3d)/(5a)-(5d), or triangle-adjacency clause (4a)-(4h) -- then at
    one of the nine lattice vertices of the window the white area has a
    FORCED forbidden angle: a maximal run of white 45-degree sectors,
    bounded by black sectors on both sides, whose length L satisfies
    45*L not in {90, 180}.  "Forced" means the run and its two delimiters
    are determined by the window cells alone, so the angle is forbidden
    whatever the surrounding cells are.  Since rectangles (axis-aligned or
    45-degree rotated) only exhibit white angles of 0, 90, 180 or 360
    degrees at lattice vertices, no valid solution can contain such a
    window.

FACT 2 (opposed pairs, parity).
    The four opposed-pair clauses (2a)-(2d) forbid <UL,BR> and <BL,UR>
    triangle pairs adjacent horizontally/vertically.  Their exclusion is
    NOT witnessed by a local corner: it is a parity argument.  The two
    hypotenuses lie on parallel diagonal grid lines with black parts on
    opposite outer sides, so in a valid solution they must support the two
    opposite diagonal sides of one 45-degree rotated rectangle, carried by
    lines  x+y = a  and  x+y = b  (or  x-y = a/b).  The corners of such a
    rectangle are lattice vertices, which forces a = b (mod 2).  The script
    computes the two supporting lines for each of the four pairs and checks
    that |a-b| = 1 in every case: an odd offset, hence a contradiction.

Exit code 0 and "ALL CHECKS PASSED" mean the inspection is verified.
"""

from itertools import product

# ------------------------------------------------------------------ #
# white sub-triangles per motif (same table as geometry_check.py)
# ------------------------------------------------------------------ #
WHITE_PARTS = {
    1: {"S", "E"},   # black fills upper-left corner
    2: {"N", "E"},   # black fills lower-left corner
    3: {"N", "W"},   # black fills lower-right corner
    4: {"S", "W"},   # black fills upper-right corner
    5: {"N", "E", "S", "W"},
    6: set(),
}

# ------------------------------------------------------------------ #
# geometry: 8 angular sectors around a lattice vertex
# ------------------------------------------------------------------ #

def sector_states(w, vr, vc):
    """States of the 8 sectors (45 degrees each, counter-clockwise from
    East) around lattice vertex (vr, vc) of the window, vr, vc in {0,1,2}.
    Each quadrant cell contributes two sectors, separated by its diagonal;
    'W' = white, 'B' = black, 'U' = cell outside the window (unknown).
    Order: NE.S, NE.W, NW.E, NW.S, SW.N, SW.E, SE.W, SE.N  where NE/NW/SW/SE
    denote the four cells around the vertex."""
    def st(r, c, sub):
        if 0 <= r <= 1 and 0 <= c <= 1:
            return 'W' if sub in WHITE_PARTS[w[r][c]] else 'B'
        return 'U'
    return [st(vr - 1, vc, "S"), st(vr - 1, vc, "W"),
            st(vr - 1, vc - 1, "E"), st(vr - 1, vc - 1, "S"),
            st(vr, vc - 1, "N"), st(vr, vc - 1, "E"),
            st(vr, vc, "W"), st(vr, vc, "N")]


def forced_bad(states):
    """True iff some maximal run of 'W' sectors, delimited by 'B' on both
    sides, has a length L with 45*L not in {90, 180} degrees."""
    n = 8
    for start in range(n):
        if states[start] != 'W' or states[(start - 1) % n] != 'B':
            continue
        L, k = 0, start
        while L < n and states[k] == 'W':
            L += 1
            k = (k + 1) % n
        if states[k] == 'B' and L not in (2, 4):
            return True
    return False


# ------------------------------------------------------------------ #
# the local clauses, window-relative (mirrors encoder.py / the paper)
# ------------------------------------------------------------------ #
OPPOSED_H = {(1, 3), (2, 4)}       # clauses (2a), (2d)
OPPOSED_V = {(1, 3), (4, 2)}       # clauses (2c), (2b)

# binary exclusions, (left, right) and (top, bottom)
H_PAIRS = {(1, 6), (1, 1), (1, 2), (2, 6), (2, 1), (2, 2),
           (6, 3), (4, 3), (3, 3), (6, 4), (3, 4), (4, 4)}
V_PAIRS = {(1, 6), (1, 4), (1, 1), (6, 2), (2, 2), (3, 2),
           (6, 3), (2, 3), (3, 3), (4, 6), (4, 1), (4, 4)}

# implication clauses: (premises, conclusion cell, allowed motifs),
# cells are (row, col) positions in the window
IMPLICATIONS = [
    # (3a)-(3d) cornered-triangle L-shape closure
    ([((0, 0), 1), ((0, 1), 5), ((1, 0), 5)], (1, 1), {5, 3}),
    ([((1, 0), 2), ((1, 1), 5), ((0, 0), 5)], (0, 1), {5, 4}),
    ([((1, 1), 3), ((1, 0), 5), ((0, 1), 5)], (0, 0), {5, 1}),
    ([((0, 1), 4), ((0, 0), 5), ((1, 1), 5)], (1, 0), {5, 2}),
    # (5a)-(5d) all-white L-shape closure
    ([((0, 0), 5), ((0, 1), 5), ((1, 0), 5)], (1, 1), {5, 3}),
    ([((0, 0), 5), ((0, 1), 5), ((1, 1), 5)], (1, 0), {5, 2}),
    ([((0, 1), 5), ((1, 1), 5), ((1, 0), 5)], (0, 0), {5, 1}),
    ([((0, 0), 5), ((1, 0), 5), ((1, 1), 5)], (0, 1), {5, 4}),
    # (4a)-(4h) triangle adjacency propagation
    ([((1, 0), 5), ((1, 1), 4)], (0, 0), {4}),
    ([((0, 0), 5), ((1, 0), 3)], (0, 1), {3}),
    ([((0, 0), 2), ((0, 1), 5)], (1, 1), {2}),
    ([((0, 1), 1), ((1, 1), 5)], (1, 0), {1}),
    ([((1, 0), 1), ((1, 1), 5)], (0, 1), {1}),
    ([((0, 1), 5), ((1, 1), 2)], (0, 0), {2}),
    ([((0, 0), 5), ((0, 1), 3)], (1, 0), {3}),
    ([((0, 0), 4), ((1, 0), 5)], (1, 1), {4}),
]


def violations(w):
    """-> (violates a non-opposed clause, violates an opposed pair)."""
    nonopp = opp = False
    for r in (0, 1):
        p = (w[r][0], w[r][1])
        if p in OPPOSED_H:
            opp = True
        if p in H_PAIRS:
            nonopp = True
    for c in (0, 1):
        p = (w[0][c], w[1][c])
        if p in OPPOSED_V:
            opp = True
        if p in V_PAIRS:
            nonopp = True
    for prem, (r, c), allowed in IMPLICATIONS:
        if all(w[pr][pc] == k for (pr, pc), k in prem) and w[r][c] not in allowed:
            nonopp = True
    return nonopp, opp


# ------------------------------------------------------------------ #
# FACT 2: parity of the opposed pairs
# ------------------------------------------------------------------ #
# Cell (i, j) occupies [j-1, j] x [i-1, i] in (col, row) coordinates.
# Motifs 1 (black UL) and 3 (black BR) have their hypotenuse on the
# anti-diagonal line  col + row = const ; motifs 2 (black BL) and
# 4 (black UR) on the main-diagonal line  col - row = const.

def hyp_line(i, j, motif):
    """(family, constant, black_side) of the hypotenuse of `motif` at
    cell (i, j); black_side = sign of (line(x) - const) on the black part."""
    if motif in (1, 3):                       # anti-diagonal col+row
        c = (j - 1) + i                       # through BL (j-1, i), TR (j, i-1)
        return ("col+row", c, -1 if motif == 1 else +1)
    else:                                     # main diagonal col-row
        c = (j - 1) - (i - 1)                 # through TL (j-1, i-1), BR (j, i)
        return ("col-row", c, +1 if motif == 2 else -1)
        # motif 2: black below the main diagonal (col-row > c side is up-right)


OPPOSED_CASES = [
    ("(2a)  1|3 horizontal", (1, 1, 1), (1, 2, 3)),
    ("(2d)  2|4 horizontal", (1, 1, 2), (1, 2, 4)),
    ("(2c)  1/3 vertical  ", (1, 1, 1), (2, 1, 3)),
    ("(2b)  4/2 vertical  ", (1, 1, 4), (2, 1, 2)),
]


def check_parity():
    ok = True
    for name, (i1, j1, m1), (i2, j2, m2) in OPPOSED_CASES:
        f1, c1, s1 = hyp_line(i1, j1, m1)
        f2, c2, s2 = hyp_line(i2, j2, m2)
        same_family = (f1 == f2)
        opposite_black = (s1 != s2)
        offset = abs(c1 - c2)
        good = same_family and opposite_black and offset % 2 == 1
        print(f"  {name}: lines {f1}={c1} vs {f2}={c2}, "
              f"black on opposite sides: {opposite_black}, "
              f"offset {offset} (odd: {offset % 2 == 1})")
        ok &= good
    return ok


def main():
    print("FACT 1: exhaustive window inspection (6^4 windows, 9 vertices each)")
    n_win = n_nonopp = n_opp_only = 0
    failures = []
    for m in product((1, 2, 3, 4, 5, 6), repeat=4):
        w = [[m[0], m[1]], [m[2], m[3]]]
        n_win += 1
        nonopp, opp = violations(w)
        if nonopp:
            n_nonopp += 1
            if not any(forced_bad(sector_states(w, vr, vc))
                       for vr in range(3) for vc in range(3)):
                failures.append(m)
        elif opp:
            n_opp_only += 1
    print(f"  windows: {n_win}; violating a non-opposed clause: {n_nonopp}; "
          f"opposed-pairs only: {n_opp_only}")
    if failures:
        print("  FAILED for windows (NW,NE,SW,SE):")
        for m in failures:
            print("   ", m)
        raise SystemExit(1)
    print("  OK: every such window forces a forbidden white angle "
          "(not 0/90/180/360) at one of its lattice vertices.")
    print()
    print("FACT 2: opposed pairs (2a)-(2d) -- parity of hypotenuse lines")
    if not check_parity():
        raise SystemExit(1)
    print("  OK: each pair puts opposite rectangle sides on diagonal lines")
    print("  at odd offset, impossible for a rotated rectangle with corners")
    print("  on lattice vertices.")
    print()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
