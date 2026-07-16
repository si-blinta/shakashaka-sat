"""
SAT encoder for Shakashaka puzzles.

Implements all constraints from the formalization:
    (1a) Black cell initialization
    (1b) At-most-one motif per cell
    (1c) At-least-one motif per cell
    (1d) Border walls
    (1e) No black motif for playable interior cells
    (2a-2d) Invalid diagonal continuity
    (3a-3d) Propagation rules (1) - triangle + two whites => forced corner
    (4a-4h) Propagation rules (2) - triangle adjacency propagation
    (5a-5d) Propagation rules (3) - L-shape white propagation
    Binary exclusion constraints (Table 1)
    (6a-6b) Index constraints
"""

from __future__ import annotations

from itertools import combinations

from puzzle import ShakashakaPuzzle, Motif


class SATEncoder:
    """Encodes a ShakashakaPuzzle into CNF clauses using the paper's formalization."""

    def __init__(self, puzzle: ShakashakaPuzzle):
        self.puzzle = puzzle
        self.nrows = puzzle.nrows
        self.ncols = puzzle.ncols
        self.clauses: list[list[int]] = []
        self._var_cache: dict[tuple[int, int, int], int] = {}
        self._next_var = 1

    def var(self, i: int, j: int, k: int) -> int:
        """Get or create the SAT variable for x_{i,j,k}."""
        key = (i, j, k)
        if key not in self._var_cache:
            self._var_cache[key] = self._next_var
            self._next_var += 1
        return self._var_cache[key]

    @property
    def num_vars(self) -> int:
        return self._next_var - 1

    @property
    def num_clauses(self) -> int:
        return len(self.clauses)

    def _add_clause(self, clause: list[int]):
        self.clauses.append(clause)

    def encode(self) -> list[list[int]]:
        """Encode the complete puzzle and return CNF clauses."""
        self._encode_init()             # (1a)
        self._encode_at_most_one()      # (1b)
        self._encode_at_least_one()     # (1c)
        self._encode_border_walls()     # (1d)
        self._encode_no_black_inside()  # (1e)
        self._encode_diagonal_continuity()  # (2a-2d)
        self._encode_propagation_1()    # (3a-3d)
        self._encode_propagation_2()    # (4a-4h)
        self._encode_propagation_3()    # (5a-5d)
        self._encode_binary_exclusion() # Table 1
        self._encode_index_constraints()  # (6a-6b)
        return self.clauses

    # ---- (1a) Black cell initialization ----
    def _encode_init(self):
        for (i, j) in self.puzzle.black_cells:
            self._add_clause([self.var(i, j, 6)])

    # ---- (1b) At-most-one motif per cell ----
    def _encode_at_most_one(self):
        nr, nc = self.nrows, self.ncols
        motifs = list(range(1, 7))
        for i in range(1, nr + 1):
            for j in range(1, nc + 1):
                for k1, k2 in combinations(motifs, 2):
                    self._add_clause([-self.var(i, j, k1), -self.var(i, j, k2)])

    # ---- (1c) At-least-one motif per cell ----
    def _encode_at_least_one(self):
        nr, nc = self.nrows, self.ncols
        for i in range(1, nr + 1):
            for j in range(1, nc + 1):
                self._add_clause([self.var(i, j, k) for k in range(1, 7)])

    # ---- (1d) Border walls ----
    def _encode_border_walls(self):
        nr, nc = self.nrows, self.ncols
        # First row and last row
        for j in range(1, nc + 1):
            self._add_clause([self.var(1, j, 6)])
            self._add_clause([self.var(nr, j, 6)])
        # First column and last column (interior)
        for i in range(2, nr):
            self._add_clause([self.var(i, 1, 6)])
            self._add_clause([self.var(i, nc, 6)])

    # ---- (1e) No black for non-black interior cells ----
    def _encode_no_black_inside(self):
        nr, nc = self.nrows, self.ncols
        for i in range(2, nr):
            for j in range(2, nc):
                if (i, j) not in self.puzzle.black_cells:
                    self._add_clause([-self.var(i, j, 6)])

    # ---- (2a-2d) Invalid diagonal continuity ----
    def _encode_diagonal_continuity(self):
        nr, nc = self.nrows, self.ncols
        # (2a): not(x_{i,j,1} and x_{i,j+1,3})
        for i in range(1, nr + 1):
            for j in range(1, nc):
                self._add_clause([-self.var(i, j, 1), -self.var(i, j + 1, 3)])

        # (2b): not(x_{i,j,4} and x_{i+1,j,2})
        for i in range(1, nr):
            for j in range(1, nc + 1):
                self._add_clause([-self.var(i, j, 4), -self.var(i + 1, j, 2)])

        # (2c): not(x_{i,j,1} and x_{i+1,j,3})
        for i in range(1, nr):
            for j in range(1, nc + 1):
                self._add_clause([-self.var(i, j, 1), -self.var(i + 1, j, 3)])

        # (2d): not(x_{i,j,2} and x_{i,j+1,4})
        for i in range(1, nr + 1):
            for j in range(1, nc):
                self._add_clause([-self.var(i, j, 2), -self.var(i, j + 1, 4)])

    # ---- (3a-3d) Propagation rules (1) ----
    def _encode_propagation_1(self):
        nr, nc = self.nrows, self.ncols
        # (3a): x_{i,j,1} ∧ x_{i,j+1,5} ∧ x_{i+1,j,5} => x_{i+1,j+1,5} ∨ x_{i+1,j+1,3}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 1),
                    -self.var(i, j + 1, 5),
                    -self.var(i + 1, j, 5),
                    self.var(i + 1, j + 1, 5),
                    self.var(i + 1, j + 1, 3)
                ])

        # (3b): x_{i,j,2} ∧ x_{i,j+1,5} ∧ x_{i-1,j,5} => x_{i-1,j+1,5} ∨ x_{i-1,j+1,4}
        for i in range(2, nr + 1):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 2),
                    -self.var(i, j + 1, 5),
                    -self.var(i - 1, j, 5),
                    self.var(i - 1, j + 1, 5),
                    self.var(i - 1, j + 1, 4)
                ])

        # (3c): x_{i,j,3} ∧ x_{i,j-1,5} ∧ x_{i-1,j,5} => x_{i-1,j-1,5} ∨ x_{i-1,j-1,1}
        for i in range(2, nr + 1):
            for j in range(2, nc + 1):
                self._add_clause([
                    -self.var(i, j, 3),
                    -self.var(i, j - 1, 5),
                    -self.var(i - 1, j, 5),
                    self.var(i - 1, j - 1, 5),
                    self.var(i - 1, j - 1, 1)
                ])

        # (3d): x_{i,j,4} ∧ x_{i,j-1,5} ∧ x_{i+1,j,5} => x_{i+1,j-1,5} ∨ x_{i+1,j-1,2}
        for i in range(1, nr):
            for j in range(2, nc + 1):
                self._add_clause([
                    -self.var(i, j, 4),
                    -self.var(i, j - 1, 5),
                    -self.var(i + 1, j, 5),
                    self.var(i + 1, j - 1, 5),
                    self.var(i + 1, j - 1, 2)
                ])

    # ---- (4a-4h) Propagation rules (2) ----
    def _encode_propagation_2(self):
        nr, nc = self.nrows, self.ncols
        # (4a): x_{i,j,5} ∧ x_{i,j+1,4} => x_{i-1,j,4}
        for i in range(2, nr + 1):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i, j + 1, 4),
                    self.var(i - 1, j, 4)
                ])

        # (4b): x_{i,j,5} ∧ x_{i+1,j,3} => x_{i,j+1,3}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i + 1, j, 3),
                    self.var(i, j + 1, 3)
                ])

        # (4c): x_{i,j,2} ∧ x_{i,j+1,5} => x_{i+1,j+1,2}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 2),
                    -self.var(i, j + 1, 5),
                    self.var(i + 1, j + 1, 2)
                ])

        # (4d): x_{i,j,1} ∧ x_{i+1,j,5} => x_{i+1,j-1,1}
        for i in range(1, nr):
            for j in range(2, nc + 1):
                self._add_clause([
                    -self.var(i, j, 1),
                    -self.var(i + 1, j, 5),
                    self.var(i + 1, j - 1, 1)
                ])

        # (4e): x_{i,j,1} ∧ x_{i,j+1,5} => x_{i-1,j+1,1}
        for i in range(2, nr + 1):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 1),
                    -self.var(i, j + 1, 5),
                    self.var(i - 1, j + 1, 1)
                ])

        # (4f): x_{i,j,5} ∧ x_{i+1,j,2} => x_{i,j-1,2}
        for i in range(1, nr):
            for j in range(2, nc + 1):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i + 1, j, 2),
                    self.var(i, j - 1, 2)
                ])

        # (4g): x_{i,j,5} ∧ x_{i,j+1,3} => x_{i+1,j,3}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i, j + 1, 3),
                    self.var(i + 1, j, 3)
                ])

        # (4h): x_{i,j,4} ∧ x_{i+1,j,5} => x_{i+1,j+1,4}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 4),
                    -self.var(i + 1, j, 5),
                    self.var(i + 1, j + 1, 4)
                ])

    # ---- (5a-5d) Propagation rules (3) - L-shapes ----
    def _encode_propagation_3(self):
        nr, nc = self.nrows, self.ncols
        # (5a): x_{i,j,5} ∧ x_{i,j+1,5} ∧ x_{i+1,j,5} => x_{i+1,j+1,5} ∨ x_{i+1,j+1,3}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i, j + 1, 5),
                    -self.var(i + 1, j, 5),
                    self.var(i + 1, j + 1, 5),
                    self.var(i + 1, j + 1, 3)
                ])

        # (5b): x_{i,j,5} ∧ x_{i,j+1,5} ∧ x_{i+1,j+1,5} => x_{i+1,j,5} ∨ x_{i+1,j,2}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i, j + 1, 5),
                    -self.var(i + 1, j + 1, 5),
                    self.var(i + 1, j, 5),
                    self.var(i + 1, j, 2)
                ])

        # (5c): x_{i,j,5} ∧ x_{i+1,j,5} ∧ x_{i+1,j-1,5} => x_{i,j-1,5} ∨ x_{i,j-1,1}
        for i in range(1, nr):
            for j in range(2, nc + 1):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i + 1, j, 5),
                    -self.var(i + 1, j - 1, 5),
                    self.var(i, j - 1, 5),
                    self.var(i, j - 1, 1)
                ])

        # (5d): x_{i,j,5} ∧ x_{i+1,j,5} ∧ x_{i+1,j+1,5} => x_{i,j+1,5} ∨ x_{i,j+1,4}
        for i in range(1, nr):
            for j in range(1, nc):
                self._add_clause([
                    -self.var(i, j, 5),
                    -self.var(i + 1, j, 5),
                    -self.var(i + 1, j + 1, 5),
                    self.var(i, j + 1, 5),
                    self.var(i, j + 1, 4)
                ])

    # ---- Binary exclusion constraints (Table 1) ----
    def _encode_binary_exclusion(self):
        nr, nc = self.nrows, self.ncols
        for i in range(1, nr + 1):
            for j in range(1, nc + 1):
                # --- Motif 1 (TRI_UL) exclusions ---
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 1), -self.var(i + 1, j, 6)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 1), -self.var(i, j + 1, 6)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 1), -self.var(i, j + 1, 1)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 1), -self.var(i, j + 1, 2)])
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 1), -self.var(i + 1, j, 4)])
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 1), -self.var(i + 1, j, 1)])

                # --- Motif 2 (TRI_BL) exclusions ---
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 2), -self.var(i - 1, j, 6)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 2), -self.var(i, j + 1, 6)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 2), -self.var(i, j + 1, 1)])
                if j + 1 <= nc:
                    self._add_clause([-self.var(i, j, 2), -self.var(i, j + 1, 2)])
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 2), -self.var(i - 1, j, 2)])
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 2), -self.var(i - 1, j, 3)])

                # --- Motif 3 (TRI_BR) exclusions ---
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i - 1, j, 6)])
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i, j - 1, 6)])
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i - 1, j, 2)])
                if i - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i - 1, j, 3)])
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i, j - 1, 4)])
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 3), -self.var(i, j - 1, 3)])

                # --- Motif 4 (TRI_UR) exclusions ---
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 4), -self.var(i, j - 1, 6)])
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 4), -self.var(i + 1, j, 6)])
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 4), -self.var(i, j - 1, 3)])
                if j - 1 >= 1:
                    self._add_clause([-self.var(i, j, 4), -self.var(i, j - 1, 4)])
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 4), -self.var(i + 1, j, 1)])
                if i + 1 <= nr:
                    self._add_clause([-self.var(i, j, 4), -self.var(i + 1, j, 4)])

    # ---- (6a-6b) Index constraints ----
    def _encode_index_constraints(self):
        for (i, j), m in self.puzzle.indexed_cells.items():
            neighbors = self.puzzle.neighbors(i, j)
            d = len(neighbors)

            # (6a) At most m triangles: for every subset of size m+1,
            # at least one must be non-triangle (white or black)
            if m + 1 <= d:
                for subset in combinations(neighbors, m + 1):
                    clause = []
                    for (ni, nj) in subset:
                        clause.append(self.var(ni, nj, 5))
                        clause.append(self.var(ni, nj, 6))
                    self._add_clause(clause)

            # (6b) At least m triangles: for every subset of size d-m+1,
            # at least one must be a triangle
            if d - m + 1 <= d and m > 0:
                for subset in combinations(neighbors, d - m + 1):
                    clause = []
                    for (ni, nj) in subset:
                        for k in range(1, 5):  # motifs 1-4 are triangles
                            clause.append(self.var(ni, nj, k))
                    self._add_clause(clause)

    def decode_solution(self, model: list[int]) -> dict[tuple[int, int], Motif]:
        """Decode a SAT solver model back to a grid of motifs."""
        true_vars = set(v for v in model if v > 0)
        solution = {}
        for i in range(1, self.nrows + 1):
            for j in range(1, self.ncols + 1):
                for k in range(1, 7):
                    if self.var(i, j, k) in true_vars:
                        solution[(i, j)] = Motif(k)
                        break
        return solution
