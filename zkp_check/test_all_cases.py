#!/usr/bin/env python3
"""Exhaustive enumeration of all 6^4 = 1,296 possible 2x2 blocks.

Each configuration is placed near the center of an otherwise unconstrained
board and the SAT solver decides whether it extends to a valid Shakashaka
solution. The resulting SAT/UNSAT classification is the automated
counterpart of the hand-made 2x2 tables used by the card-based ZKP protocol
of Miyahara, Robert, Lafourcade and Kaneko (FUN 2026); the two lists are
written to results_sat.txt and results_unsat.txt.

Usage:
    python -B test_all_cases.py [grid_size]           # Normal mode with progress
    python -B test_all_cases.py [grid_size] --quiet   # Quiet mode (faster, no progress output)
    
Examples:
    python -B test_all_cases.py 8           # Test with 8x8 grid
    python -B test_all_cases.py 12 --quiet  # Test with 12x12 grid, quiet mode
"""

import itertools
import sys
from datetime import datetime

from block_solver import ShakashakaSolver, ShakashakaPiece, GUI_TO_SAT


# Parse arguments
QUIET_MODE = "--quiet" in sys.argv or "-q" in sys.argv

# Get grid size from arguments (default 8)
GRID_SIZE = 8
for arg in sys.argv[1:]:
    if arg not in ("--quiet", "-q"):
        try:
            GRID_SIZE = int(arg)
            if GRID_SIZE < 4:
                print("ERROR: Grid size must be at least 4")
                sys.exit(1)
        except ValueError:
            pass


K_NAMES = {
    1: "k1",
    2: "k2",
    3: "k3",
    4: "k4",
    5: "white",
    6: "black"
}


def grid_to_string(grid):
    """Convert a 2x2 grid to a string representation using k names."""
    result = []
    for row in grid:
        row_str = []
        for cell in row:
            k = GUI_TO_SAT[cell]
            row_str.append(K_NAMES[k])
        result.append(row_str)
    return result


def main():
    if not QUIET_MODE:
        print("=" * 60)
        print("SHAKASHAKA 2x2 SUBGRID EXHAUSTIVE TEST")
        print("=" * 60)
        print(f"Grid size: {GRID_SIZE}x{GRID_SIZE}")
        print(f"Start time: {datetime.now()}")
        print()

    # All possible piece values
    all_pieces = [
        ShakashakaPiece.K1,
        ShakashakaPiece.K2,
        ShakashakaPiece.K3,
        ShakashakaPiece.K4,
        ShakashakaPiece.WHITE,
        ShakashakaPiece.BLACK
    ]

    total_cases = 6 ** 4
    if not QUIET_MODE:
        print(f"Total cases to test: {total_cases}")
        print()

    sat_cases = []
    unsat_cases = []
    
    # Calculate center position for 2x2 (inside the border walls)
    center_row = GRID_SIZE // 2 - 1
    center_col = GRID_SIZE // 2 - 1
    # Ensure it's within valid range (not on borders)
    center_row = max(1, min(center_row, GRID_SIZE - 3))
    center_col = max(1, min(center_col, GRID_SIZE - 3))
    
    case_num = 0
    for combo in itertools.product(all_pieces, repeat=4):
        case_num += 1
        
        # Build 2x2 grid from combination
        grid = [
            [combo[0], combo[1]],
            [combo[2], combo[3]]
        ]
        
        # Run solver (verbose=False to suppress output)
        solver = ShakashakaSolver(
            grid, 
            output_n=GRID_SIZE, 
            verbose=False,
            input_row=center_row,
            input_col=center_col
        )
        result = solver.solve()
        is_sat = result is not None
        
        grid_str = grid_to_string(grid)
        
        if is_sat:
            sat_cases.append((grid_str, combo))
        else:
            unsat_cases.append((grid_str, combo))
        
        # Progress update every 100 cases
        if not QUIET_MODE and case_num % 100 == 0:
            print(f"Progress: {case_num}/{total_cases} ({100*case_num/total_cases:.1f}%)")

    if not QUIET_MODE:
        print()
        print("=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(f"Total cases: {total_cases}")
        print(f"SAT cases: {len(sat_cases)}")
        print(f"UNSAT cases: {len(unsat_cases)}")
        print()

    # Write SAT cases to file
    with open("results_sat.txt", "w") as f:
        f.write("SATISFIABLE CASES\n")
        f.write(f"Grid size: {GRID_SIZE}x{GRID_SIZE}\n")
        f.write("=" * 40 + "\n\n")
        for grid_str, combo in sat_cases:
            f.write(f"[{grid_str[0][0]:>5}, {grid_str[0][1]:>5}]\n")
            f.write(f"[{grid_str[1][0]:>5}, {grid_str[1][1]:>5}]\n")
            f.write("\n")
        f.write("=" * 40 + "\n")
        f.write(f"TOTAL SAT: {len(sat_cases)}\n")
    if not QUIET_MODE:
        print(f"SAT cases written to: results_sat.txt")

    # Write UNSAT cases to file
    with open("results_unsat.txt", "w") as f:
        f.write("UNSATISFIABLE CASES\n")
        f.write(f"Grid size: {GRID_SIZE}x{GRID_SIZE}\n")
        f.write("=" * 40 + "\n\n")
        for grid_str, combo in unsat_cases:
            f.write(f"[{grid_str[0][0]:>5}, {grid_str[0][1]:>5}]\n")
            f.write(f"[{grid_str[1][0]:>5}, {grid_str[1][1]:>5}]\n")
            f.write("\n")
        f.write("=" * 40 + "\n")
        f.write(f"TOTAL UNSAT: {len(unsat_cases)}\n")
    if not QUIET_MODE:
        print(f"UNSAT cases written to: results_unsat.txt")
    
    # Final summary (always print)
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Grid size: {GRID_SIZE}x{GRID_SIZE}")
    print(f"Total cases tested: {total_cases}")
    print(f"SAT cases:   {len(sat_cases):4d} ({100*len(sat_cases)/total_cases:.1f}%)")
    print(f"UNSAT cases: {len(unsat_cases):4d} ({100*len(unsat_cases)/total_cases:.1f}%)")
    if not QUIET_MODE:
        print()
        print(f"End time: {datetime.now()}")


if __name__ == "__main__":
    main()
