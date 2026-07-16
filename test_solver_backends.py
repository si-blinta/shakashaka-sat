"""Cross-check the six model/backend configurations used in the paper."""

from __future__ import annotations

import random
import sys

from artificial import artificial_instance
from generator import generate_puzzle
from geometry_check import check_solution
from ip_solver import IPSolver
from puzzle import ShakashakaPuzzle
from solver_backends import (
    CNFCadicalSolver,
    CNFCPSATSolver,
    CNFSCIPSolver,
    DemaineCadicalSolver,
    DemaineCPSATSolver,
    configure_scip,
)
from test_ip_equiv import check_assignment_against_cnf
from puzzlink import decode_puzz_link


TIME_LIMIT = 60.0


def _build_solvers(puzzle: ShakashakaPuzzle):
    cadical = CNFCadicalSolver(puzzle, random_seed=1)
    cadical.build()

    cnf_cp = CNFCPSATSolver(puzzle)
    cnf_cp.build()

    cnf_scip = CNFSCIPSolver(puzzle)
    cnf_scip.build()

    dem_scip = IPSolver(puzzle, corrected=True)
    dem_scip.build()
    configure_scip(dem_scip.model, num_threads=1, random_seed=1)

    dem_cadical = DemaineCadicalSolver(
        puzzle,
        corrected=True,
        random_seed=1,
    )
    dem_cadical.build()

    dem_cp = DemaineCPSATSolver(puzzle, corrected=True)
    dem_cp.build()

    # The adapters must preserve both mathematical models exactly.
    assert cnf_cp.num_vars == cadical.num_vars
    assert cnf_scip.num_vars == cadical.num_vars
    assert cnf_cp.num_constraints == cadical.num_constraints
    assert cnf_scip.num_constraints == cadical.num_constraints
    cnf_nnz = cnf_cp.num_nonzeros
    assert cadical.num_nonzeros == cnf_nnz
    assert cnf_cp.num_nonzeros == cnf_nnz
    assert cnf_scip.num_nonzeros == cnf_nnz

    assert dem_cp.num_vars == dem_scip.num_vars
    assert dem_cp.num_constraints == dem_scip.num_conss
    assert dem_cp.num_nonzeros == dem_scip.num_nonzeros
    assert dem_cadical.num_vars == dem_scip.num_vars
    assert dem_cadical.num_source_vars == dem_scip.num_vars
    assert dem_cadical.num_source_constraints == dem_scip.num_conss
    assert dem_cadical.num_source_nonzeros == dem_scip.num_nonzeros

    return [
        ("ours/cadical-1.9.5", cadical),
        ("ours/cp-sat", cnf_cp),
        ("ours/scip", cnf_scip),
        ("demaine/cadical-1.9.5", dem_cadical),
        ("demaine/scip", dem_scip),
        ("demaine/cp-sat", dem_cp),
    ]


def run_one(name: str, puzzle: ShakashakaPuzzle) -> bool:
    try:
        solvers = _build_solvers(puzzle)
    except Exception as exc:
        print(f"  [{name}] BUILD FAILURE: {type(exc).__name__}: {exc}")
        return False

    verdicts = []
    ok = True
    timings = []
    for label, solver in solvers:
        try:
            verdict = solver.solve(time_limit=TIME_LIMIT)
        except Exception as exc:
            print(f"  [{name}] {label} SOLVE FAILURE: "
                  f"{type(exc).__name__}: {exc}")
            return False
        verdicts.append(verdict)
        timings.append(f"{label}={solver.solve_time * 1000:.1f}ms")

        if verdict is None:
            print(f"  [{name}] {label} TIMEOUT/UNKNOWN")
            ok = False
        elif verdict:
            if solver.solution is None:
                print(f"  [{name}] {label} returned SAT without a solution")
                ok = False
                continue
            if not check_assignment_against_cnf(puzzle, solver.solution):
                print(f"  [{name}] {label} solution violates the reference CNF")
                ok = False
            errors = check_solution(puzzle, solver.solution)
            if errors:
                print(f"  [{name}] {label} geometrically invalid: {errors[:2]}")
                ok = False

    if any(verdict is None for verdict in verdicts):
        ok = False
    elif len(set(verdicts)) != 1:
        print(f"  [{name}] VERDICT MISMATCH: "
              + ", ".join(
                  f"{label}={verdict}"
                  for (label, _), verdict in zip(solvers, verdicts)
              ))
        ok = False

    if ok:
        print(f"  [{name}] OK ({verdicts[0]}); " + ", ".join(timings))
    return ok


def _instances():
    for n in (2, 3, 4, 5, 6):
        yield f"artificial n={n}", artificial_instance(n)

    for seed in range(5):
        puzzle = generate_puzzle(
            6, 6, num_black=4, num_indexed=3, seed=seed
        )
        if puzzle is not None:
            yield f"generated6 seed={seed}", puzzle

    for seed in range(3):
        puzzle = generate_puzzle(
            10, 10, num_black=10, num_indexed=6, seed=100 + seed
        )
        if puzzle is not None:
            yield f"generated10 seed={100 + seed}", puzzle

    yield "hf_1199", decode_puzz_link(
        "http://puzz.link/p?shakashaka/10/10/zs000ajaajaaj000azq"
    )

    yield "unsat clue4-cornerless", ShakashakaPuzzle(
        nrows=6,
        ncols=6,
        black_cells={(3, 3)},
        indexed_cells={(3, 3): 4},
    )
    yield "unsat clue3-at-corner", ShakashakaPuzzle(
        nrows=6,
        ncols=6,
        black_cells={(2, 2)},
        indexed_cells={(2, 2): 3},
    )

    rng = random.Random(7)
    for trial in range(10):
        cells = [(i, j) for i in range(2, 8) for j in range(2, 8)]
        rng.shuffle(cells)
        black = set(cells[:6])
        indexed = {cell: rng.randint(0, 4) for cell in cells[6:10]}
        yield f"raw8 trial={trial}", ShakashakaPuzzle(
            nrows=8,
            ncols=8,
            black_cells=black | set(indexed),
            indexed_cells=indexed,
        )


def main() -> int:
    timeout_solver = CNFCadicalSolver(artificial_instance(2), random_seed=1)
    timeout_solver.build()
    timeout_verdict = timeout_solver.solve(time_limit=1e-9)
    timeout_ok = (
        timeout_verdict is None and timeout_solver.status_name == "TIMEOUT"
    )
    print(
        "CaDiCaL wall-clock timeout: " + ("OK" if timeout_ok else "FAILURE")
    )

    demaine_timeout_solver = DemaineCadicalSolver(
        artificial_instance(2),
        corrected=True,
        random_seed=1,
    )
    demaine_timeout_solver.build()
    demaine_timeout_verdict = demaine_timeout_solver.solve(time_limit=1e-9)
    demaine_timeout_ok = (
        demaine_timeout_verdict is None
        and demaine_timeout_solver.status_name == "TIMEOUT"
    )
    print(
        "Demaine/CaDiCaL wall-clock timeout: "
        + ("OK" if demaine_timeout_ok else "FAILURE")
    )

    cases = list(_instances())
    passed = sum(run_one(name, puzzle) for name, puzzle in cases)
    print(f"\n{passed}/{len(cases)} solver-matrix cases passed")
    return 0 if timeout_ok and demaine_timeout_ok and passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
