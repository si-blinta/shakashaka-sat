"""
Cross-validation of the IP solver (Demaine et al. model) against the SAT
solver:
  1. same SAT/UNSAT verdict on every instance;
  2. every IP solution satisfies the CNF formula Phi(I), hence is a valid
     Shakashaka solution.
"""

from __future__ import annotations

import sys

from puzzle import ShakashakaPuzzle, Motif
from encoder import SATEncoder
from solver import ShakashakaSolver
from ip_solver import IPSolver
from generator import generate_puzzle
from artificial import artificial_instance


def check_assignment_against_cnf(puzzle: ShakashakaPuzzle,
                                 solution: dict[tuple[int, int], Motif]) -> bool:
    """True iff the motif assignment satisfies every clause of Phi(I)."""
    enc = SATEncoder(puzzle)
    enc.encode()
    true_lits = set()
    for i in range(1, puzzle.nrows + 1):
        for j in range(1, puzzle.ncols + 1):
            motif = solution.get((i, j))
            if motif is None:
                return False
            for k in range(1, 7):
                v = enc._var_cache.get((i, j, k))
                if v is None:
                    continue
                if k == int(motif):
                    true_lits.add(v)
                else:
                    true_lits.add(-v)
    for clause in enc.clauses:
        if not any(lit in true_lits for lit in clause):
            return False
    return True


def run_one(name: str, puzzle: ShakashakaPuzzle) -> bool:
    sat_solver = ShakashakaSolver(puzzle)
    sat_res = sat_solver.solve()

    ip_solver = IPSolver(puzzle)
    ip_res = ip_solver.solve(time_limit=120)

    from geometry_check import check_solution

    ok = True
    if ip_res is None:
        print(f"  [{name}] IP TIMEOUT (SAT={sat_res})")
        return False
    if sat_res != ip_res:
        print(f"  [{name}] VERDICT MISMATCH: SAT={sat_res} IP={ip_res}")
        ok = False
    if sat_res:
        gerrs = check_solution(puzzle, sat_solver.solution)
        if gerrs:
            print(f"  [{name}] SAT solution GEOMETRICALLY INVALID: {gerrs[:2]}")
            ok = False
    if ip_res:
        valid = check_assignment_against_cnf(puzzle, ip_solver.solution)
        if not valid:
            print(f"  [{name}] IP solution VIOLATES the CNF formula")
            ok = False
        gerrs = check_solution(puzzle, ip_solver.solution)
        if gerrs:
            print(f"  [{name}] IP solution GEOMETRICALLY INVALID: {gerrs[:2]}")
            ok = False
    if ok:
        print(f"  [{name}] OK (sat={sat_res}, "
              f"sat_t={sat_solver.solve_time*1000:.1f}ms, "
              f"ip_t={ip_solver.solve_time*1000:.1f}ms)")
    return ok


def main() -> int:
    all_ok = True

    # artificial instances (unique solutions, known SAT)
    for n in (2, 3, 4, 5, 6):
        all_ok &= run_one(f"artificial n={n}", artificial_instance(n))

    # random generated (SAT by construction)
    for seed in range(10):
        p = generate_puzzle(6, 6, num_black=4, num_indexed=3, seed=seed)
        if p:
            all_ok &= run_one(f"random6 seed={seed}", p)

    for seed in range(5):
        p = generate_puzzle(10, 10, num_black=10, num_indexed=6, seed=100 + seed)
        if p:
            all_ok &= run_one(f"random10 seed={100+seed}", p)

    # regression test: counterexample to the published IP model (hf_1199)
    from puzzlink import decode_puzz_link
    p1199 = decode_puzz_link(
        "http://puzz.link/p?shakashaka/10/10/zs000ajaajaaj000azq")
    all_ok &= run_one("hf_1199 (IP-model counterexample)", p1199)

    # hand-made UNSAT instances
    unsat1 = ShakashakaPuzzle(nrows=6, ncols=6,
                              black_cells={(3, 3)}, indexed_cells={(3, 3): 4})
    all_ok &= run_one("unsat clue4-cornerless", unsat1)

    # clue 4 in a corner of the playable area: impossible
    unsat2 = ShakashakaPuzzle(nrows=6, ncols=6,
                              black_cells={(2, 2)}, indexed_cells={(2, 2): 3})
    all_ok &= run_one("clue3 at corner", unsat2)

    # random possibly-UNSAT: place blacks without solvability filtering
    import random
    rng = random.Random(7)
    for trial in range(15):
        nrows = ncols = 8
        cells = [(i, j) for i in range(2, nrows) for j in range(2, ncols)]
        rng.shuffle(cells)
        blacks = set(cells[:6])
        idx = {c: rng.randint(0, 4) for c in cells[6:10]}
        p = ShakashakaPuzzle(nrows=nrows, ncols=ncols,
                             black_cells=blacks | set(idx), indexed_cells=idx)
        all_ok &= run_one(f"raw8 trial={trial}", p)

    print("\nALL OK" if all_ok else "\nFAILURES PRESENT")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
