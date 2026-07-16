"""
0-1 Integer Programming solver for Shakashaka puzzles.

Faithful implementation of the IP model of:
    E. D. Demaine, Y. Okamoto, R. Uehara, Y. Uno,
    "Computational Complexity and an Integer Programming Model of Shakashaka",
    IEICE Trans. Fundamentals, E97-A(6):1213-1219, 2014 (also CCCG 2013).

Solved with SCIP (via PySCIPOpt), the same solver family used in the
original paper.

Motif numbering (same as puzzle.py / the SAT encoder):
    1 = TRI_UL : black triangle fills the upper-left corner
    2 = TRI_BL : black triangle fills the lower-left corner
    3 = TRI_BR : black triangle fills the lower-right corner
    4 = TRI_UR : black triangle fills the upper-right corner
    5 = WHITE  : cell remains white
    6 = BLACK  : black cell (given, not a variable)

Constraint families (paper numbering):
    A : exactly one motif among {1,2,3,4,5} per white square        (eq. 1)
    B : neighbours of black squares (fixings + clue equality)       (eqs. 2-3)
    C : sequences of triangles (diagonal continuation / 90-turn)    (eqs. 4-5)
    D : exclusion of concave corners among white squares            (eq. 6)
    E : exclusion of nested white rectangles                        (eq. 7)
"""

from __future__ import annotations

import time
from typing import Optional

from pyscipopt import Model, quicksum

from puzzle import ShakashakaPuzzle, Motif

WHITE = 5
TRIANGLES = (1, 2, 3, 4)


class IPSolver:
    """Solves a Shakashaka puzzle with the Demaine et al. 0-1 IP model."""

    def __init__(self, puzzle: ShakashakaPuzzle, corrected: bool = True):
        """corrected=True adds constraint family F (triangle-corner
        propagation), which is MISSING from the published model: the claim of
        [Demaine et al. 2014, Prop. 5] that "a concave corner may be produced
        by only white squares" overlooks concave corners formed at the corner
        of a *black* square by a b/w square and two white squares (see
        instance hf_1199 of the pencil-puzzle-bench dataset for a concrete
        counterexample to their Theorem 6).  corrected=False reproduces the
        published model A-E faithfully."""
        self.puzzle = puzzle
        self.corrected = corrected
        self.model: Optional[Model] = None
        self.x: dict[tuple[int, int, int], object] = {}
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._solve_time: float = 0.0
        self._build_time: float = 0.0
        self._feasible: Optional[bool] = None
        self.num_vars = 0
        self.num_conss = 0
        self.num_nonzeros = 0  # counted while building

    # Helpers

    def _is_white_sq(self, i: int, j: int) -> bool:
        """A 'white square' in the IP sense = playable cell of the instance."""
        return self.puzzle.is_playable(i, j)

    def _v(self, i: int, j: int, t: int):
        """Variable x[i,j,t]; None if (i,j) is not a white square."""
        return self.x.get((i, j, t))

    def _add_cons(self, cons, nnz: int):
        self.model.addCons(cons)
        self.num_conss += 1
        self.num_nonzeros += nnz

    # Model construction

    def build(self):
        p = self.puzzle
        m = Model("shakashaka_ip")
        m.hideOutput()
        self.model = m

        t0 = time.perf_counter()

        # ---- variables (5 per white square) ----
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if self._is_white_sq(i, j):
                    for t in (1, 2, 3, 4, WHITE):
                        self.x[(i, j, t)] = m.addVar(
                            vtype="B", name=f"x_{i}_{j}_{t}")
        self.num_vars = len(self.x)

        self._constraint_A()
        self._constraint_B()
        self._constraint_C()
        self._constraint_D()
        self._constraint_E()
        if self.corrected:
            self._constraint_F()

        self._build_time = time.perf_counter() - t0

    # ---- Constraint A: exactly one motif per white square (eq. 1) ----
    def _constraint_A(self):
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if self._is_white_sq(i, j):
                    self._add_cons(
                        quicksum(self.x[(i, j, t)]
                                 for t in (1, 2, 3, 4, WHITE)) == 1,
                        nnz=5)

    # ---- Constraint B: neighbours of black squares (eqs. 2-3) ----
    #
    # A white square adjacent to a black square (or to the board boundary,
    # which is modelled as a black border) must not expose a 45-degree white
    # corner towards it.  Forbidden triangle types per relative position:
    #   above a black square : {1, 4}   (white part touches its bottom edge)
    #   below a black square : {2, 3}   (white part touches its top edge)
    #   left  of a black sq. : {1, 2}   (white part touches its right edge)
    #   right of a black sq. : {3, 4}   (white part touches its left edge)
    # For a numbered black square with clue v, the remaining (allowed)
    # triangle variables of its neighbours sum to v.
    _FORBIDDEN = {
        (-1, 0): (1, 4),   # neighbour above the black square
        (+1, 0): (2, 3),   # neighbour below
        (0, -1): (1, 2),   # neighbour to the left
        (0, +1): (3, 4),   # neighbour to the right
    }

    def _black_squares(self):
        """All black squares: declared blacks + the border frame."""
        p = self.puzzle
        seen = set(p.black_cells)
        for j in range(1, p.ncols + 1):
            seen.add((1, j))
            seen.add((p.nrows, j))
        for i in range(1, p.nrows + 1):
            seen.add((i, 1))
            seen.add((i, p.ncols))
        return seen

    def _constraint_B(self):
        p = self.puzzle
        for (i, j) in self._black_squares():
            # variable fixings for the four neighbours
            for (di, dj), forb in self._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if self._is_white_sq(ni, nj):
                    for t in forb:
                        self._add_cons(self.x[(ni, nj, t)] == 0, nnz=1)

        # clue equalities (eq. 3)
        for (i, j), v in p.indexed_cells.items():
            terms = []
            for (di, dj), forb in self._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if self._is_white_sq(ni, nj):
                    allowed = [t for t in TRIANGLES if t not in forb]
                    terms.extend(self.x[(ni, nj, t)] for t in allowed)
            if terms:
                self._add_cons(quicksum(terms) == v, nnz=len(terms))
            elif v != 0:
                # no white neighbour but positive clue: infeasible
                z = self.model.addVar(vtype="B", name=f"infeas_{i}_{j}")
                self._add_cons(z == 0, nnz=1)
                self._add_cons(z == 1, nnz=1)

    # ---- Constraint C: sequences of triangles (eqs. 4-5) ----
    #
    # Each diagonal (hypotenuse) edge of a triangle must, at each of its two
    # endpoints, either continue with the same triangle type on the next cell
    # of the diagonal, or turn by 90 degrees with the appropriate type on the
    # orthogonally adjacent cell ("the other directions" of the paper).
    #
    # Each rule below is (cell offsets are (di,dj) row/col):
    #   x[i,j,t] <= x[turn] + x[continue]
    # and when the diagonal continues, the middle cell on the white side of
    # the hypotenuse must remain white:
    #   x[i,j,t] + x[continue,t] <= x[middle,WHITE] + 1
    _C_RULES = [
        # (t, end1_turn(dij, type), end1_cont(dij), ...)
        # type 2 (black BL, hyp = main diagonal, white above-right)
        (2, ((0, +1), 3), (+1, +1)),    # lower-right end (eq. 4 of the paper)
        (2, ((-1, 0), 1), (-1, -1)),    # upper-left end
        # type 4 (black UR, hyp = main diagonal, white below-left)
        (4, ((+1, 0), 3), (+1, +1)),    # lower-right end
        (4, ((0, -1), 1), (-1, -1)),    # upper-left end
        # type 1 (black UL, hyp = anti-diagonal, white below-right)
        (1, ((+1, 0), 2), (+1, -1)),    # lower-left end
        (1, ((0, +1), 4), (-1, +1)),    # upper-right end
        # type 3 (black BR, hyp = anti-diagonal, white above-left)
        (3, ((0, -1), 2), (+1, -1)),    # lower-left end
        (3, ((-1, 0), 4), (-1, +1)),    # upper-right end
    ]
    # middle white cell when the diagonal continues towards "down" direction
    _C_MIDDLE = {
        2: ((+1, +1), (0, +1)),   # k2 at (i,j) & (i+1,j+1) -> (i,j+1) white
        4: ((+1, +1), (+1, 0)),   # k4 pair -> (i+1,j) white
        1: ((+1, -1), (+1, 0)),   # k1 at (i,j) & (i+1,j-1) -> (i+1,j) white
        3: ((+1, -1), (0, -1)),   # k3 pair -> (i,j-1) white
    }

    def _constraint_C(self):
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                # eq. 4 family
                for (t, ((tdi, tdj), tt), (cdi, cdj)) in self._C_RULES:
                    rhs = []
                    vturn = self._v(i + tdi, j + tdj, tt)
                    vcont = self._v(i + cdi, j + cdj, t)
                    if vturn is not None:
                        rhs.append(vturn)
                    if vcont is not None:
                        rhs.append(vcont)
                    self._add_cons(
                        self.x[(i, j, t)] <= quicksum(rhs) if rhs
                        else self.x[(i, j, t)] <= 0,
                        nnz=1 + len(rhs))
                # eq. 5 family
                for t, ((cdi, cdj), (mdi, mdj)) in self._C_MIDDLE.items():
                    vcont = self._v(i + cdi, j + cdj, t)
                    vmid = self._v(i + mdi, j + mdj, WHITE)
                    if vcont is None:
                        continue
                    if vmid is not None:
                        self._add_cons(
                            self.x[(i, j, t)] + vcont <= vmid + 1, nnz=3)
                    else:
                        # middle cell is black: the pair is impossible
                        self._add_cons(
                            self.x[(i, j, t)] + vcont <= 1, nnz=2)

    # ---- Constraint D: exclusion of concave corners (eq. 6) ----
    #
    # If three white squares of a 2x2 block remain white, the fourth must be
    # white or the unique triangle type closing the corner.
    #   corner cell offset -> closing triangle type
    _D_RULES = [
        # (three white offsets, corner offset, closing type)
        (((0, 0), (+1, 0), (0, +1)), (+1, +1), 3),
        (((0, 0), (0, +1), (+1, +1)), (+1, 0), 2),
        (((0, 0), (+1, 0), (+1, +1)), (0, +1), 4),
        (((+1, 0), (0, +1), (+1, +1)), (0, 0), 1),
    ]

    def _constraint_D(self):
        p = self.puzzle
        for i in range(1, p.nrows):
            for j in range(1, p.ncols):
                for whites, (cdi, cdj), ct in self._D_RULES:
                    wvars = []
                    ok = True
                    for (di, dj) in whites:
                        v = self._v(i + di, j + dj, WHITE)
                        if v is None:
                            ok = False
                            break
                        wvars.append(v)
                    if not ok:
                        continue
                    vw = self._v(i + cdi, j + cdj, WHITE)
                    vt = self._v(i + cdi, j + cdj, ct)
                    rhs = [v for v in (vw, vt) if v is not None]
                    self._add_cons(
                        quicksum(wvars) <= quicksum(rhs) + 2 if rhs
                        else quicksum(wvars) <= 2,
                        nnz=len(wvars) + len(rhs))

    # ---- Constraint E: exclusion of nested white rectangles (eq. 7) ----
    #
    # If (i,j) and (i+k,j+k) carry the same anti-diagonal triangle type
    # (1 or 3), some cell (i+k',j+k'), 0<k'<k, must carry the opposite type;
    # similarly for main-diagonal types (2 and 4) along (i+k, j-k).
    _E_RULES = [
        (1, 3, +1),   # t, opposite t', column step (row step is always +1)
        (3, 1, +1),
        (2, 4, -1),
        (4, 2, -1),
    ]

    def _constraint_E(self):
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for (t, topp, cstep) in self._E_RULES:
                    k = 1
                    while True:
                        i2, j2 = i + k, j + k * cstep
                        if not (1 <= i2 <= p.nrows and 1 <= j2 <= p.ncols):
                            break
                        if self._is_white_sq(i2, j2):
                            between = []
                            for kk in range(1, k):
                                v = self._v(i + kk, j + kk * cstep, topp)
                                if v is not None:
                                    between.append(v)
                            self._add_cons(
                                self.x[(i, j, t)] + self.x[(i2, j2, t)]
                                <= quicksum(between) + 1,
                                nnz=2 + len(between))
                        k += 1

    # ---- Constraint F (correction): concave corners with a b/w square ----
    #
    # The white right angle of a triangle, together with two white squares,
    # can complete a 270-degree corner at the corner of a black square --
    # a case not excluded by families A-E of the published model. For each
    # triangle type t whose white right angle points to the 2x2 corner cell,
    # if the two orthogonal cells are white then the corner cell must be
    # white or the closing triangle type t':
    #   x[i,j,t] + x[r1,W] + x[r2,W] <= x[c,W] + x[c,t'] + 2
    # This is the IP analogue of the SAT L-shape closure clauses.
    _F_RULES = [
        # t, white offsets, corner offset, closing type t'
        (1, ((0, +1), (+1, 0)), (+1, +1), 3),
        (2, ((0, +1), (-1, 0)), (-1, +1), 4),
        (3, ((0, -1), (-1, 0)), (-1, -1), 1),
        (4, ((0, -1), (+1, 0)), (+1, -1), 2),
    ]

    def _constraint_F(self):
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for (t, whites, (cdi, cdj), tt) in self._F_RULES:
                    wvars = []
                    ok = True
                    for (di, dj) in whites:
                        v = self._v(i + di, j + dj, WHITE)
                        if v is None:        # neighbour is black/border
                            ok = False
                            break
                        wvars.append(v)
                    if not ok:
                        continue
                    vw = self._v(i + cdi, j + cdj, WHITE)
                    vt = self._v(i + cdi, j + cdj, tt)
                    rhs = [v for v in (vw, vt) if v is not None]
                    lhs = self.x[(i, j, t)]
                    self._add_cons(
                        lhs + quicksum(wvars) <= quicksum(rhs) + 2 if rhs
                        else lhs + quicksum(wvars) <= 2,
                        nnz=1 + len(wvars) + len(rhs))

    # Solving

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        """Build (if needed) and solve. Returns True/False, or None on timeout."""
        if self.model is None:
            self.build()
        if time_limit is not None:
            self.model.setRealParam("limits/time", time_limit)

        start = time.perf_counter()
        self.model.optimize()
        self._solve_time = time.perf_counter() - start

        status = self.model.getStatus()
        if status == "optimal":
            self._feasible = True
            self._extract_solution()
        elif status == "infeasible":
            self._feasible = False
        else:                      # timelimit, userinterrupt, ...
            self._feasible = None
        return self._feasible

    def _extract_solution(self):
        p = self.puzzle
        sol = {}
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if self._is_white_sq(i, j):
                    for t in (1, 2, 3, 4, WHITE):
                        if self.model.getVal(self.x[(i, j, t)]) > 0.5:
                            sol[(i, j)] = Motif(t)
                            break
                else:
                    sol[(i, j)] = Motif.BLACK
        self._solution = sol

    # Accessors

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def feasible(self) -> Optional[bool]:
        return self._feasible

    def display_solution(self) -> str:
        if self._solution is None:
            return "No solution found."
        lines = []
        for i in range(1, self.puzzle.nrows + 1):
            row = []
            for j in range(1, self.puzzle.ncols + 1):
                motif = self._solution.get((i, j))
                if motif is None:
                    row.append("?")
                elif motif == Motif.BLACK and (i, j) in self.puzzle.indexed_cells:
                    row.append(str(self.puzzle.indexed_cells[(i, j)]))
                else:
                    row.append(motif.symbol())
            lines.append(" ".join(row))
        return "\n".join(lines)
