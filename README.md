# Shakashaka as a SAT Problem - Artifact

SAT-based solver for the Shakashaka pencil puzzle, with a complete comparison
against the 0-1 integer-programming (IP) model of Demaine, Okamoto, Uehara,
and Uno (IEICE Transactions on Fundamentals, 2014). This is the companion
artifact of an anonymous ICTAI 2026 submission.

## Contents

```text
puzzle.py               instance representation
encoder.py              CNF encoding described in the paper
solver.py               SAT solving with Glucose 4 via PySAT
ip_solver.py            published IP model A-E and corrected model A-F
                        with SCIP via PySCIPOpt
geometry_check.py       independent geometric solution validator
artificial.py           crafted 2n x 2n scaling family
generator.py            random satisfiable-instance generator

test_ip_equiv.py        SAT/IP cross-validation suite
demo_ip_bug/verify_ip_bug.py
                        reproducible counterexample to the published IP model
verify_hf.py            validation against pencil-puzzle-bench

benchmark_compare.py    SAT vs IP benchmark on 2,897 public instances
scaling_bench.py        SAT vs IP benchmark on the crafted family
make_figures.py         regenerates Figures 12 and 13

results_compare_hf_full_dataset.csv   2,897-instance benchmark results
scaling_artificial.csv                crafted-family benchmark results
```

## Installation

```text
pip install -r requirements.txt
```

## Validation

```text
python test_ip_equiv.py
python demo_ip_bug/verify_ip_bug.py
```

The first command cross-validates the SAT and corrected IP formulations. The
second reproduces the instance on which the published A-E model accepts an
invalid solution, rejects it with the independent geometric validator, and
checks that the corrected A-F model returns a valid solution.

## Reproducing the experiments

Public benchmark:

```text
python benchmark_compare.py hf --full --repeat 3
```

Crafted scaling family:

```text
python scaling_bench.py --sizes 5,10,15,20,25,30,40,50,60 --ip-max 60 --timeout 600 --repeat 3
python scaling_bench.py --sizes 80,100 --ip-max 0 --repeat 1
```

Regenerate the figures from the committed CSV files:

```text
python make_figures.py
```

## Solving an instance programmatically

```python
from puzzle import ShakashakaPuzzle
from solver import ShakashakaSolver
from geometry_check import check_solution

puzzle = ShakashakaPuzzle.from_file("instance.txt")
solver = ShakashakaSolver(puzzle)
if solver.solve():
    assert not check_solution(puzzle, solver.solution)
    print(solver.display_solution())
```

The instance format starts with `rows [cols]`, followed by one row per grid
line using `.` for white cells, `#` for unnumbered black cells, and `0`-`4`
for clue cells.

## CSV columns

`sat_vars`, `sat_clauses`, `sat_encode_ms`, `sat_solve_ms`, and `sat_result`
describe the SAT side. `ip_vars`, `ip_conss`, `ip_nonzeros`, `ip_build_ms`,
`ip_solve_ms`, and `ip_result` describe the IP side. `agree` records matching
verdicts, while `*_valid` records validation by the independent geometric
checker. Reported times are medians over the repetitions.
