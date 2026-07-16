"""Validate, summarize, and plot benchmark results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


CONFIGS = (
    "our-cadical",
    "our-cpsat",
    "our-scip",
    "demaine-cadical",
    "demaine-cpsat",
    "demaine-scip",
)

CONFIG_INFO = {
    "our-cadical": ("ours-cnf", "cadical195"),
    "our-cpsat": ("ours-cnf", "cp-sat"),
    "our-scip": ("ours-cnf", "scip"),
    "demaine-cadical": ("demaine-a-f", "cadical195"),
    "demaine-scip": ("demaine-a-f", "scip"),
    "demaine-cpsat": ("demaine-a-f", "cp-sat"),
}

LABELS = {
    "our-cadical": "Ours / CaDiCaL 1.9.5",
    "our-cpsat": "Ours / CP-SAT",
    "our-scip": "Ours / SCIP",
    "demaine-cadical": "Demaine A-F / CaDiCaL 1.9.5",
    "demaine-scip": "Demaine A-F / SCIP",
    "demaine-cpsat": "Demaine A-F / CP-SAT",
}

STYLES = {
    "our-cadical": ("#0072B2", "-", "o", True),
    "our-cpsat": ("#0072B2", "--", "s", True),
    "our-scip": ("#0072B2", ":", "^", True),
    "demaine-cadical": ("#D55E00", "-", "o", False),
    "demaine-cpsat": ("#D55E00", "--", "s", False),
    "demaine-scip": ("#D55E00", ":", "^", False),
}

REQUIRED_COLUMNS = {
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
}

STATUS_CLASSES = {
    "our-cadical": {
        "sat": {"SAT"},
        "unsat": {"UNSAT"},
        "timeout": {"TIMEOUT"},
    },
    "our-cpsat": {
        "sat": {"OPTIMAL", "FEASIBLE"},
        "unsat": {"INFEASIBLE"},
        "timeout": {"UNKNOWN"},
    },
    "demaine-cadical": {
        "sat": {"SAT"},
        "unsat": {"UNSAT"},
        "timeout": {"TIMEOUT"},
    },
    "demaine-cpsat": {
        "sat": {"OPTIMAL", "FEASIBLE"},
        "unsat": {"INFEASIBLE"},
        "timeout": {"UNKNOWN"},
    },
    "our-scip": {
        "sat": {"OPTIMAL"},
        "unsat": {"INFEASIBLE"},
        "timeout": {"TIMELIMIT"},
    },
    "demaine-scip": {
        "sat": {"OPTIMAL"},
        "unsat": {"INFEASIBLE"},
        "timeout": {"TIMELIMIT"},
    },
}

SUMMARY_HEADER = [
    "config",
    "instances",
    "solved",
    "timeouts",
    "build_mean_ms",
    "build_median_ms",
    "solve_mean_ms",
    "solve_median_ms",
    "solve_p95_ms",
    "solve_max_ms",
    "total_mean_ms",
    "total_median_ms",
    "total_p95_ms",
    "total_max_ms",
    "par2_solve_s",
    "par2_total_s",
]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _float(row: dict, key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{row.get('name', '?')}/{row.get('config', '?')}: "
                         f"invalid {key}={row.get(key)!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(
            f"{row.get('name', '?')}/{row.get('config', '?')}: "
            f"invalid {key}={row.get(key)!r}"
        )
    return value


def _samples(row: dict, key: str, repetitions: int) -> list[float]:
    try:
        raw = json.loads(row[key])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{row.get('name', '?')}/{row.get('config', '?')}: "
            f"invalid {key}"
        ) from exc
    if not isinstance(raw, list) or len(raw) != repetitions:
        raise ValueError(
            f"{row['name']}/{row['config']}: wrong number of {key}"
        )
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{row['name']}/{row['config']}: non-numeric {key}"
        ) from exc
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError(
            f"{row['name']}/{row['config']}: invalid value in {key}"
        )
    return values


def _statuses(row: dict, repetitions: int) -> list[str]:
    try:
        raw = json.loads(row["statuses"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{row.get('name', '?')}/{row.get('config', '?')}: invalid statuses"
        ) from exc
    if not isinstance(raw, list) or len(raw) != repetitions:
        raise ValueError(
            f"{row['name']}/{row['config']}: wrong number of statuses"
        )
    if any(not isinstance(status, str) or not status.strip() for status in raw):
        raise ValueError(f"{row['name']}/{row['config']}: invalid status value")
    return [status.upper() for status in raw]


def _validate_statuses(row: dict, statuses: list[str]) -> None:
    config = row["config"]
    result = row["result"]
    classes = STATUS_CLASSES[config]
    allowed = classes["sat"] | classes["unsat"] | classes["timeout"]
    unexpected = set(statuses) - allowed
    if unexpected:
        raise ValueError(
            f"{row['name']}/{config}: unexpected statuses {sorted(unexpected)}"
        )
    if result == "SAT" and not all(status in classes["sat"] for status in statuses):
        raise ValueError(f"{row['name']}/{config}: statuses disagree with SAT")
    if result == "UNSAT" and not all(
        status in classes["unsat"] for status in statuses
    ):
        raise ValueError(f"{row['name']}/{config}: statuses disagree with UNSAT")
    if result == "TIMEOUT":
        if not any(status in classes["timeout"] for status in statuses):
            raise ValueError(
                f"{row['name']}/{config}: TIMEOUT has no timeout status"
            )
        has_sat = any(status in classes["sat"] for status in statuses)
        has_unsat = any(status in classes["unsat"] for status in statuses)
        if has_sat and has_unsat:
            raise ValueError(
                f"{row['name']}/{config}: definitive statuses disagree"
            )


def _load(path: Path) -> tuple[list[dict], dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"missing CSV header: {path}")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"missing CSV columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"empty result file: {path}")
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    if not meta_path.exists():
        raise FileNotFoundError(f"missing metadata file: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected_hash = meta.get("csv_sha256")
    if expected_hash:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash.lower() != str(expected_hash).lower():
            raise ValueError(f"CSV hash does not match metadata: {path}")
    return rows, meta


def _validate(
    rows: list[dict],
    meta: dict,
    *,
    expected_instances: int | None,
    expected_repeat: int | None,
    allow_timeouts: bool,
) -> dict[str, list[dict]]:
    protocol = meta.get("protocol", {})
    configs = protocol.get("backends")
    if not isinstance(configs, list) or not configs:
        raise ValueError("metadata protocol must list at least one backend")
    if len(configs) != len(set(configs)):
        raise ValueError("duplicate configuration in metadata")
    if set(configs) - set(CONFIGS):
        raise ValueError(f"unknown configurations in metadata: {configs}")

    try:
        metadata_repeat = int(protocol["repeat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("metadata protocol has no valid repeat count") from exc
    if metadata_repeat < 1:
        raise ValueError("metadata repeat count must be positive")
    if expected_repeat is None:
        expected_repeat = metadata_repeat
    elif expected_repeat != metadata_repeat:
        raise ValueError(
            f"--expected-repeat={expected_repeat} disagrees with "
            f"metadata repeat={metadata_repeat}"
        )

    expected_family = protocol.get("mode")
    if expected_family not in {"hf", "artificial"}:
        raise ValueError(f"invalid metadata mode: {expected_family!r}")

    by_key = {}
    by_instance: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_config: dict[str, list[dict]] = defaultdict(list)
    index_by_name = {}

    for row in rows:
        config = row.get("config")
        if config not in configs:
            raise ValueError(f"unexpected configuration in CSV: {config}")
        formulation, backend = CONFIG_INFO[config]
        if row.get("formulation") != formulation or row.get("backend") != backend:
            raise ValueError(
                f"{row.get('name', '?')}/{config}: expected "
                f"formulation={formulation}, backend={backend}"
            )

        family = row.get("family", "")
        name = row.get("name", "")
        if family != expected_family:
            raise ValueError(
                f"{name}/{config}: family={family!r}, expected {expected_family!r}"
            )
        if not name:
            raise ValueError(f"unnamed instance for {config}")

        try:
            index = int(row["instance_index"])
            nrows = int(row["rows"])
            ncols = int(row["cols"])
            playable = int(row["playable"])
            structural_counts = tuple(
                int(row[field]) for field in ("vars", "constraints", "nonzeros")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{name}/{config}: invalid integer field") from exc
        if index < 1 or nrows < 1 or ncols < 1:
            raise ValueError(f"{name}/{config}: invalid index or dimensions")
        if not 0 <= playable <= nrows * ncols:
            raise ValueError(f"{name}/{config}: invalid playable count")
        if any(value < 0 for value in structural_counts):
            raise ValueError(f"{name}/{config}: negative structural count")
        if family == "hf" and name != f"hf_{index}":
            raise ValueError(
                f"{name}/{config}: HF name does not match instance_index={index}"
            )
        if family == "artificial":
            try:
                artificial_n = _artificial_n(row)
            except ValueError as exc:
                raise ValueError(f"{name}/{config}: invalid artificial identity") from exc
            if artificial_n < 1:
                raise ValueError(f"{name}/{config}: artificial n must be positive")

        row["_index_int"] = index
        row["_rows_int"] = nrows
        row["_cols_int"] = ncols
        row["_playable_int"] = playable
        row["_structural_counts"] = structural_counts

        key = (family, name, config)
        if key in by_key:
            raise ValueError(f"duplicate result row: {key}")
        by_key[key] = row
        instance_key = key[:2]
        by_instance[instance_key].append(row)
        by_config[config].append(row)

        previous = index_by_name.setdefault(instance_key, index)
        if previous != index:
            raise ValueError(f"inconsistent index for {instance_key}")

        try:
            repetitions = int(row["repetitions"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}/{config}: invalid repetitions") from exc
        if repetitions != expected_repeat:
            raise ValueError(
                f"{name}/{config}: {repetitions} repetitions, "
                f"expected {expected_repeat}"
            )

        result = row["result"]
        if result not in {"SAT", "UNSAT", "TIMEOUT"}:
            raise ValueError(f"{name}/{config}: invalid result {result}")
        if result == "TIMEOUT" and not allow_timeouts:
            raise ValueError(f"{name}/{config}: unexpected timeout")

        timing_samples = {}
        for sample_key, median_key in (
            ("build_samples_ms", "build_ms"),
            ("solve_samples_ms", "solve_ms"),
            ("engine_samples_ms", "engine_ms"),
        ):
            samples = _samples(row, sample_key, repetitions)
            timing_samples[sample_key] = samples
            if not math.isclose(
                statistics.median(samples),
                _float(row, median_key),
                rel_tol=1e-6,
                abs_tol=2e-6,
            ):
                raise ValueError(
                    f"{row['name']}/{config}: {median_key} is not the "
                    f"median of {sample_key}"
                )

        paired_totals = [
            build_value + solve_value
            for build_value, solve_value in zip(
                timing_samples["build_samples_ms"],
                timing_samples["solve_samples_ms"],
            )
        ]
        paired_total_median = statistics.median(paired_totals)
        recorded_total = _float(row, "total_ms")
        total_samples = _samples(row, "total_samples_ms", repetitions)
        for position, (stored, reconstructed) in enumerate(
            zip(total_samples, paired_totals), 1
        ):
            if not math.isclose(
                stored,
                reconstructed,
                rel_tol=1e-6,
                abs_tol=4e-6,
            ):
                raise ValueError(
                    f"{name}/{config}: total sample {position} is not "
                    "build+solve"
                )
        if not math.isclose(
            recorded_total,
            statistics.median(total_samples),
            rel_tol=1e-6,
            abs_tol=4e-6,
        ):
            raise ValueError(
                f"{name}/{config}: total_ms is not the paired median"
            )
        row["total_ms"] = f"{paired_total_median:.6f}"

        statuses = _statuses(row, repetitions)
        _validate_statuses(row, statuses)
        if result == "SAT":
            if row.get("geometry_valid") != "OK":
                raise ValueError(f"{row['name']}/{config}: geometry not validated")
            if row.get("cnf_valid") != "OK":
                raise ValueError(f"{row['name']}/{config}: CNF not validated")

    if expected_instances is not None and len(by_instance) != expected_instances:
        raise ValueError(
            f"found {len(by_instance)} instances, expected {expected_instances}"
        )

    for instance_key, group in by_instance.items():
        present = {row["config"] for row in group}
        if present != set(configs):
            raise ValueError(
                f"{instance_key}: configurations {sorted(present)}, "
                f"expected {sorted(configs)}"
            )
        solved_verdicts = {
            row["result"] for row in group if row["result"] != "TIMEOUT"
        }
        if len(solved_verdicts) > 1:
            raise ValueError(f"{instance_key}: verdict mismatch {solved_verdicts}")

        identities = {
            (
                row["_index_int"],
                row["_rows_int"],
                row["_cols_int"],
                row["_playable_int"],
            )
            for row in group
        }
        if len(identities) != 1:
            raise ValueError(
                f"{instance_key}: index, dimensions, or playable count differ"
            )

        structural = {row["config"]: row for row in group}
        cnf_configs = present & {"our-cadical", "our-cpsat", "our-scip"}
        if len(cnf_configs) >= 2:
            counts = {
                structural[config]["_structural_counts"]
                for config in cnf_configs
            }
            if len(counts) != 1:
                raise ValueError(f"{instance_key}: our CNF counts differ")
        if {"demaine-scip", "demaine-cpsat"} <= present:
            counts = {
                structural[config]["_structural_counts"]
                for config in ("demaine-scip", "demaine-cpsat")
            }
            if len(counts) != 1:
                raise ValueError(f"{instance_key}: Demaine A-F counts differ")
        if {
            "demaine-cadical",
            "demaine-scip",
            "demaine-cpsat",
        } <= present:
            variable_counts = {
                structural[config]["_structural_counts"][0]
                for config in (
                    "demaine-cadical",
                    "demaine-scip",
                    "demaine-cpsat",
                )
            }
            if len(variable_counts) != 1:
                raise ValueError(
                    f"{instance_key}: Demaine A-F semantic variable counts differ"
                )

    indices = sorted(index_by_name.values())
    if len(indices) != len(set(indices)):
        raise ValueError("two instances share the same instance_index")
    if indices != list(range(indices[0], indices[-1] + 1)):
        raise ValueError("instance indices are not contiguous")
    return dict(by_config)


def _summaries(
    by_config: dict[str, list[dict]], *, timeout_seconds: float
) -> list[dict]:
    def mean_or_nan(values: list[float]) -> float:
        return statistics.mean(values) if values else math.nan

    def median_or_nan(values: list[float]) -> float:
        return statistics.median(values) if values else math.nan

    def max_or_nan(values: list[float]) -> float:
        return max(values) if values else math.nan

    summaries = []
    for config in CONFIGS:
        rows = by_config.get(config)
        if not rows:
            continue
        solved = [row for row in rows if row["result"] != "TIMEOUT"]
        build = [_float(row, "build_ms") for row in rows]
        solve = [_float(row, "solve_ms") for row in solved]
        total = [_float(row, "total_ms") for row in solved]
        timeouts = len(rows) - len(solved)
        par2_solve = (
            sum(value / 1000.0 for value in solve)
            + timeouts * 2 * timeout_seconds
        ) / len(rows)
        par2_total = (
            sum(value / 1000.0 for value in total)
            + timeouts * 2 * timeout_seconds
        ) / len(rows)
        summaries.append({
            "config": config,
            "instances": len(rows),
            "solved": len(solved),
            "timeouts": timeouts,
            "build_mean_ms": mean_or_nan(build),
            "build_median_ms": median_or_nan(build),
            "solve_mean_ms": mean_or_nan(solve),
            "solve_median_ms": median_or_nan(solve),
            "solve_p95_ms": _percentile(solve, 0.95),
            "solve_max_ms": max_or_nan(solve),
            "total_mean_ms": mean_or_nan(total),
            "total_median_ms": median_or_nan(total),
            "total_p95_ms": _percentile(total, 0.95),
            "total_max_ms": max_or_nan(total),
            "par2_solve_s": par2_solve,
            "par2_total_s": par2_total,
        })
    return summaries


def _write_summary(path: Path, summaries: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_HEADER)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({
                key: (f"{value:.6f}" if isinstance(value, float) else value)
                for key, value in summary.items()
            })


def _plot_cactus(
    output: Path,
    by_config: dict[str, list[dict]],
    *,
    metric: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4.35, 3.55))
    for config in CONFIGS:
        rows = by_config.get(config)
        if not rows:
            continue
        values = sorted(
            _float(row, metric) for row in rows if row["result"] != "TIMEOUT"
        )
        color, linestyle, marker, filled = STYLES[config]
        marker_step = max(1, len(values) // 14)
        marker_offset = 0
        if config.startswith("demaine-"):
            marker_offset = max(1, marker_step // 2)
        ax.plot(
            range(1, len(values) + 1),
            values,
            color=color,
            linestyle=linestyle,
            linewidth=1.75,
            marker=marker,
            markersize=3.8,
            markerfacecolor=color if filled else "white",
            markeredgecolor=color,
            markeredgewidth=0.8,
            markevery=(marker_offset, marker_step),
            label=LABELS[config],
        )
    ax.set_yscale("log")
    ax.set_xlabel("instances solved")
    ax.set_ylabel("total time (ms)" if metric == "total_ms" else "solving time (ms)")
    ax.grid(True, which="major", alpha=0.26, linewidth=0.55)
    ax.grid(True, which="minor", alpha=0.12, linewidth=0.35)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        frameon=False,
        fontsize=6.9,
        columnspacing=0.9,
        handlelength=3.0,
        handletextpad=0.55,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.77))
    fig.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _artificial_n(row: dict) -> int:
    name = row["name"]
    marker = "artificial_n="
    if not name.startswith(marker):
        raise ValueError(f"cannot extract n from {name}")
    return int(name[len(marker):])


def _plot_scaling(
    output: Path,
    by_config: dict[str, list[dict]],
    *,
    metric: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4.35, 3.55))
    for config in CONFIGS:
        rows = by_config.get(config)
        if not rows:
            continue
        points = sorted(
            (_artificial_n(row), _float(row, metric))
            for row in rows
            if row["result"] != "TIMEOUT"
        )
        color, linestyle, marker, filled = STYLES[config]
        ax.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            color=color,
            linestyle=linestyle,
            marker=marker,
            markersize=4.2,
            markerfacecolor=color if filled else "white",
            markeredgecolor=color,
            markeredgewidth=0.85,
            linewidth=1.75,
            label=LABELS[config],
        )
    ax.set_yscale("log")
    ax.set_xlabel(r"size parameter $n$")
    ax.set_ylabel("total time (ms)" if metric == "total_ms" else "solving time (ms)")
    ax.grid(True, which="major", alpha=0.26, linewidth=0.55)
    ax.grid(True, which="minor", alpha=0.12, linewidth=0.35)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        frameon=False,
        fontsize=6.9,
        columnspacing=0.9,
        handlelength=3.0,
        handletextpad=0.55,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.77))
    fig.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _print_summary(summaries: list[dict]) -> None:
    print("config                 solved    build-med  solve-med  total-med  total-max")
    for summary in summaries:
        print(
            f"{summary['config']:<22} "
            f"{summary['solved']:>4}/{summary['instances']:<4} "
            f"{summary['build_median_ms']:>9.2f} "
            f"{summary['solve_median_ms']:>9.2f} "
            f"{summary['total_median_ms']:>9.2f} "
            f"{summary['total_max_ms']:>9.2f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--expected-instances", type=int)
    parser.add_argument("--expected-repeat", type=int)
    parser.add_argument("--allow-timeouts", action="store_true")
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--figure", required=True)
    parser.add_argument("--metric", choices=("solve_ms", "total_ms"), default="total_ms")
    parser.add_argument("--plot", choices=("cactus", "scaling"), default="cactus")
    args = parser.parse_args()

    input_path = Path(args.csv).resolve()
    rows, meta = _load(input_path)
    by_config = _validate(
        rows,
        meta,
        expected_instances=args.expected_instances,
        expected_repeat=args.expected_repeat,
        allow_timeouts=args.allow_timeouts,
    )
    timeout = float(meta.get("protocol", {}).get("timeout_seconds", 600.0))
    summaries = _summaries(by_config, timeout_seconds=timeout)
    summary_path = Path(args.summary_csv).resolve()
    figure_path = Path(args.figure).resolve()
    _write_summary(summary_path, summaries)
    if args.plot == "cactus":
        _plot_cactus(figure_path, by_config, metric=args.metric)
    else:
        _plot_scaling(figure_path, by_config, metric=args.metric)
    _print_summary(summaries)
    print(f"validated {len(rows)} rows")
    print(f"summary -> {summary_path}")
    print(f"figure  -> {figure_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
