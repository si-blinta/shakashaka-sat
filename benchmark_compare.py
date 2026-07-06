"""
Benchmark: SAT encoding (ours, Glucose4) vs 0-1 IP model (Demaine et al., SCIP).

Modes
-----
  python benchmark_compare.py artificial --n 5 [--timeout 600] [--csv FILE]
      Run one artificial 2n x 2n instance (Fig. 9 of Demaine et al.) with both
      solvers and append a CSV row.

  python benchmark_compare.py hf [--limit K] [--full] [--timeout 600] [--csv FILE]
      Run the shakashaka instances of the HuggingFace dataset
      bluecoconut/pencil-puzzle-bench (golden_300.jsonl by default,
      full_dataset.jsonl with --full), loaded with the same method as
      verify_hf.py (datasets.load_dataset). Falls back to a local jsonl file
      next to this script when the Hub is unreachable.

CSV columns:
  family,name,rows,cols,playable,
  sat_vars,sat_clauses,sat_encode_ms,sat_solve_ms,sat_result,
  ip_vars,ip_conss,ip_nonzeros,ip_build_ms,ip_solve_ms,ip_result,
  agree,ip_valid
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

from puzzle import ShakashakaPuzzle
from solver import ShakashakaSolver
from ip_solver import IPSolver
from artificial import artificial_instance
from test_ip_equiv import check_assignment_against_cnf

HEADER = ["family", "name", "rows", "cols", "playable",
          "sat_vars", "sat_clauses", "sat_encode_ms", "sat_solve_ms", "sat_result",
          "ip_vars", "ip_conss", "ip_nonzeros", "ip_build_ms", "ip_solve_ms", "ip_result",
          "agree", "ip_valid"]


def run_pair(family: str, name: str, puzzle: ShakashakaPuzzle,
             timeout: float, repeat: int = 1) -> dict:
    """Run both solvers `repeat` times on the same instance and report the
    median of each timing (solvers are deterministic; repetitions only smooth
    out system noise)."""
    from statistics import median

    playable = sum(1 for i in range(1, puzzle.nrows + 1)
                   for j in range(1, puzzle.ncols + 1)
                   if puzzle.is_playable(i, j))

    sat_encode_times, sat_solve_times = [], []
    ip_build_times, ip_solve_times = [], []

    for _ in range(max(1, repeat)):
        # ---- SAT ----
        t0 = time.perf_counter()
        sat = ShakashakaSolver(puzzle)
        sat.encoder.encode()
        sat_encode_times.append((time.perf_counter() - t0) * 1000)
        sat_res = sat.solve(time_limit=timeout)   # same limit as the IP side
        sat_solve_times.append(sat.solve_time * 1000)

        # ---- IP ----
        ip = IPSolver(puzzle)
        ip.build()
        ip_res = ip.solve(time_limit=timeout)
        ip_build_times.append(ip.build_time * 1000)
        ip_solve_times.append(ip.solve_time * 1000)

        if ip_res is None or sat_res is None:   # timeout: no point repeating
            break

    ip_result = {True: "SAT", False: "UNSAT", None: "TIMEOUT"}[ip_res]
    sat_result = {True: "SAT", False: "UNSAT", None: "TIMEOUT"}[sat_res]
    agree = (ip_res is None) or (sat_res is None) or (sat_res == ip_res)
    ip_valid = ""
    if ip_res:
        ip_valid = check_assignment_against_cnf(puzzle, ip.solution)

    return dict(zip(HEADER, [
        family, name, puzzle.nrows, puzzle.ncols, playable,
        sat.encoder.num_vars, sat.encoder.num_clauses,
        f"{median(sat_encode_times):.2f}", f"{median(sat_solve_times):.2f}",
        sat_result,
        ip.num_vars, ip.num_conss, ip.num_nonzeros,
        f"{median(ip_build_times):.2f}", f"{median(ip_solve_times):.2f}",
        ip_result,
        int(agree), ip_valid,
    ]))


def append_rows(path: str, rows: list[dict]):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


# --------------------------------------------------------------------- #
# HF dataset loading (via Hugging Face 'datasets' library)
# --------------------------------------------------------------------- #

def load_hf_puzzles(limit: int | None, use_full: bool = False):
    from verify_hf import decode_puzz_link
    from datasets import load_dataset

    # Choix du dataset selon les paramètres
    data_file = "full_dataset.jsonl" if use_full else "golden_300.jsonl"
    print(f"Loading bluecoconut/pencil-puzzle-bench ({data_file}) from Hugging Face...", flush=True)

    # Importation via l'API Hugging Face
    ds = load_dataset(
        "bluecoconut/pencil-puzzle-bench",
        data_files=data_file,
        split="train",
    )

    puzzles = []
    for row in ds:
        if row.get("pid") != "shakashaka":
            continue
        try:
            # On décode l'URL puzz.link en un objet ShakashakaPuzzle
            puzzle = decode_puzz_link(row["puzzlink_url"])
            puzzles.append((row, puzzle))
            
            # Arrêt anticipé si une limite est atteinte
            if limit and len(puzzles) >= limit:
                break
        except Exception as e:
            # On ignore l'instance en cas d'erreur de décodage (comme dans verify_hf.py)
            pass

    return data_file, puzzles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["artificial", "hf"])
    ap.add_argument("--n", type=int, help="artificial size parameter")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--repeat", type=int, default=1,
                    help="measurement repetitions per instance (median reported)")
    ap.add_argument("--csv", default=None)
    # Ajout du paramètre --full pour imiter verify_hf.py
    ap.add_argument("--full", action="store_true", help="Use full_dataset instead of golden_300")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))

    if args.mode == "artificial":
        assert args.n, "--n required"
        csv_path = args.csv or os.path.join(here, "bench_artificial.csv")
        puzzle = artificial_instance(args.n)
        row = run_pair("artificial", f"n={args.n}", puzzle, args.timeout,
                       repeat=args.repeat)
        append_rows(csv_path, [row])
        print(f"n={args.n}: SAT {row['sat_solve_ms']}ms ({row['sat_result']}) | "
              f"IP build {row['ip_build_ms']}ms solve {row['ip_solve_ms']}ms "
              f"({row['ip_result']}) | conss={row['ip_conss']} "
              f"nnz={row['ip_nonzeros']} | agree={row['agree']} valid={row['ip_valid']}")
    else:
        # Configuration des résultats HF
        label = "full_dataset" if args.full else "golden_300"
        csv_path = args.csv or os.path.join(here, f"results_compare_hf_{label}.csv")
        
        # Appel de la nouvelle fonction
        fname, puzzles = load_hf_puzzles(args.limit, args.full)
        
        print(f"{len(puzzles)} shakashaka instances from {fname}")
        rows = []
        for k, (meta, puzzle) in enumerate(puzzles, 1):
            name = f"hf_{k}_{meta.get('difficulty', '')}".rstrip("_")
            row = run_pair("hf", name, puzzle, args.timeout,
                           repeat=args.repeat)
            rows.append(row)
            print(f"  [{k}/{len(puzzles)}] {row['rows']}x{row['cols']} "
                  f"SAT {row['sat_solve_ms']}ms | IP {row['ip_solve_ms']}ms "
                  f"(build {row['ip_build_ms']}ms) agree={row['agree']} "
                  f"valid={row['ip_valid']}")
        append_rows(csv_path, rows)
        print(f"saved -> {csv_path}")


if __name__ == "__main__":
    main()
