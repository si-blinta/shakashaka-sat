"""Reproduce the A-E counterexample and verify the corrective family F."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry_check import check_solution
from instances import load_instance
from ip_solver import IPSolver
from puzzle import Motif, ShakashakaPuzzle
from solver_backends import configure_scip


DATA_PATH = ROOT / "data" / "hf_instances.jsonl"
DEFECTIVE_CORNER = (
    (4, 4, Motif.TRI_UL),
    (4, 5, Motif.WHITE),
    (5, 4, Motif.WHITE),
)


def motif_at(
    puzzle: ShakashakaPuzzle,
    solution: dict[tuple[int, int], Motif],
    row: int,
    col: int,
) -> Motif:
    if puzzle.is_black(row, col):
        return Motif.BLACK
    return solution[(row, col)]


def indicator(
    puzzle: ShakashakaPuzzle,
    solution: dict[tuple[int, int], Motif],
    row: int,
    col: int,
    motif: Motif,
) -> int:
    return int(motif_at(puzzle, solution, row, col) == motif)


def corner_values(
    puzzle: ShakashakaPuzzle,
    solution: dict[tuple[int, int], Motif],
) -> tuple[int, int, int, int]:
    """Evaluate families D and F on the defective 2x2 corner."""
    d_lhs = (
        indicator(puzzle, solution, 4, 4, Motif.WHITE)
        + indicator(puzzle, solution, 4, 5, Motif.WHITE)
        + indicator(puzzle, solution, 5, 4, Motif.WHITE)
    )
    f_lhs = (
        indicator(puzzle, solution, 4, 4, Motif.TRI_UL)
        + indicator(puzzle, solution, 4, 5, Motif.WHITE)
        + indicator(puzzle, solution, 5, 4, Motif.WHITE)
    )
    rhs = (
        indicator(puzzle, solution, 5, 5, Motif.WHITE)
        + indicator(puzzle, solution, 5, 5, Motif.TRI_BR)
        + 2
    )
    return d_lhs, rhs, f_lhs, rhs


def build_model(
    puzzle: ShakashakaPuzzle,
    *,
    corrected: bool,
) -> IPSolver:
    solver = IPSolver(puzzle, corrected=corrected)
    solver.build()
    configure_scip(solver.model, num_threads=1, random_seed=1)
    return solver


def force_defective_corner(solver: IPSolver) -> None:
    for row, column, motif in DEFECTIVE_CORNER:
        solver.model.addCons(solver.x[(row, column, int(motif))] == 1)


def main() -> int:
    name, puzzle = load_instance(DATA_PATH, 1199)

    published = build_model(puzzle, corrected=False)
    force_defective_corner(published)
    if published.solve() is not True or published.solution is None:
        raise RuntimeError("A-E rejected the defective corner")
    invalid_solution = published.solution
    violations = check_solution(puzzle, invalid_solution)
    if not violations:
        raise RuntimeError("A-E unexpectedly returned a valid solution")

    expected_corner = (
        Motif.TRI_UL,
        Motif.WHITE,
        Motif.WHITE,
        Motif.BLACK,
    )
    actual_corner = tuple(
        motif_at(puzzle, invalid_solution, row, col)
        for row, col in ((4, 4), (4, 5), (5, 4), (5, 5))
    )
    if actual_corner != expected_corner:
        raise RuntimeError(
            "A-E returned a different witness at the inspected corner: "
            f"{actual_corner}"
        )

    d_lhs, d_rhs, f_lhs, f_rhs = corner_values(puzzle, invalid_solution)
    if d_lhs > d_rhs:
        raise RuntimeError("the A-E witness does not satisfy family D")
    if f_lhs <= f_rhs:
        raise RuntimeError("family F does not reject the A-E witness")

    blocked = build_model(puzzle, corrected=True)
    force_defective_corner(blocked)
    if blocked.solve() is not False:
        raise RuntimeError("family F did not reject the defective corner")

    corrected = build_model(puzzle, corrected=True)
    if corrected.solve() is not True or corrected.solution is None:
        raise RuntimeError("A-F unexpectedly reported the instance infeasible")
    valid_solution = corrected.solution
    corrected_violations = check_solution(puzzle, valid_solution)
    if corrected_violations:
        raise RuntimeError(
            "A-F returned an invalid solution: "
            + "; ".join(corrected_violations)
        )

    print(f"Instance: {name}")
    print(
        "A-E: feasible, but rejected by the geometric validator "
        f"({len(violations)} violation(s))"
    )
    print(f"Family D at the defective corner: {d_lhs} <= {d_rhs}")
    print(f"Family F at the same corner:       {f_lhs} <= {f_rhs} (false)")
    print("A-F: feasible and accepted by the geometric validator")
    print(
        "Model sizes (variables, constraints): "
        f"A-E=({published.num_vars}, {published.num_conss}), "
        f"A-F=({corrected.num_vars}, {corrected.num_conss})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
