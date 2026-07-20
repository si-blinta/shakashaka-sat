# Shakashaka SAT artifact

This repository contains the two models and the experiments reported in the
paper:

- the CNF model, solved with CaDiCaL 1.9.5 through PySAT;
- the corrected IP model A--F, solved with SCIP through PySCIPOpt.

The repository also includes an independent geometric validator and the
`hf_1199` counterexample showing why family F is needed.

## Installation

The recorded experiments used Python 3.13.14. Install the pinned dependencies
with:

```text
python -m pip install -r requirements.txt
```

## Validation

```text
python -B test_models.py
python -B demo_ip_bug/verify_ip_bug.py
```

The first command checks the published CNF sizes, timeout recovery, and SAT
and UNSAT instances with both models. It validates each solution geometrically
and against the CNF.
The second command reproduces the invalid A--E solution on `hf_1199` and shows
that family F removes it.

## Recorded experiments

- `data/hf_instances.jsonl`: local cache of the 2,897 benchmark instances;
- `results/hf_results.csv`: the two models on all 2,897 instances;
- `results/scaling_results.csv`: the two models on the crafted family for
  `n = 5, 10, 15, 20, 25, 30, 40, 50`;
- `figures/hf_cactus.png` and `figures/scaling_artificial.png`: the figures
  used in the experimental evaluation.

Each CSV stores all three timing samples. Its adjacent metadata file records
the protocol, software versions, dataset hash, result hash, and derivation of
the published two-model subset. These recorded files are immutable; `--resume`
is intended for new files created by `benchmark.py`.

To validate the recorded files and regenerate the figures:

```text
mkdir reproduced
python -B analyze_results.py results/hf_results.csv --expected-instances 2897 --expected-repeat 3 --summary-csv reproduced/hf_summary.csv --figure reproduced/hf_cactus.png --plot cactus
python -B analyze_results.py results/scaling_results.csv --expected-instances 8 --expected-repeat 3 --summary-csv reproduced/scaling_summary.csv --figure reproduced/scaling_artificial.png --plot scaling
```

## ZKP block check

The `zkp_check/` directory contains the tool used to cross-check the
hand-made 2x2 tables of the card-based ZKP protocol for Shakashaka
(Miyahara, Robert, Lafourcade and Kaneko, FUN 2026). Each of the
6^4 = 1,296 possible 2x2 motif configurations is placed near the center of
an otherwise unconstrained board and the SAT solver decides whether it
extends to a valid solution:

```text
python -B zkp_check/test_all_cases.py 8 --quiet
```

This classifies 138 configurations as extensible and 1,158 as impossible
(written to `results_sat.txt` and `results_unsat.txt`), in agreement with
the enumeration of the FUN 2026 paper. The classification is deterministic
and independent of the board size beyond small values.

The same check is available interactively:

```text
python zkp_check/gui.py
```

Compose a 2x2 configuration and press SOLVE; on unsatisfiable
configurations the tool writes the conflicting constraint instances,
extracted from the unsatisfiable core, to `shakashaka_reason.log`, next to
the DIMACS formula and a DRAT proof.

## Re-running the experiments

The protocol uses one thread, seed 1, one warm-up, three repetitions, and a
600-second solver limit:

```text
mkdir reproduced
python -B benchmark.py hf --full --repeat 3 --timeout 600 --threads 1 --random-seed 1 --csv reproduced/hf_results.csv
python -B benchmark.py artificial --sizes 5,10,15,20,25,30,40,50 --repeat 3 --timeout 600 --threads 1 --random-seed 1 --csv reproduced/scaling_results.csv
```

Add `--resume` to continue an interrupted run. The local instance cache has
SHA-256 `0aecc8afb076adf025c36e89178827334320a0f6e55e7cf6f04370ca58da4e41`.

## Custom instances

The file passed to `benchmark.py hf --instances-jsonl` contains one JSON object
per line. Each object gives `nrows`, `ncols`, a list of one-based `[row, col]`
pairs in `black`, and an `indexed` object mapping `"row,col"` to a clue from 0
to 4. See `data/hf_instances.jsonl` for examples.

## License

See `LICENSE`.
