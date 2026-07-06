"""
SAT solver wrapper for Shakashaka puzzles.

Uses pysat (python-sat) to solve the encoded CNF instance.
"""

from __future__ import annotations

import time
from typing import Optional

from pysat.solvers import Glucose4

from puzzle import ShakashakaPuzzle, Motif
from encoder import SATEncoder


class ShakashakaSolver:
    """Solves a Shakashaka puzzle using SAT."""

    def __init__(self, puzzle: ShakashakaPuzzle):
        self.puzzle = puzzle
        self.encoder = SATEncoder(puzzle)
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._solve_time: float = 0.0
        self._satisfiable: Optional[bool] = None

    def solve(self, verbose: bool = False,
              time_limit: Optional[float] = None) -> Optional[bool]:
        """Encode and solve the puzzle. Returns True if satisfiable, False if
        not, or None if `time_limit` (wall-clock seconds) was exceeded."""
        if not self.encoder.clauses:
            self.encoder.encode()
        clauses = self.encoder.clauses

        if verbose:
            print(f"Encoded: {self.encoder.num_vars} variables, {self.encoder.num_clauses} clauses")

        start = time.perf_counter()
        with Glucose4() as solver:
            for clause in clauses:
                solver.add_clause(clause)

            if time_limit is None:
                self._satisfiable = solver.solve()
            else:
                import threading
                timer = threading.Timer(time_limit, solver.interrupt)
                timer.start()
                try:
                    self._satisfiable = solver.solve_limited(
                        expect_interrupt=True)
                finally:
                    timer.cancel()
            self._solve_time = time.perf_counter() - start

            if self._satisfiable:
                model = solver.get_model()
                self._solution = self.encoder.decode_solution(model)

        return self._satisfiable

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def satisfiable(self) -> Optional[bool]:
        return self._satisfiable

    def display_solution(self) -> str:
        """Return a text representation of the solution."""
        if self._solution is None:
            return "No solution found."

        lines = []
        for i in range(1, self.puzzle.nrows + 1):
            row = []
            for j in range(1, self.puzzle.ncols + 1):
                motif = self._solution.get((i, j))
                if motif is not None:
                    if motif == Motif.BLACK and (i, j) in self.puzzle.indexed_cells:
                        row.append(str(self.puzzle.indexed_cells[(i, j)]))
                    else:
                        row.append(motif.symbol())
                else:
                    row.append("?")
            lines.append(" ".join(row))
        return "\n".join(lines)

    def export_dimacs(self, path: str):
        """Export the CNF to DIMACS format for use with external solvers."""
        if not self.encoder.clauses:
            self.encoder.encode()

        with open(path, "w") as f:
            f.write(f"p cnf {self.encoder.num_vars} {self.encoder.num_clauses}\n")
            for clause in self.encoder.clauses:
                f.write(" ".join(str(lit) for lit in clause) + " 0\n")
