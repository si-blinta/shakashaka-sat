"""
Shakashaka puzzle representation and parser.

Motifs (k values):
    1 = Upper-left triangle  (black fills TL corner)
    2 = Lower-left triangle  (black fills BL corner)
    3 = Lower-right triangle (black fills BR corner)
    4 = Upper-right triangle (black fills TR corner)
    5 = White (empty)
    6 = Black
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Motif(IntEnum):
    """Cell motifs as defined in the formalization."""
    TRI_UL = 1   # Upper-left triangle
    TRI_BL = 2   # Lower-left triangle
    TRI_BR = 3   # Lower-right triangle
    TRI_UR = 4   # Upper-right triangle
    WHITE = 5     # Empty white cell
    BLACK = 6     # Black cell

    def symbol(self) -> str:
        symbols = {1: "◣", 2: "◤", 3: "◥", 4: "◢", 5: "·", 6: "■"}
        return symbols[self.value]


@dataclass
class ShakashakaPuzzle:
    """
    Represents a Shakashaka puzzle instance.

    The grid uses 1-based indexing as in the LaTeX formalization.
    nrows/ncols are the full grid sizes including border walls.
    The playable area is (2..nrows-1) x (2..ncols-1).

    black_cells: set of (i, j) positions of black cells from the puzzle statement
    indexed_cells: dict mapping (i, j) -> m for indexed black cells
    """
    nrows: int
    ncols: int
    black_cells: set[tuple[int, int]] = field(default_factory=set)
    indexed_cells: dict[tuple[int, int], int] = field(default_factory=dict)

    def __post_init__(self):
        # Validate indexed cells are a subset of black cells
        for pos in self.indexed_cells:
            if pos not in self.black_cells:
                self.black_cells.add(pos)

    @property
    def inner_rows(self) -> int:
        """Number of playable rows."""
        return self.nrows - 2

    @property
    def inner_cols(self) -> int:
        """Number of playable columns."""
        return self.ncols - 2

    def is_border(self, i: int, j: int) -> bool:
        return i == 1 or i == self.nrows or j == 1 or j == self.ncols

    def is_black(self, i: int, j: int) -> bool:
        return self.is_border(i, j) or (i, j) in self.black_cells

    def is_playable(self, i: int, j: int) -> bool:
        return (
            not self.is_black(i, j)
            and 2 <= i <= self.nrows - 1
            and 2 <= j <= self.ncols - 1
        )

    def neighbors(self, i: int, j: int) -> list[tuple[int, int]]:
        """Orthogonal neighbors within grid bounds (N(i,j) from formalization)."""
        result = []
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ni, nj = i + di, j + dj
            if 1 <= ni <= self.nrows and 1 <= nj <= self.ncols:
                result.append((ni, nj))
        return result

    @staticmethod
    def from_file(path: str | Path) -> ShakashakaPuzzle:
        """
        Parse a puzzle from a text file.

        Format:
            First line: size spec — either "rows cols" (e.g. "5 8") or a single
                        number "5" meaning 5×5.  Values are inner (playable) sizes.
            Remaining lines: grid rows (top to bottom) of the inner area.
            Characters:
                '.' = empty/playable cell
                '#' = black cell (no index)
                '0'-'4' = indexed black cell
        """
        path = Path(path)
        lines = path.read_text().strip().splitlines()
        parts = lines[0].strip().split()
        if len(parts) == 2:
            inner_rows, inner_cols = int(parts[0]), int(parts[1])
        else:
            inner_rows = inner_cols = int(parts[0])
        nrows = inner_rows + 2
        ncols = inner_cols + 2

        black_cells: set[tuple[int, int]] = set()
        indexed_cells: dict[tuple[int, int], int] = {}

        for row_idx, line in enumerate(lines[1:], start=2):  # 1-based, offset by border
            for col_idx, ch in enumerate(line.strip(), start=2):
                if ch == '.':
                    continue
                elif ch == '#':
                    black_cells.add((row_idx, col_idx))
                elif ch in "01234":
                    pos = (row_idx, col_idx)
                    black_cells.add(pos)
                    indexed_cells[pos] = int(ch)
                else:
                    raise ValueError(
                        f"unknown character {ch!r} at row {row_idx}, "
                        f"column {col_idx}"
                    )

        return ShakashakaPuzzle(
            nrows=nrows,
            ncols=ncols,
            black_cells=black_cells,
            indexed_cells=indexed_cells,
        )

    def display_puzzle(self) -> str:
        """Display the puzzle grid."""
        lines = []
        for i in range(1, self.nrows + 1):
            row = []
            for j in range(1, self.ncols + 1):
                if self.is_border(i, j):
                    row.append("■")
                elif (i, j) in self.indexed_cells:
                    row.append(str(self.indexed_cells[(i, j)]))
                elif (i, j) in self.black_cells:
                    row.append("■")
                else:
                    row.append("·")
            lines.append(" ".join(row))
        return "\n".join(lines)
