"""
Scaling benchmark on the artificial 2n x 2n family of Demaine et al.
(Fig. 11-12 of the IEICE 2014 paper): SAT encoding (Glucose 4 via PySAT)
vs the corrected 0-1 IP model A-F (SCIP via PySCIPOpt).

The SAT side is run for every n; the IP side only up to --ip-max (its
Theta(n^3) constraint family makes even *building* the model impractical
beyond that).  Each measurement is the median of --repeat runs.

Usage:
    python scaling_bench.py --sizes 5,10,15,20,25,30,40,50 --ip-max 40 \
                            --timeout 600 --repeat 3 --csv scaling_artificial.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from statistics import median

from artificial import artificial_instance
from solver import ShakashakaSolver
from ip_solver import IPSolver
from geometry_check import check_solution

HEADER = ["n", "grid", "playable",
          "sat_vars", "sat_clauses", "sat_encode_ms", "sat_solve_ms", "sat_result",
          "ip_vars", "ip_conss", "ip_nonzeros", "ip_build_ms", "ip_solve_ms", "ip_result",
          "sat_valid", "ip_valid"]


def bench_one(n: int, timeout: float, repeat: int, run_ip: bool,
              run_sat: bool = True) -> dict:
    puzzle = artificial_instance(n)
    playable = sum(1 for i in range(1, puzzle.nrows + 1)
                   for j in range(1, puzzle.ncols + 1)
                   if puzzle.is_playable(i, j))

    row = dict.fromkeys(HEADER, "")
    row.update(n=n, grid=f"{puzzle.nrows}x{puzzle.ncols}", playable=playable)

    # ---- SAT ----
    enc_ts, sol_ts = [], []
    sat_valid = ""
    for _ in range(repeat if run_sat else 0):
        t0 = time.perf_counter()
        sat = ShakashakaSolver(puzzle)
        sat.encoder.encode()
        enc_ts.append((time.perf_counter() - t0) * 1000)
        res = sat.solve(time_limit=timeout)
        sol_ts.append(sat.solve_time * 1000)
    if run_sat:
        if res and sat.solution is not None:
            sat_valid = "OK" if not check_solution(puzzle, sat.solution) else "INVALID"
        row.update(sat_vars=sat.encoder.num_vars,
                   sat_clauses=sat.encoder.num_clauses,
                   sat_encode_ms=f"{median(enc_ts):.1f}",
                   sat_solve_ms=f"{median(sol_ts):.1f}",
                   sat_result={True: "SAT", False: "UNSAT", None: "TIMEOUT"}[res],
                   sat_valid=sat_valid)

    # ---- IP (corrected model A-F) ----
    if run_ip:
        b_ts, s_ts = [], []
        ip_valid = ""
        for _ in range(repeat):
            ip = IPSolver(puzzle, corrected=True)
            ip.build()
            b_ts.append(ip.build_time * 1000)
            ipres = ip.solve(time_limit=timeout)
            s_ts.append(ip.solve_time * 1000)
            if ipres is None:
                break
        if ipres and ip.solution is not None:
            ip_valid = "OK" if not check_solution(puzzle, ip.solution) else "INVALID"
        row.update(ip_vars=ip.num_vars, ip_conss=ip.num_conss,
                   ip_nonzeros=ip.num_nonzeros,
                   ip_build_ms=f"{median(b_ts):.1f}",
                   ip_solve_ms=f"{median(s_ts):.1f}",
                   ip_result={True: "SAT", False: "UNSAT", None: "TIMEOUT"}[ipres],
                   ip_valid=ip_valid)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="5,10,15,20,25,30,40,50")
    ap.add_argument("--ip-max", type=int, default=40)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--csv", default="scaling_artificial.csv")
    ap.add_argument("--ip-only", action="store_true")
    args = ap.parse_args()

    sizes = [int(s) for s in args.sizes.split(",")]
    new = not os.path.exists(args.csv)
    with open(args.csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        if new:
            w.writeheader()
            f.flush()
        for n in sizes:
            rep = args.repeat if n <= 30 else 1
            row = bench_one(n, args.timeout, rep, run_ip=(n <= args.ip_max),
                            run_sat=not args.ip_only)
            w.writerow(row)
            f.flush()
            print(f"n={n:4d} grid={row['grid']:>9} | SAT enc {row['sat_encode_ms']}ms "
                  f"solve {row['sat_solve_ms']}ms [{row['sat_valid']}] | "
                  f"IP build {row['ip_build_ms']}ms solve {row['ip_solve_ms']}ms "
                  f"[{row['ip_valid']}] conss={row['ip_conss']}", flush=True)


if __name__ == "__main__":
    main()
