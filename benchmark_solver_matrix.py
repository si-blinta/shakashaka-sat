"""Run the six model/backend configurations used in the paper.

    our CNF      + CaDiCaL 1.9.5
    our CNF      + CP-SAT
    our CNF      + SCIP
    Demaine A-F + CaDiCaL 1.9.5 (exact auxiliary-free CNF translation)
    Demaine A-F + SCIP
    Demaine A-F + CP-SAT

Results use a long CSV format (one row per instance/configuration), which
makes interrupted runs resumable and retains every timing sample.
Every returned solution is checked both geometrically and against the CNF.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from artificial import artificial_instance
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


BACKENDS = (
    "our-cadical",
    "our-cpsat",
    "our-scip",
    "demaine-cadical",
    "demaine-scip",
    "demaine-cpsat",
)

BACKEND_INFO = {
    "our-cadical": ("ours-cnf", "cadical195"),
    "our-cpsat": ("ours-cnf", "cp-sat"),
    "our-scip": ("ours-cnf", "scip"),
    "demaine-cadical": ("demaine-a-f", "cadical195"),
    "demaine-scip": ("demaine-a-f", "scip"),
    "demaine-cpsat": ("demaine-a-f", "cp-sat"),
}

HEADER = [
    "family",
    "instance_index",
    "name",
    "rows",
    "cols",
    "playable",
    "formulation",
    "backend",
    "config",
    "vars",
    "constraints",
    "nonzeros",
    "build_ms",
    "solve_ms",
    "engine_ms",
    "total_ms",
    "build_samples_ms",
    "solve_samples_ms",
    "engine_samples_ms",
    "total_samples_ms",
    "result",
    "geometry_valid",
    "cnf_valid",
    "repetitions",
    "statuses",
]

CRITICAL_SOURCE_FILES = (
    "benchmark_solver_matrix.py",
    "solver_backends.py",
    "demaine_cnf.py",
    "solver.py",
    "ip_solver.py",
    "encoder.py",
    "puzzle.py",
    "artificial.py",
    "geometry_check.py",
    "test_ip_equiv.py",
    "puzzlink.py",
)

VERDICT = {True: "SAT", False: "UNSAT", None: "TIMEOUT"}


def _round_samples(values: list[float]) -> list[float]:
    return [round(value, 6) for value in values]


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _source_code_fingerprint() -> dict:
    """Return an anonymous hash of the source files that define a result row."""

    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in CRITICAL_SOURCE_FILES:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"missing critical source file: {name}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "algorithm": "sha256",
        "files": list(CRITICAL_SOURCE_FILES),
        "sha256": digest.hexdigest(),
    }


def _metadata(
    args,
    selected_backends: list[str],
    source: str,
    source_sha256: str | None,
) -> dict:
    return {
        "schema_version": 2,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        # Absolute interpreter paths can contain a local account name.
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": {
            "ortools": _package_version("ortools"),
            "pyscipopt": _package_version("pyscipopt"),
            "python-sat": _package_version("python-sat"),
            "datasets": _package_version("datasets"),
            "matplotlib": _package_version("matplotlib"),
        },
        "source_code": _source_code_fingerprint(),
        "protocol": {
            "mode": args.mode,
            "source": source,
            "source_sha256": source_sha256,
            "full": bool(getattr(args, "full", False)),
            "limit": getattr(args, "limit", None),
            "start": args.start,
            "end": args.end,
            "sizes": args.sizes if args.mode == "artificial" else None,
            "backends": selected_backends,
            "repeat": args.repeat,
            "timeout_seconds": args.timeout,
            "threads": args.threads,
            "random_seed": args.random_seed,
            "warmup": args.warmup,
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _critical_protocol(meta: dict) -> dict:
    protocol = dict(meta.get("protocol", {}))
    # start/end select rows, but do not change the protocol used for each row.
    # Warm-up is intentionally retained because it can affect measured times.
    protocol.pop("start", None)
    protocol.pop("end", None)
    return protocol


def _check_resume_metadata(old_meta: dict, new_meta: dict) -> None:
    if _critical_protocol(old_meta) != _critical_protocol(new_meta):
        raise ValueError(
            "resume protocol differs from the existing metadata:\n"
            f"old={_critical_protocol(old_meta)}\n"
            f"new={_critical_protocol(new_meta)}"
        )

    for key in ("python", "packages"):
        if old_meta.get(key) != new_meta.get(key):
            raise ValueError(
                f"resume environment differs for {key}: "
                f"old={old_meta.get(key)!r}, new={new_meta.get(key)!r}"
            )

    if old_meta.get("source_code") != new_meta.get("source_code"):
        raise ValueError(
            "resume source-code fingerprint differs from the existing metadata"
        )


def _prepare_outputs(
    csv_path: Path,
    meta: dict,
    *,
    resume: bool,
) -> tuple[
    set[tuple[str, str, str]],
    dict[tuple[str, str, str], dict],
    list[str],
]:
    meta_path = csv_path.with_suffix(csv_path.suffix + ".meta.json")
    completed: set[tuple[str, str, str]] = set()
    existing_rows: dict[tuple[str, str, str], dict] = {}

    if csv_path.exists():
        if not resume:
            raise FileExistsError(
                f"{csv_path} already exists; use --resume or choose another file"
            )
        if not meta_path.exists():
            raise FileNotFoundError(f"missing metadata file: {meta_path}")
        old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        _check_resume_metadata(old_meta, meta)
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != HEADER:
                raise ValueError("existing CSV header does not match this script")
            output_header = list(reader.fieldnames)
            for row in reader:
                key = (row["family"], row["name"], row["config"])
                if key in existing_rows:
                    raise ValueError(f"duplicate existing result: {key}")
                completed.add(key)
                existing_rows[key] = row
    else:
        output_header = list(HEADER)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=output_header).writeheader()
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return completed, existing_rows, output_header


def _playable(puzzle: ShakashakaPuzzle) -> int:
    return sum(
        puzzle.is_playable(i, j)
        for i in range(1, puzzle.nrows + 1)
        for j in range(1, puzzle.ncols + 1)
    )


def _puzzle_from_record(record: dict) -> ShakashakaPuzzle:
    required = {"nrows", "ncols", "black", "indexed"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"cache record misses fields: {sorted(missing)}")
    black = {tuple(map(int, cell)) for cell in record["black"]}
    indexed = {
        tuple(map(int, key.split(","))): int(value)
        for key, value in record["indexed"].items()
    }
    return ShakashakaPuzzle(
        nrows=int(record["nrows"]),
        ncols=int(record["ncols"]),
        black_cells=black,
        indexed_cells=indexed,
    )


def _load_cached_instances(path: Path) -> list[tuple[str, ShakashakaPuzzle]]:
    instances = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                puzzle = _puzzle_from_record(record)
            except Exception as exc:
                raise ValueError(f"invalid cache record at line {line_number}") from exc
            instances.append((f"hf_{len(instances) + 1}", puzzle))
    if not instances:
        raise ValueError(f"no instances in {path}")
    return instances


def _load_hf_instances(*, full: bool) -> list[tuple[str, ShakashakaPuzzle]]:
    from datasets import load_dataset

    data_file = "full_dataset.jsonl" if full else "golden_300.jsonl"
    dataset = load_dataset(
        "bluecoconut/pencil-puzzle-bench",
        data_files=data_file,
        split="train",
    )
    instances = []
    errors = []
    for row_number, record in enumerate(dataset, 1):
        if record.get("pid") != "shakashaka":
            continue
        try:
            puzzle = decode_puzz_link(record["puzzlink_url"])
        except Exception as exc:
            errors.append((row_number, str(exc)))
            continue
        instances.append((f"hf_{len(instances) + 1}", puzzle))
    if errors:
        preview = "; ".join(f"row {n}: {msg}" for n, msg in errors[:5])
        raise RuntimeError(
            f"failed to decode {len(errors)} Shakashaka instances: {preview}"
        )
    expected = 2897 if full else 15
    if len(instances) != expected:
        raise RuntimeError(
            f"expected {expected} Shakashaka instances, found {len(instances)}"
        )
    return instances


def _make_solver(
    config: str,
    puzzle: ShakashakaPuzzle,
    *,
    threads: int,
    random_seed: int,
):
    if config == "our-cadical":
        solver = CNFCadicalSolver(puzzle, random_seed=random_seed)
        solver.build()
        return solver
    if config == "our-cpsat":
        solver = CNFCPSATSolver(
            puzzle, num_workers=threads, random_seed=random_seed
        )
        solver.build()
        return solver
    if config == "our-scip":
        solver = CNFSCIPSolver(
            puzzle, num_threads=threads, random_seed=random_seed
        )
        solver.build()
        return solver
    if config == "demaine-cadical":
        solver = DemaineCadicalSolver(
            puzzle,
            corrected=True,
            random_seed=random_seed,
        )
        solver.build()
        return solver
    if config == "demaine-scip":
        solver = IPSolver(puzzle, corrected=True)
        solver.build()
        configure_scip(
            solver.model, num_threads=threads, random_seed=random_seed
        )
        return solver
    if config == "demaine-cpsat":
        solver = DemaineCPSATSolver(
            puzzle,
            corrected=True,
            num_workers=threads,
            random_seed=random_seed,
        )
        solver.build()
        return solver
    raise ValueError(f"unknown configuration: {config}")


def _counts(config: str, solver) -> tuple[int, int, int]:
    if config == "demaine-scip":
        return solver.num_vars, solver.num_conss, solver.num_nonzeros
    return solver.num_vars, solver.num_constraints, solver.num_nonzeros


def _engine_time_ms(solver) -> float:
    return float(solver.solve_time) * 1000.0


def _status_name(config: str, solver, verdict: Optional[bool]) -> str:
    if hasattr(solver, "status_name"):
        return str(solver.status_name)
    if config == "demaine-scip":
        return str(solver.model.getStatus()).upper()
    return VERDICT[verdict]


def _is_timeout_status(config: str, status: str) -> bool:
    normalized = status.upper()
    if config in {"our-cadical", "demaine-cadical"}:
        return normalized == "TIMEOUT"
    if config in {"our-cpsat", "demaine-cpsat"}:
        return normalized == "UNKNOWN"
    return normalized == "TIMELIMIT"


def _run_backend(
    *,
    family: str,
    instance_index: int,
    name: str,
    puzzle: ShakashakaPuzzle,
    config: str,
    repeat: int,
    timeout: float,
    threads: int,
    random_seed: int,
) -> dict:
    build_samples = []
    solve_samples = []
    engine_samples = []
    verdicts = []
    statuses = []
    counts = None

    for _ in range(repeat):
        build_start = time.perf_counter()
        solver = _make_solver(
            config,
            puzzle,
            threads=threads,
            random_seed=random_seed,
        )
        build_samples.append((time.perf_counter() - build_start) * 1000.0)

        current_counts = _counts(config, solver)
        if counts is None:
            counts = current_counts
        elif current_counts != counts:
            raise RuntimeError(
                f"{name}/{config}: structural counts changed between repeats"
            )

        solve_start = time.perf_counter()
        verdict = solver.solve(time_limit=timeout)
        solve_samples.append((time.perf_counter() - solve_start) * 1000.0)
        engine_samples.append(_engine_time_ms(solver))
        status = _status_name(config, solver, verdict)
        verdicts.append(verdict)
        statuses.append(status)

        if verdict is None and not _is_timeout_status(config, status):
            raise RuntimeError(
                f"{name}/{config}: inconclusive non-timeout status {status}"
            )

        if verdict:
            if solver.solution is None:
                raise RuntimeError(f"{name}/{config}: SAT without a solution")
            geometry_errors = check_solution(puzzle, solver.solution)
            if geometry_errors:
                raise RuntimeError(
                    f"{name}/{config}: geometrically invalid solution: "
                    f"{geometry_errors[:2]}"
                )
            if not check_assignment_against_cnf(puzzle, solver.solution):
                raise RuntimeError(
                    f"{name}/{config}: solution violates the reference CNF"
                )
    definitive_verdicts = {value for value in verdicts if value is not None}
    if len(definitive_verdicts) > 1:
        raise RuntimeError(
            f"{name}/{config}: inconsistent repeated verdicts: {verdicts}"
        )
    # All requested repetitions are executed. A single timeout makes the row a
    # TIMEOUT, even if another repetition solved it, so censoring is never hidden
    # inside a median or silently reported as SAT/UNSAT.
    verdict = None if None in verdicts else verdicts[0]
    assert counts is not None

    build_median = statistics.median(build_samples)
    solve_median = statistics.median(solve_samples)
    engine_median = statistics.median(engine_samples)
    total_samples = [
        build_value + solve_value
        for build_value, solve_value in zip(build_samples, solve_samples)
    ]
    total_median = statistics.median(total_samples)
    formulation, backend = BACKEND_INFO[config]
    return {
        "family": family,
        "instance_index": instance_index,
        "name": name,
        "rows": puzzle.nrows,
        "cols": puzzle.ncols,
        "playable": _playable(puzzle),
        "formulation": formulation,
        "backend": backend,
        "config": config,
        "vars": counts[0],
        "constraints": counts[1],
        "nonzeros": counts[2],
        "build_ms": f"{build_median:.6f}",
        "solve_ms": f"{solve_median:.6f}",
        "engine_ms": f"{engine_median:.6f}",
        "total_ms": f"{total_median:.6f}",
        "build_samples_ms": json.dumps(_round_samples(build_samples)),
        "solve_samples_ms": json.dumps(_round_samples(solve_samples)),
        "engine_samples_ms": json.dumps(_round_samples(engine_samples)),
        "total_samples_ms": json.dumps(_round_samples(total_samples)),
        "result": VERDICT[verdict],
        "geometry_valid": "OK" if verdict else "",
        "cnf_valid": "OK" if verdict else "",
        "repetitions": len(verdicts),
        "statuses": json.dumps(statuses),
    }


def _append_row(path: Path, row: dict, fieldnames: list[str]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writerow(row)
        handle.flush()


def _check_instance_verdicts(
    family: str,
    name: str,
    selected_backends: list[str],
    rows: dict[tuple[str, str, str], dict],
) -> None:
    values = []
    for config in selected_backends:
        row = rows.get((family, name, config))
        if row is not None:
            values.append((config, row["result"]))
    solved = [(config, result) for config, result in values if result != "TIMEOUT"]
    if len({result for _, result in solved}) > 1:
        raise RuntimeError(
            f"{name}: verdict mismatch: "
            + ", ".join(f"{config}={result}" for config, result in values)
        )


def _warm_up(configs: list[str], *, threads: int, random_seed: int) -> None:
    puzzle = artificial_instance(2)
    print("warming up backends...", flush=True)
    for config in configs:
        solver = _make_solver(
            config, puzzle, threads=threads, random_seed=random_seed
        )
        verdict = solver.solve(time_limit=30.0)
        if verdict is not True or check_solution(puzzle, solver.solution):
            raise RuntimeError(f"warm-up failed for {config}")


def _slice_instances(
    instances: list[tuple[str, ShakashakaPuzzle]],
    *,
    start: int,
    end: Optional[int],
    limit: Optional[int],
) -> list[tuple[int, str, ShakashakaPuzzle]]:
    indexed = [
        (index, name, puzzle)
        for index, (name, puzzle) in enumerate(instances, 1)
    ]
    if start > 1:
        indexed = [item for item in indexed if item[0] >= start]
    if end is not None:
        indexed = [item for item in indexed if item[0] <= end]
    if limit is not None:
        indexed = indexed[:limit]
    return indexed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("hf", "artificial"))
    parser.add_argument(
        "--backends",
        default=",".join(BACKENDS),
        help="comma-separated configurations: " + ",".join(BACKENDS),
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=1)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--budget", type=float, help="wall-clock budget in seconds")
    parser.add_argument(
        "--warmup",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--instances-jsonl")
    parser.add_argument("--sizes", default="5,10,15,20,25,30,40,50,60,80,100")
    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.threads != 1:
        parser.error("the paper protocol requires --threads 1")
    if args.start < 1:
        parser.error("--start is one-based and must be at least 1")
    if args.budget is not None and args.budget <= 0:
        parser.error("--budget must be positive")

    selected_backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    if not selected_backends:
        parser.error("--backends must select at least one configuration")
    unknown = set(selected_backends) - set(BACKENDS)
    if unknown:
        parser.error(f"unknown backends: {sorted(unknown)}")
    if len(selected_backends) != len(set(selected_backends)):
        parser.error("duplicate backend in --backends")

    if args.mode == "hf":
        if args.instances_jsonl:
            cache_path = Path(args.instances_jsonl).resolve()
            raw_instances = _load_cached_instances(cache_path)
            source = f"local-cache:{cache_path.name}"
            source_sha256 = _sha256(cache_path)
            if args.full and len(raw_instances) != 2897:
                raise RuntimeError(
                    f"--full expects 2897 cached instances, found {len(raw_instances)}"
                )
        else:
            raw_instances = _load_hf_instances(full=args.full)
            source = (
                "bluecoconut/pencil-puzzle-bench/full_dataset.jsonl"
                if args.full
                else "bluecoconut/pencil-puzzle-bench/golden_300.jsonl"
            )
            source_sha256 = None
        instances = _slice_instances(
            raw_instances,
            start=args.start,
            end=args.end,
            limit=args.limit,
        )
        family = "hf"
    else:
        sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
        if not sizes or any(size < 1 for size in sizes):
            parser.error("--sizes must contain positive integers")
        if len(sizes) != len(set(sizes)):
            parser.error("--sizes must not contain duplicates")
        raw_instances = [
            (f"artificial_n={n}", artificial_instance(n)) for n in sizes
        ]
        instances = _slice_instances(
            raw_instances,
            start=args.start,
            end=args.end,
            limit=args.limit,
        )
        source = "artificial_instance"
        source_sha256 = None
        family = "artificial"

    if not instances:
        raise RuntimeError("the selected instance range is empty")

    csv_path = Path(args.csv).resolve()
    meta = _metadata(args, selected_backends, source, source_sha256)
    completed, rows, output_header = _prepare_outputs(
        csv_path, meta, resume=args.resume
    )

    if args.warmup:
        _warm_up(
            selected_backends,
            threads=args.threads,
            random_seed=args.random_seed,
        )

    started = time.perf_counter()
    total = len(instances)
    written = 0
    for position, (instance_index, name, puzzle) in enumerate(instances, 1):
        for config in selected_backends:
            key = (family, name, config)
            if key in completed:
                continue
            if args.budget is not None and written > 0:
                if time.perf_counter() - started >= args.budget:
                    print(
                        f"budget reached; resume with the same command and --resume",
                        flush=True,
                    )
                    return 0

            row = _run_backend(
                family=family,
                instance_index=instance_index,
                name=name,
                puzzle=puzzle,
                config=config,
                repeat=args.repeat,
                timeout=args.timeout,
                threads=args.threads,
                random_seed=args.random_seed,
            )
            _append_row(csv_path, row, output_header)
            completed.add(key)
            rows[key] = row
            written += 1
            print(
                f"[{position}/{total}] {name} {config}: {row['result']} "
                f"build={float(row['build_ms']):.2f}ms "
                f"solve={float(row['solve_ms']):.2f}ms "
                f"total={float(row['total_ms']):.2f}ms",
                flush=True,
            )

        _check_instance_verdicts(family, name, selected_backends, rows)

    print(
        f"complete: {len(instances)} instances, {written} new rows -> {csv_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
