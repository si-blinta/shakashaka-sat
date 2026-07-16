"""
Generate valid Shakashaka puzzles by placing black cells and verifying solvability.
"""

from __future__ import annotations

import random
from typing import Optional

from puzzle import ShakashakaPuzzle
from solver import ShakashakaSolver


def generate_puzzle(
    inner_rows: int,
    inner_cols: int | None = None,
    num_black: int = 0,
    num_indexed: int = 0,
    seed: Optional[int] = None,
    max_attempts: int = 1000,
) -> Optional[ShakashakaPuzzle]:
    """
    Generate a valid (satisfiable) Shakashaka puzzle.

    Places black cells and indexed cells randomly, then verifies solvability.
    If inner_cols is None, defaults to inner_rows (square grid).
    """
    if inner_cols is None:
        inner_cols = inner_rows
    rng = random.Random(seed)
    nrows = inner_rows + 2
    ncols = inner_cols + 2

    for _ in range(max_attempts):
        # Pick random interior positions for black cells
        positions = [
            (i, j)
            for i in range(2, nrows)
            for j in range(2, ncols)
        ]
        rng.shuffle(positions)

        if num_black + num_indexed > len(positions):
            return None

        black_positions = set(positions[:num_black + num_indexed])
        indexed_positions = positions[num_black:num_black + num_indexed]

        indexed_cells = {}
        for pos in indexed_positions:
            # Count max possible neighbors (for valid index range)
            puzzle_temp = ShakashakaPuzzle(nrows=nrows, ncols=ncols, black_cells=black_positions)
            neighbors = puzzle_temp.neighbors(pos[0], pos[1])
            max_tri = len(neighbors)
            indexed_cells[pos] = rng.randint(0, min(4, max_tri))

        puzzle = ShakashakaPuzzle(
            nrows=nrows,
            ncols=ncols,
            black_cells=black_positions,
            indexed_cells=indexed_cells,
        )

        # Check solvability
        solver = ShakashakaSolver(puzzle)
        if solver.solve():
            return puzzle

    return None


def save_puzzle(puzzle: ShakashakaPuzzle, path: str):
    """Save puzzle to text file."""
    ir, ic = puzzle.inner_rows, puzzle.inner_cols
    if ir == ic:
        lines = [str(ir)]
    else:
        lines = [f"{ir} {ic}"]
    for i in range(2, puzzle.nrows):
        row = []
        for j in range(2, puzzle.ncols):
            if (i, j) in puzzle.indexed_cells:
                row.append(str(puzzle.indexed_cells[(i, j)]))
            elif (i, j) in puzzle.black_cells:
                row.append("#")
            else:
                row.append(".")
        lines.append("".join(row))

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Shakashaka puzzles")
    parser.add_argument("rows", type=int, help="Inner rows")
    parser.add_argument(
        "cols", type=int, nargs="?", default=None, help="Inner cols (default=rows)"
    )
    parser.add_argument(
        "--black", type=int, default=2, help="Number of unindexed black cells"
    )
    parser.add_argument(
        "--indexed", type=int, default=1, help="Number of indexed black cells"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--output", "-o", required=True, help="Output file path")
    args = parser.parse_args()

    cols = args.cols or args.rows
    print(f"Generating {args.rows}x{cols} puzzle (black={args.black}, indexed={args.indexed})...")
    puzzle = generate_puzzle(
        inner_rows=args.rows,
        inner_cols=cols,
        num_black=args.black,
        num_indexed=args.indexed,
        seed=args.seed,
    )

    if puzzle is None:
        print("Failed to generate a valid puzzle.")
    else:
        save_puzzle(puzzle, args.output)
        print(f"Saved to {args.output}")
        print(puzzle.display_puzzle())
