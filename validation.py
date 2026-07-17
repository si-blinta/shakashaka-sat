"""Checks shared by the benchmark and the tests."""

from __future__ import annotations

from collections.abc import Mapping

from encoder import SATEncoder
from puzzle import Motif, ShakashakaPuzzle


def check_assignment_against_cnf(
    puzzle: ShakashakaPuzzle,
    solution: Mapping[tuple[int, int], Motif],
) -> bool:
    """Return whether a motif assignment satisfies the CNF model."""

    encoder = SATEncoder(puzzle)
    encoder.encode()
    values: dict[int, bool] = {}
    for row in range(1, puzzle.nrows + 1):
        for column in range(1, puzzle.ncols + 1):
            selected = solution.get((row, column))
            if selected is None:
                return False
            for motif in range(1, 7):
                values[encoder.var(row, column, motif)] = int(selected) == motif

    return all(
        any(values[abs(literal)] == (literal > 0) for literal in clause)
        for clause in encoder.clauses
    )
