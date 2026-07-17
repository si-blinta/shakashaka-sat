"""Focused checks for the two models compared in the paper."""

from __future__ import annotations

from pathlib import Path

from artificial import artificial_instance
from encoder import SATEncoder
from geometry_check import check_solution
from instances import load_instance
from ip_solver import IPSolver
from puzzle import Motif, ShakashakaPuzzle
from solver_backends import CNFCadicalSolver, configure_scip
from validation import check_assignment_against_cnf


DATA_PATH = Path(__file__).parent / "data" / "hf_instances.jsonl"
EXPECTED_CNF_SIZES = {
    10: (2_904, 28_508, 74_596),
    25: (16_224, 162_608, 421_936),
    50: (62_424, 630_108, 1_628_836),
}


def _build_ip(puzzle: ShakashakaPuzzle, *, corrected: bool) -> IPSolver:
    solver = IPSolver(puzzle, corrected=corrected)
    solver.build()
    configure_scip(solver.model, num_threads=1, random_seed=1)
    return solver


def check_models(puzzle: ShakashakaPuzzle, expected: bool) -> None:
    cnf = CNFCadicalSolver(puzzle, random_seed=1)
    cnf.build()
    cnf_result = cnf.solve(time_limit=30.0)
    assert cnf_result is expected

    ip = _build_ip(puzzle, corrected=True)
    ip_result = ip.solve(time_limit=30.0)
    assert ip_result is expected

    if expected:
        assert cnf.solution is not None
        assert ip.solution is not None
        assert not check_solution(puzzle, cnf.solution)
        assert not check_solution(puzzle, ip.solution)
        assert check_assignment_against_cnf(puzzle, cnf.solution)
        assert check_assignment_against_cnf(puzzle, ip.solution)


def check_encoding_sizes() -> None:
    for size, expected in EXPECTED_CNF_SIZES.items():
        encoder = SATEncoder(artificial_instance(size))
        encoder.encode()
        actual = (
            encoder.num_vars,
            encoder.num_clauses,
            sum(len(clause) for clause in encoder.clauses),
        )
        assert actual == expected


def check_cadical_timeout() -> None:
    solver = CNFCadicalSolver(artificial_instance(20), random_seed=1)
    solver.build()
    assert solver.solve(time_limit=0.000001) is None


def check_counterexample() -> None:
    name, puzzle = load_instance(DATA_PATH, 1199)
    assert name == "hf_1199"

    published = _build_ip(puzzle, corrected=False)
    defective_corner = {
        (4, 4): Motif.TRI_UL,
        (4, 5): Motif.WHITE,
        (5, 4): Motif.WHITE,
    }
    for (row, column), motif in defective_corner.items():
        published.model.addCons(
            published.x[(row, column, int(motif))] == 1
        )
    assert published.solve(time_limit=30.0) is True
    assert published.solution is not None
    witness = published.solution
    assert check_solution(puzzle, witness)
    assert not check_assignment_against_cnf(puzzle, witness)

    corrected = _build_ip(puzzle, corrected=True)
    for (row, column), motif in defective_corner.items():
        corrected.model.addCons(
            corrected.x[(row, column, int(motif))] == 1
        )
    assert corrected.solve(time_limit=30.0) is False

    repaired = _build_ip(puzzle, corrected=True)
    assert repaired.solve(time_limit=30.0) is True
    assert repaired.solution is not None
    assert not check_solution(puzzle, repaired.solution)
    assert check_assignment_against_cnf(puzzle, repaired.solution)


def main() -> int:
    check_encoding_sizes()
    check_cadical_timeout()
    check_models(artificial_instance(3), expected=True)
    impossible = ShakashakaPuzzle(
        nrows=6,
        ncols=6,
        black_cells={(2, 2)},
        indexed_cells={(2, 2): 3},
    )
    check_models(impossible, expected=False)
    check_counterexample()
    print("Model checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
