# Shakashaka SAT artifact

This repository contains the SAT encoding, the corrected A-F model, and the
experiments reported in the paper. The benchmark compares both models with
CaDiCaL 1.9.5, CP-SAT, and SCIP.

## Contents

| Path | Purpose |
| --- | --- |
| `puzzle.py` | Puzzle representation and input parser |
| `encoder.py` | Local CNF encoding |
| `demaine_cnf.py` | Direct, auxiliary-free CNF translation of A-F |
| `ip_solver.py` | A-E IP model and corrective family F |
| `solver_backends.py` | CaDiCaL, CP-SAT, and SCIP adapters |
| `geometry_check.py` | Independent solution validator |
| `puzzlink.py` | Decoder for Shakashaka puzz.link URLs |
| `artificial.py` | Crafted scaling family |
| `benchmark_solver_matrix.py` | Resumable six-configuration benchmark |
| `analyze_solver_matrix.py` | Result validation, summaries, and figures |
| `test_*.py` | Cross-model and backend tests |
| `demo_ip_bug/` | Reproduction of the A-E counterexample |
| `data/` | Immutable cache of the 2,897 benchmark instances |
| `results/` | Raw measurements, metadata, and summaries |
| `figures/` | Figures generated from the recorded measurements |

`generator.py` and `solver.py` support the tests, while `puzzlink.py` decodes
dataset URLs. `solver.py` is the small reference PySAT solver; the paper
benchmarks use the adapters in `solver_backends.py`.

## Installation

The recorded campaign used Python 3.13.14. Install the pinned dependencies with:

```text
python -m pip install -r requirements.txt
```

## Validation

Run the complete local checks without creating bytecode files:

```text
python -B test_demaine_cnf.py
python -B test_ip_equiv.py
python -B test_solver_backends.py
python -B demo_ip_bug/verify_ip_bug.py
```

The first three commands validate the cardinality translation, agreement
between the two models, SAT/UNSAT verdicts, decoded solutions, and backend
timeouts. The demonstration shows that A-E accepts an invalid assignment on
`hf_1199` and that family F removes it.

## Recorded results

The committed matrices contain one row per instance and configuration:

- `results/solver_matrix_hf.csv`: 2,897 instances and six configurations;
- `results/solver_matrix_scaling.csv`: eight crafted sizes and six
  configurations.

Each adjacent `.meta.json` file records the software versions, protocol,
dataset hash, and composition provenance. The Demaine/CaDiCaL rows were
measured in a separate campaign under the same machine and protocol; the
campaigns were not interleaved.

Validate the matrices and regenerate both figures:

```text
mkdir reproduced
python -B analyze_solver_matrix.py results/solver_matrix_hf.csv --expected-instances 2897 --expected-repeat 3 --summary-csv reproduced/hf_summary.csv --figure reproduced/hf_cactus.png --metric total_ms --plot cactus
python -B analyze_solver_matrix.py results/solver_matrix_scaling.csv --expected-instances 8 --expected-repeat 3 --summary-csv reproduced/scaling_summary.csv --figure reproduced/scaling.png --metric total_ms --plot scaling
```

The plots use the paired total time
`median(build_i + solve_i)`. Every returned solution is checked by the
geometric validator and against the reference CNF.

## Re-running the benchmark

The full protocol uses one thread, seed 1, one warm-up, three repetitions, and
a 600-second solver limit:

```text
mkdir reproduced
python -B benchmark_solver_matrix.py hf --full --instances-jsonl data/hf_instances.jsonl --repeat 3 --timeout 600 --threads 1 --random-seed 1 --csv reproduced/solver_matrix_hf.csv
python -B benchmark_solver_matrix.py artificial --sizes 5,10,15,20,25,30,40,50 --repeat 3 --timeout 600 --threads 1 --random-seed 1 --csv reproduced/solver_matrix_scaling.csv
```

Add `--resume` to continue an interrupted run. The HF cache has SHA-256
`0aecc8afb076adf025c36e89178827334320a0f6e55e7cf6f04370ca58da4e41`.

## Instance format

An instance starts with `rows [cols]`, followed by one line per row. Use `.`
for a white cell, `#` for an unnumbered black cell, or a digit from 0 to 4 for
a clue.

## License

See `LICENSE`.
