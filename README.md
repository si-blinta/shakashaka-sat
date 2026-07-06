# Shakashaka as a SAT Problem — Artifact

SAT-based solver for the Shakashaka pencil puzzle, with a complete comparison
against the 0-1 integer programming (IP) model of Demaine, Okamoto, Uehara,
and Uno (IEICE Trans. Fundamentals, 2014). Companion artifact of an anonymous
ICTAI 2026 submission.

## Contents

```
puzzle.py               instance representation (grid, black cells, clues)
encoder.py              the CNF encoding of the paper (Section IV)
solver.py               SAT solving (Glucose 4 via PySAT)
ip_solver.py            IP model of Demaine et al., families A-E + corrective
                        family F (SCIP via PySCIPOpt)
geometry_check.py       independent geometric validator (first principles,
                        no reference to clauses or inequalities)
artificial.py           the 2n x 2n scaling family of Demaine et al.
generator.py            random satisfiable instance generation

verify_local_lemma.py   mechanical verification of the case inspection in
                        the completeness proof (Theorem 1)
test_ip_equiv.py        SAT/IP cross-validation suite
demo_ip_bug/verify_ip_bug.py
                        end-to-end demonstration that the published model
                        A-E accepts an invalid solution on instance hf_1199
verify_hf.py            validates SAT solutions against the dataset's
                        reference solutions

benchmark_compare.py    SAT vs IP on bluecoconut/pencil-puzzle-bench
scaling_bench.py        SAT vs IP on the artificial scaling family
make_figures.py         regenerates the two experimental figures of the paper

results_compare_hf_full_dataset.csv   benchmark results (2,897 instances)
scaling_artificial.csv                scaling benchmark results
```

## Installation

```
pip install -r requirements.txt     # python-sat, pyscipopt, datasets, matplotlib
```

## Reproducing the results of the paper

Correctness, Section V:

```
python verify_local_lemma.py            # exhaustive case inspection
python test_ip_equiv.py                 # SAT/IP cross-validation
```

Flaw in the published IP model, Section VI:

```
python demo_ip_bug/verify_ip_bug.py
```

Runs the published model A-E on instance hf_1199, exhibits the invalid
solution it accepts, rejects that solution with the independent validator,
locates the failing constraint family, and shows that the corrected model
A-F returns a valid solution.

Experiments, Section VII (results are appended to the CSV files;
`make_figures.py` rebuilds Figures 11 and 12 from them):

```
python benchmark_compare.py hf --full --repeat 3
python scaling_bench.py --sizes 5,10,15,20,25,30,40,50,60 --ip-max 60 --timeout 600 --repeat 3
python scaling_bench.py --sizes 80,100 --ip-max 0 --repeat 1
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
    assert not check_solution(puzzle, solver.solution)   # [] = valid
    print(solver.display_solution())
```

Instance format: first line `rows [cols]`, then one line per row with
`.` (white), `#` (black), or a digit 0-4 (black cell with clue).

## CSV columns

`sat_vars, sat_clauses, sat_encode_ms, sat_solve_ms, sat_result` describe the
SAT side; `ip_vars, ip_conss, ip_nonzeros, ip_build_ms, ip_solve_ms,
ip_result` the IP side; `agree` records that both models returned the same
verdict, and `*_valid` that the returned solution passed the independent
geometric validator. Reported times are medians over the repetitions.
