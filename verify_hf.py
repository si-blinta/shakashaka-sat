"""
Benchmark our Shakashaka SAT solver against the HuggingFace pencil-puzzle-bench dataset.

Outputs a per-puzzle results table (console, CSV, and LaTeX) with:
  grid dimensions, black-cell counts, SAT formula size, solve time, difficulty, result.

Usage:
  python verify_hf.py                  # 15 puzzles from golden_300.jsonl
  python verify_hf.py 50               # first 50 from golden_300
  python verify_hf.py --full           # all 2897 puzzles from full_dataset.jsonl
  python verify_hf.py --full 100       # first 100 from full_dataset
"""

from __future__ import annotations

import base64
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from statistics import mean, median, stdev

from datasets import load_dataset

from puzzle import ShakashakaPuzzle, Motif
from solver import ShakashakaSolver

# ---------------------------------------------------------------------------
# Decryption
# ---------------------------------------------------------------------------

_XOR_KEY = b"ppbench"


def decrypt_solution(enc: str) -> dict:
    raw = base64.b64decode(enc)
    return json.loads(bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(raw)))


# ---------------------------------------------------------------------------
# puzz.link decode4Cell (reverse-engineered from puzz.link/js/pzpr.js)
# ---------------------------------------------------------------------------

def decode_puzz_link(url: str) -> ShakashakaPuzzle:
    """
    Decode a puzz.link shakashaka URL into a ShakashakaPuzzle.

    Encoding rules (from puzz.link decode4Cell):
      '0'-'4'  → black cell with constraint 0–4,          advance 1
      '5'-'9'  → black cell with constraint value–5,       advance 2
      'a'-'e'  → black cell with constraint hex_val–10,    advance 3
      'g'-'z'  → run of empty cells, advance base36(c)–15
      '.'      → plain black cell (no constraint),         advance 1
    """
    q = url.split("?")[-1]
    parts = q.split("/")
    w = int(parts[1])
    h = int(parts[2])
    encoded = parts[3] if len(parts) > 3 else ""

    total = w * h
    qnums = [-1] * total   # -1=white, -2=plain black, 0-4=constrained black

    e = 0
    for ch in encoded:
        if e >= total:
            break
        if "0" <= ch <= "4":
            qnums[e] = int(ch)
        elif "5" <= ch <= "9":
            qnums[e] = int(ch) - 5
            e += 1
        elif "a" <= ch <= "e":
            qnums[e] = int(ch, 16) - 10
            e += 2
        elif "g" <= ch <= "z":
            e += int(ch, 36) - 16
        elif ch == ".":
            qnums[e] = -2
        e += 1

    black_cells: set[tuple[int, int]] = set()
    indexed_cells: dict[tuple[int, int], int] = {}
    for idx, qnum in enumerate(qnums):
        if qnum == -1:
            continue
        r, c = divmod(idx, w)
        i, j = r + 2, c + 2
        black_cells.add((i, j))
        if qnum >= 0:
            indexed_cells[(i, j)] = qnum

    return ShakashakaPuzzle(
        nrows=h + 2, ncols=w + 2,
        black_cells=black_cells, indexed_cells=indexed_cells,
    )


# ---------------------------------------------------------------------------
# Solution decoding from puzz.link moves
# ---------------------------------------------------------------------------

def decode_solution_moves(moves_full: list[str]) -> dict[tuple[int, int], Motif]:
    """
    Build expected solution from puzz.link moves_full.
      left-click  (x.5, y.5) → triangle (quadrant → type)
      right-click (2c+1, 2r+1) → white cell
    Returned keys are 1-based with border.
    """
    solution: dict[tuple[int, int], Motif] = {}
    for move in moves_full:
        parts = move.split(",")
        if len(parts) < 4:
            continue
        action, x, y = parts[1], float(parts[2]), float(parts[3])
        if action == "left":
            col_0, row_0 = int(x / 2), int(y / 2)
            dx, dy = x % 2, y % 2
            if   dx < 1 and dy < 1:  motif = Motif.TRI_UL
            elif dx < 1:              motif = Motif.TRI_BL
            elif dy >= 1:             motif = Motif.TRI_BR
            else:                     motif = Motif.TRI_UR
            solution[(row_0 + 2, col_0 + 2)] = motif
        elif action == "right":
            xi, yi = int(x), int(y)
            solution[((yi - 1) // 2 + 2, (xi - 1) // 2 + 2)] = Motif.WHITE
    return solution


# ---------------------------------------------------------------------------
# Per-puzzle result record
# ---------------------------------------------------------------------------

@dataclass
class PuzzleResult:
    idx: int
    rows: int
    cols: int
    area: int
    n_black: int          # total black cells
    n_constrained: int    # black cells with explicit constraint
    n_playable: int       # white/playable cells
    n_triangles: int      # triangle cells in expected solution
    req_moves: int        # number_required_moves from dataset
    sat_vars: int
    sat_clauses: int
    solve_ms: float       # wall-clock solve time in ms
    passed: bool
    note: str = ""

    @property
    def size_str(self) -> str:
        return f"{self.rows}×{self.cols}"


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

def run_benchmark(puzzles: list[dict]) -> list[PuzzleResult]:
    results: list[PuzzleResult] = []
    for idx, row in enumerate(puzzles, 1):
        url = row["puzzlink_url"]
        w, h = row["width"], row["height"]

        try:
            puzzle = decode_puzz_link(url)
        except Exception as exc:
            results.append(PuzzleResult(
                idx=idx, rows=h, cols=w, area=h*w,
                n_black=0, n_constrained=0, n_playable=0,
                n_triangles=0, req_moves=row.get("number_required_moves", 0),
                sat_vars=0, sat_clauses=0, solve_ms=0.0,
                passed=False, note=f"DECODE ERR: {exc}",
            ))
            continue

        try:
            sol_data = decrypt_solution(row["solution_enc"])
        except Exception as exc:
            results.append(PuzzleResult(
                idx=idx, rows=h, cols=w, area=h*w,
                n_black=len(puzzle.black_cells), n_constrained=len(puzzle.indexed_cells),
                n_playable=h*w - len(puzzle.black_cells),
                n_triangles=0, req_moves=row.get("number_required_moves", 0),
                sat_vars=0, sat_clauses=0, solve_ms=0.0,
                passed=False, note=f"DECRYPT ERR: {exc}",
            ))
            continue

        expected = decode_solution_moves(sol_data["moves_full"])
        n_tri = sum(1 for m in expected.values() if m != Motif.WHITE)

        solver = ShakashakaSolver(puzzle)
        solver.encoder.encode()
        sat_vars    = solver.encoder.num_vars
        sat_clauses = solver.encoder.num_clauses

        sat = solver.solve(verbose=False)
        solve_ms = solver.solve_time * 1000

        if not sat:
            results.append(PuzzleResult(
                idx=idx, rows=h, cols=w, area=h*w,
                n_black=len(puzzle.black_cells), n_constrained=len(puzzle.indexed_cells),
                n_playable=h*w - len(puzzle.black_cells),
                n_triangles=n_tri, req_moves=row.get("number_required_moves", 0),
                sat_vars=sat_vars, sat_clauses=sat_clauses, solve_ms=solve_ms,
                passed=False, note="UNSAT",
            ))
            continue

        mismatches = [
            (i, j) for (i, j), exp in expected.items()
            if solver.solution.get((i, j)) != exp
        ]

        results.append(PuzzleResult(
            idx=idx, rows=h, cols=w, area=h*w,
            n_black=len(puzzle.black_cells),
            n_constrained=len(puzzle.indexed_cells),
            n_playable=h*w - len(puzzle.black_cells),
            n_triangles=n_tri,
            req_moves=row.get("number_required_moves", 0),
            sat_vars=sat_vars, sat_clauses=sat_clauses, solve_ms=solve_ms,
            passed=(len(mismatches) == 0),
            note="" if not mismatches else f"{len(mismatches)} mismatches",
        ))

    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_table(results: list[PuzzleResult]) -> None:
    """Print a human-readable results table to stdout."""
    h  = (f"{'#':>3}  {'Size':>7}  {'Area':>5}  "
          f"{'Vars':>6}  {'Clauses':>7}  "
          f"{'Time(ms)':>9}  {'Result':<8}")
    sep = "-" * len(h)
    print(sep)
    print(h)
    print(sep)
    for r in results:
        status = "PASS" if r.passed else f"FAIL  {r.note}"
        print(
            f"{r.idx:>3}  {r.size_str:>7}  {r.area:>5}  "
            f"{r.sat_vars:>6}  {r.sat_clauses:>7}  "
            f"{r.solve_ms:>9.2f}  {status}"
        )
    print(sep)


def print_summary(results: list[PuzzleResult]) -> None:
    """Print aggregate statistics."""
    n      = len(results)
    passed = sum(1 for r in results if r.passed)
    times  = [r.solve_ms for r in results if r.passed]

    print(f"\nAggregate statistics ({n} puzzles, {passed} passed, "
          f"{n-passed} failed, {100*passed/n:.1f}% pass rate)")
    if times:
        print(f"  Solve time (ms):  "
              f"min={min(times):.2f}  "
              f"max={max(times):.2f}  "
              f"mean={mean(times):.2f}  "
              f"median={median(times):.2f}"
              + (f"  std={stdev(times):.2f}" if len(times) > 1 else ""))
    vars_   = [r.sat_vars    for r in results if r.passed]
    clauses = [r.sat_clauses for r in results if r.passed]
    if vars_:
        print(f"  SAT variables:    "
              f"min={min(vars_)}  max={max(vars_)}  mean={mean(vars_):.0f}")
        print(f"  SAT clauses:      "
              f"min={min(clauses)}  max={max(clauses)}  mean={mean(clauses):.0f}")

    areas = [r.area for r in results if r.passed]
    if areas:
        print(f"  Grid area:        "
              f"min={min(areas)}  max={max(areas)}  mean={mean(areas):.0f}")


def save_csv(results: list[PuzzleResult], path: str) -> None:
    """Save results to CSV."""
    fields = [
        "#", "size", "rows", "cols", "area",
        "sat_vars", "sat_clauses",
        "solve_time_ms", "passed", "note",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in results:
            w.writerow([
                r.idx, r.size_str, r.rows, r.cols, r.area,
                r.sat_vars, r.sat_clauses,
                f"{r.solve_ms:.3f}", int(r.passed), r.note,
            ])
    print(f"\nCSV saved: {path}")


def save_latex(results: list[PuzzleResult], path: str) -> None:
    """Save a LaTeX booktabs table: #, Size, Area, Vars, Clauses, Time (ms), Result."""
    lines = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{Shakashaka benchmark results (SAT solver vs.\ "
        r"\texttt{bluecoconut/pencil-puzzle-bench} golden set).}",
        r"\label{tab:shakashaka_results}",
        r"\setlength{\tabcolsep}{5pt}",
        r"\begin{tabular}{rrrrrrr}",
        r"\toprule",
        r"\# & Size & Area & Vars & Clauses & Time\,(ms) & Result \\",
        r"\midrule",
    ]
    for r in results:
        result_cell = r"$\checkmark$" if r.passed else r"\textbf{FAIL}"
        lines.append(
            f"  {r.idx} & ${r.rows}\\times{r.cols}$ & {r.area} & "
            f"{r.sat_vars} & {r.sat_clauses} & "
            f"{r.solve_ms:.2f} & {result_cell} \\\\"
        )
    passed_results = [r for r in results if r.passed]
    if passed_results:
        times = [r.solve_ms for r in passed_results]
        lines += [
            r"\midrule",
            (f"  \\multicolumn{{6}}{{r}}{{Mean}} & "
             f"{mean(times):.2f} \\\\"),
        ]
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"LaTeX saved: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    use_full = "--full" in sys.argv
    args     = [a for a in sys.argv[1:] if not a.startswith("--")]
    limit    = int(args[0]) if args else None

    data_file = "full_dataset.jsonl" if use_full else "golden_300.jsonl"
    label     = "full_dataset" if use_full else "golden_300"

    print(f"Loading bluecoconut/pencil-puzzle-bench ({data_file}) …", flush=True)
    ds = load_dataset(
        "bluecoconut/pencil-puzzle-bench",
        data_files=data_file,
        split="train",
    )

    puzzles = [row for row in ds if row.get("pid") == "shakashaka"]
    if limit:
        puzzles = puzzles[:limit]

    n = len(puzzles)
    suffix = f"_n{n}" if (use_full and limit) else ""
    out_csv   = os.path.join(os.path.dirname(__file__),
                             f"results_shakashaka_{label}{suffix}.csv")
    out_latex = os.path.join(os.path.dirname(__file__),
                             f"results_shakashaka_{label}{suffix}.tex")

    print(f"Running benchmark on {n} shakashaka puzzles …\n", flush=True)
    results = run_benchmark(puzzles)

    print_table(results)
    print_summary(results)
    save_csv(results, out_csv)
    save_latex(results, out_latex)

    n_failed = sum(1 for r in results if not r.passed)
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
