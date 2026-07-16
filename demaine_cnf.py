"""Exact CNF translation of the corrected Demaine A-F model.

The encoder keeps the five semantic motif variables of the original 0-1
model for every playable cell. It introduces no auxiliary variables:
the only cardinality constraints have at most eight literals, so the classical
binomial encoding is both exact and small.  Families C--F are implications and
therefore translate to one clause per linear inequality.
"""

from __future__ import annotations

from itertools import combinations

from ip_solver import IPSolver, TRIANGLES, WHITE
from puzzle import Motif, ShakashakaPuzzle


def exactly_k_clauses(literals: list[int], bound: int) -> list[list[int]]:
    """Return an auxiliary-free CNF equivalent to ``sum(literals) == bound``."""

    size = len(literals)
    if bound < 0 or bound > size:
        return [[]]

    clauses: list[list[int]] = []

    # At most ``bound``: no subset of bound + 1 literals may all be true.
    if bound < size:
        clauses.extend(
            [-literal for literal in subset]
            for subset in combinations(literals, bound + 1)
        )

    # At least ``bound``: no subset of size - bound + 1 may all be false.
    if bound > 0:
        clauses.extend(
            list(subset)
            for subset in combinations(literals, size - bound + 1)
        )

    return clauses


class DemaineCNFEncoder:
    """Translate the corrected Demaine A-F model to plain CNF."""

    def __init__(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        corrected: bool = True,
    ) -> None:
        self.puzzle = puzzle
        self.corrected = corrected
        self.variables: dict[tuple[int, int, int], int] = {}
        self.clauses: list[list[int]] = []
        self.num_vars = 0
        self.num_clauses = 0
        self.num_nonzeros = 0
        self.num_source_constraints = 0
        self.num_source_nonzeros = 0
        self._encoded = False

    def _is_white_sq(self, i: int, j: int) -> bool:
        return self.puzzle.is_playable(i, j)

    def _v(self, i: int, j: int, motif: int) -> int | None:
        return self.variables.get((i, j, motif))

    def _new_var(self, key: tuple[int, int, int]) -> int:
        self.num_vars += 1
        self.variables[key] = self.num_vars
        return self.num_vars

    def _add_clause(self, clause) -> None:
        normalized = [int(literal) for literal in clause]
        self.clauses.append(normalized)
        self.num_clauses += 1
        self.num_nonzeros += len(normalized)

    def _add_source_constraint(self, *, nnz: int) -> None:
        self.num_source_constraints += 1
        self.num_source_nonzeros += int(nnz)

    def _add_exactly(self, literals: list[int], bound: int) -> None:
        for clause in exactly_k_clauses(literals, bound):
            self._add_clause(clause)

    def _black_squares(self) -> set[tuple[int, int]]:
        puzzle = self.puzzle
        cells = set(puzzle.black_cells)
        for j in range(1, puzzle.ncols + 1):
            cells.add((1, j))
            cells.add((puzzle.nrows, j))
        for i in range(1, puzzle.nrows + 1):
            cells.add((i, 1))
            cells.add((i, puzzle.ncols))
        return cells

    def encode(self) -> None:
        if self._encoded:
            return

        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if self._is_white_sq(i, j):
                    for motif in (*TRIANGLES, WHITE):
                        self._new_var((i, j, motif))

        self._constraint_a()
        self._constraint_b()
        self._constraint_c()
        self._constraint_d()
        self._constraint_e()
        if self.corrected:
            self._constraint_f()

        self._encoded = True

    def _constraint_a(self) -> None:
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                variables = [
                    self.variables[(i, j, motif)]
                    for motif in (*TRIANGLES, WHITE)
                ]
                self._add_source_constraint(nnz=5)
                self._add_exactly(variables, 1)

    def _constraint_b(self) -> None:
        puzzle = self.puzzle
        for i, j in self._black_squares():
            for (di, dj), forbidden in IPSolver._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if not self._is_white_sq(ni, nj):
                    continue
                for motif in forbidden:
                    self._add_source_constraint(nnz=1)
                    self._add_clause([-self.variables[(ni, nj, motif)]])

        for (i, j), clue in puzzle.indexed_cells.items():
            terms: list[int] = []
            for (di, dj), forbidden in IPSolver._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if self._is_white_sq(ni, nj):
                    allowed = [
                        motif for motif in TRIANGLES if motif not in forbidden
                    ]
                    terms.extend(
                        self.variables[(ni, nj, motif)] for motif in allowed
                    )
            if terms:
                self._add_source_constraint(nnz=len(terms))
                self._add_exactly(terms, clue)
            elif clue != 0:
                # SCIP/CP-SAT express this degenerate contradiction with one
                # internal variable and two unit constraints, but do not count
                # that implementation variable among the five motif variables.
                # A single empty clause is the exact CNF counterpart; the
                # source counters still mirror the two original constraints.
                self._add_source_constraint(nnz=1)
                self._add_source_constraint(nnz=1)
                self._add_clause([])

    def _constraint_c(self) -> None:
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, ((tdi, tdj), turn_motif), (cdi, cdj) in IPSolver._C_RULES:
                    rhs = []
                    turn = self._v(i + tdi, j + tdj, turn_motif)
                    continuation = self._v(i + cdi, j + cdj, motif)
                    if turn is not None:
                        rhs.append(turn)
                    if continuation is not None:
                        rhs.append(continuation)
                    self._add_source_constraint(nnz=1 + len(rhs))
                    self._add_clause([-self.variables[(i, j, motif)], *rhs])

                for motif, ((cdi, cdj), (mdi, mdj)) in IPSolver._C_MIDDLE.items():
                    continuation = self._v(i + cdi, j + cdj, motif)
                    if continuation is None:
                        continue
                    middle = self._v(i + mdi, j + mdj, WHITE)
                    clause = [
                        -self.variables[(i, j, motif)],
                        -continuation,
                    ]
                    if middle is not None:
                        clause.append(middle)
                    self._add_source_constraint(nnz=len(clause))
                    self._add_clause(clause)

    def _constraint_d(self) -> None:
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows):
            for j in range(1, puzzle.ncols):
                for whites, (cdi, cdj), closing_motif in IPSolver._D_RULES:
                    white_vars = []
                    for di, dj in whites:
                        variable = self._v(i + di, j + dj, WHITE)
                        if variable is None:
                            break
                        white_vars.append(variable)
                    if len(white_vars) != len(whites):
                        continue
                    rhs = [
                        variable
                        for variable in (
                            self._v(i + cdi, j + cdj, WHITE),
                            self._v(i + cdi, j + cdj, closing_motif),
                        )
                        if variable is not None
                    ]
                    clause = [-variable for variable in white_vars] + rhs
                    self._add_source_constraint(nnz=len(clause))
                    self._add_clause(clause)

    def _constraint_e(self) -> None:
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, opposite, column_step in IPSolver._E_RULES:
                    distance = 1
                    while True:
                        i2 = i + distance
                        j2 = j + distance * column_step
                        if not (1 <= i2 <= puzzle.nrows and 1 <= j2 <= puzzle.ncols):
                            break
                        if self._is_white_sq(i2, j2):
                            between = [
                                variable
                                for offset in range(1, distance)
                                if (
                                    variable := self._v(
                                        i + offset,
                                        j + offset * column_step,
                                        opposite,
                                    )
                                )
                                is not None
                            ]
                            clause = [
                                -self.variables[(i, j, motif)],
                                -self.variables[(i2, j2, motif)],
                                *between,
                            ]
                            self._add_source_constraint(nnz=len(clause))
                            self._add_clause(clause)
                        distance += 1

    def _constraint_f(self) -> None:
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, whites, (cdi, cdj), closing_motif in IPSolver._F_RULES:
                    white_vars = []
                    for di, dj in whites:
                        variable = self._v(i + di, j + dj, WHITE)
                        if variable is None:
                            break
                        white_vars.append(variable)
                    if len(white_vars) != len(whites):
                        continue
                    rhs = [
                        variable
                        for variable in (
                            self._v(i + cdi, j + cdj, WHITE),
                            self._v(i + cdi, j + cdj, closing_motif),
                        )
                        if variable is not None
                    ]
                    clause = [
                        -self.variables[(i, j, motif)],
                        *(-variable for variable in white_vars),
                        *rhs,
                    ]
                    self._add_source_constraint(nnz=len(clause))
                    self._add_clause(clause)

    def decode_solution(
        self,
        model: list[int],
    ) -> dict[tuple[int, int], Motif]:
        positive = {literal for literal in model if literal > 0}
        solution: dict[tuple[int, int], Motif] = {}
        puzzle = self.puzzle
        for i in range(1, puzzle.nrows + 1):
            for j in range(1, puzzle.ncols + 1):
                if self._is_white_sq(i, j):
                    selected = [
                        motif
                        for motif in (*TRIANGLES, WHITE)
                        if self.variables[(i, j, motif)] in positive
                    ]
                    if len(selected) != 1:
                        raise RuntimeError(
                            f"invalid Demaine CNF model at ({i},{j}): {selected}"
                        )
                    solution[(i, j)] = Motif(selected[0])
                else:
                    solution[(i, j)] = Motif.BLACK
        return solution
