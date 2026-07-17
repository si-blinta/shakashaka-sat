"""Load the cached pencil-puzzle-bench instances."""

from __future__ import annotations

import json
from pathlib import Path

from puzzle import ShakashakaPuzzle


def _puzzle_from_record(record: dict) -> ShakashakaPuzzle:
    required = {"nrows", "ncols", "black", "indexed"}
    missing = required - set(record)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")

    black_cells = {
        tuple(map(int, coordinates)) for coordinates in record["black"]
    }
    indexed_cells = {
        tuple(map(int, coordinates.split(","))): int(clue)
        for coordinates, clue in record["indexed"].items()
    }
    return ShakashakaPuzzle(
        nrows=int(record["nrows"]),
        ncols=int(record["ncols"]),
        black_cells=black_cells,
        indexed_cells=indexed_cells,
    )


def load_instances(path: Path) -> list[tuple[str, ShakashakaPuzzle]]:
    """Load all cached instances in their benchmark order."""

    instances = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                puzzle = _puzzle_from_record(record)
            except Exception as exc:
                raise ValueError(
                    f"invalid instance at line {line_number} in {path}"
                ) from exc
            instances.append((f"hf_{len(instances) + 1}", puzzle))

    if not instances:
        raise ValueError(f"no instances in {path}")
    return instances


def load_instance(
    path: Path,
    index: int,
) -> tuple[str, ShakashakaPuzzle]:
    """Load one instance by its one-based benchmark index."""

    if index < 1:
        raise ValueError("instance index must be positive")
    instances = load_instances(path)
    try:
        return instances[index - 1]
    except IndexError as exc:
        raise IndexError(
            f"instance {index} is outside the cache of {len(instances)} instances"
        ) from exc
