"""Decode Shakashaka instances from puzz.link URLs."""

from __future__ import annotations

from puzzle import ShakashakaPuzzle


def decode_puzz_link(url: str) -> ShakashakaPuzzle:
    """Return the puzzle encoded by a Shakashaka puzz.link URL."""
    parts = url.split("?")[-1].split("/")
    if len(parts) < 4 or parts[0] != "shakashaka":
        raise ValueError(f"invalid Shakashaka puzz.link URL: {url}")

    width = int(parts[1])
    height = int(parts[2])
    encoded = parts[3]
    values = [-1] * (width * height)

    index = 0
    for char in encoded:
        if index >= len(values):
            break
        if "0" <= char <= "4":
            values[index] = int(char)
        elif "5" <= char <= "9":
            values[index] = int(char) - 5
            index += 1
        elif "a" <= char <= "e":
            values[index] = int(char, 16) - 10
            index += 2
        elif "g" <= char <= "z":
            index += int(char, 36) - 16
        elif char == ".":
            values[index] = -2
        else:
            raise ValueError(f"invalid puzz.link character: {char!r}")
        index += 1

    black_cells: set[tuple[int, int]] = set()
    indexed_cells: dict[tuple[int, int], int] = {}
    for index, value in enumerate(values):
        if value == -1:
            continue
        row, col = divmod(index, width)
        position = (row + 2, col + 2)
        black_cells.add(position)
        if value >= 0:
            indexed_cells[position] = value

    return ShakashakaPuzzle(
        nrows=height + 2,
        ncols=width + 2,
        black_cells=black_cells,
        indexed_cells=indexed_cells,
    )
