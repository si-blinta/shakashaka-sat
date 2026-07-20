#!/usr/bin/env python3
"""SAT-based extensibility check for 2x2 Shakashaka blocks.

Given a 2x2 motif configuration, the solver places it at a chosen position
of an otherwise unconstrained n x n board (surrounded by the usual black
border) and decides whether it extends to a valid Shakashaka solution.
Enumerating all 6^4 = 1,296 configurations (see test_all_cases.py) gives an
automated cross-check of the hand-made 2x2 tables used by the card-based
ZKP protocol of Miyahara, Robert, Lafourcade and Kaneko (FUN 2026).

On unsatisfiable configurations, an explanation is extracted from the
unsatisfiable core (the set of conflicting constraint instances) and, with
debug_files=True, written to shakashaka_reason.log together with the DIMACS
formula and a DRAT proof.
"""
import sys

try:
    from pysat.solvers import Glucose3
    from pysat.formula import CNF
except ImportError:
    print("ERROR: Please install python-sat (pip install python-sat)")
    sys.exit(1)


# =============================================================================
# PIECE DEFINITIONS
# =============================================================================

class ShakashakaPiece:
    WHITE = 0
    BLACK = 1
    K2 = 2
    K3 = 3
    K1 = 4
    K4 = 5


GUI_TO_SAT = {
    ShakashakaPiece.K1: 1,
    ShakashakaPiece.K2: 2,
    ShakashakaPiece.K3: 3,
    ShakashakaPiece.K4: 4,
    ShakashakaPiece.WHITE: 5,
    ShakashakaPiece.BLACK: 6
}

SAT_TO_GUI = {v: k for k, v in GUI_TO_SAT.items()}


# =============================================================================
# SAT SOLVER
# =============================================================================

class ShakashakaSolver:
    def __init__(self, input_grid_2x2, output_n=6, verbose=True, input_row=None, input_col=None, debug_files=False):
        self.input_grid = input_grid_2x2
        self.n = output_n
        self.cnf = CNF()
        self.verbose = verbose
        self.debug_files = debug_files
        self.clause_count = 0
        # Allow custom position for the 2x2 input, default to center
        if input_row is None:
            self.center_row = self.n // 2 - 1
        else:
            self.center_row = input_row
        if input_col is None:
            self.center_col = self.n // 2 - 1
        else:
            self.center_col = input_col
        self.log_lines = []
        self.clause_rules = []

    def x(self, i, j, k):
        return (i - 1) * self.n * 6 + (j - 1) * 6 + (k - 1) + 1

    def literal_to_string(self, literal):
        abs_lit = abs(literal)
        sign = "-" if literal < 0 else ""
        val = abs_lit - 1
        k = (val % 6) + 1
        val //= 6
        j = (val % self.n) + 1
        i = (val // self.n) + 1
        return f"{sign}x({i},{j},{k})"

    def log(self, message):
        if self.verbose:
            print(message)
        self.log_lines.append(message)

    def add_clause(self, literals, rule_name=""):
        self.cnf.append(literals)
        self.clause_rules.append((self.clause_count, rule_name, literals))
        self.clause_count += 1
        if self.verbose or True:
            clause_str = " ".join([self.literal_to_string(l) for l in literals])
            self.log(f"c [{rule_name}] {clause_str}")

    def generate_constraints(self):
        n = self.n
        K = range(1, 7)

        self.log("c")
        self.log("c === CONSTRAINT GENERATION ===")
        self.log("c")

        self.log("c --- (1a) Initial assignment ---")
        for di in range(2):
            for dj in range(2):
                gui_val = self.input_grid[di][dj]
                k_val = GUI_TO_SAT[gui_val]
                i = (self.center_row + di) + 1
                j = (self.center_col + dj) + 1
                self.add_clause([self.x(i, j, k_val)], "1a")

        self.log("c --- (1b) Existence / (1c) Uniqueness ---")
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                existence_clause = [self.x(i, j, k) for k in K]
                self.cnf.append(existence_clause)
                self.clause_rules.append((self.clause_count, "1b-existence", existence_clause))
                self.clause_count += 1
                for k1 in K:
                    for k2 in K:
                        if k1 < k2:
                            uniqueness_clause = [-self.x(i, j, k1), -self.x(i, j, k2)]
                            self.cnf.append(uniqueness_clause)
                            self.clause_rules.append((self.clause_count, "1c-uniqueness", uniqueness_clause))
                            self.clause_count += 1

        # Border wall constraints: force BLACK (k=6) at all borders
        self.log("c --- (1d) Border walls (BLACK at borders) ---")
        # Top border (row 1)
        for j in range(1, n + 1):
            self.add_clause([self.x(1, j, 6)], "1d-border-top")
        # Bottom border (row n)
        for j in range(1, n + 1):
            self.add_clause([self.x(n, j, 6)], "1d-border-bottom")
        # Left border (column 1) - excluding corners already covered
        for i in range(2, n):
            self.add_clause([self.x(i, 1, 6)], "1d-border-left")
        # Right border (column n) - excluding corners already covered
        for i in range(2, n):
            self.add_clause([self.x(i, n, 6)], "1d-border-right")
        self.log("c --- (2) Diagonal constraints (Fig 2) ---")
        for i in range(1, n + 1):
            for j in range(1, n):
                self.add_clause([-self.x(i, j, 1), -self.x(i, j + 1, 3)], "2a-diag")
        for i in range(1, n):
            for j in range(1, n + 1):
                self.add_clause([-self.x(i, j, 4), -self.x(i + 1, j, 2)], "2b-diag")
        for i in range(1, n):
            for j in range(1, n + 1):
                self.add_clause([-self.x(i, j, 1), -self.x(i + 1, j, 3)], "2c-diag")
        for i in range(1, n + 1):
            for j in range(1, n):
                self.add_clause([-self.x(i, j, 2), -self.x(i, j + 1, 4)], "2d-diag")

        self.log("c --- (3) Implication constraints (Fig 3) ---")
        for i in range(1, n):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 1),
                    self.x(i + 1, j + 1, 5), self.x(i + 1, j + 1, 3)
                ], "3a")
        for i in range(2, n + 1):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 2),
                    self.x(i - 1, j + 1, 5), self.x(i - 1, j + 1, 4)
                ], "3b")
        for i in range(2, n + 1):
            for j in range(2, n + 1):
                self.add_clause([
                    -self.x(i, j, 3), 
                    self.x(i - 1, j - 1, 5), self.x(i - 1, j - 1, 1)
                ], "3c")
        for i in range(1, n):
            for j in range(2, n + 1):
                self.add_clause([
                    -self.x(i, j, 4), 
                    self.x(i + 1, j - 1, 5), self.x(i + 1, j - 1, 2)
                ], "3d")

        self.log("c --- (4) Propagation constraints (Fig 4) ---")
        for i in range(2, n + 1):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i, j + 1, 4), self.x(i - 1, j, 4)
                ], "4a")
        for i in range(1, n):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i + 1, j, 3), self.x(i, j + 1, 3)
                ], "4b")
                self.add_clause([
                    -self.x(i, j, 2), -self.x(i, j + 1, 5), self.x(i + 1, j + 1, 2)
                ], "4c")
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i, j + 1, 3), self.x(i + 1, j, 3)
                ], "4g")
                self.add_clause([
                    -self.x(i, j, 4), -self.x(i + 1, j, 5), self.x(i + 1, j + 1, 4)
                ], "4h")
        for i in range(1, n):
            for j in range(2, n + 1):
                self.add_clause([
                    -self.x(i, j, 1), -self.x(i + 1, j, 5), self.x(i + 1, j - 1, 1)
                ], "4d")
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i + 1, j, 2), self.x(i, j - 1, 2)
                ], "4f")
        for i in range(2, n + 1):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 1), -self.x(i, j + 1, 5), self.x(i - 1, j + 1, 1)
                ], "4e")

        self.log("c --- (5) L-shape constraints (Fig 5) ---")
        for i in range(1, n):
            for j in range(1, n):
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i, j + 1, 5), -self.x(i + 1, j, 5),
                    self.x(i + 1, j + 1, 5), self.x(i + 1, j + 1, 3)
                ], "5a")
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i, j + 1, 5), -self.x(i + 1, j + 1, 5),
                    self.x(i + 1, j, 5), self.x(i + 1, j, 2)
                ], "5b")
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i + 1, j, 5), -self.x(i + 1, j + 1, 5),
                    self.x(i, j + 1, 5), self.x(i, j + 1, 4)
                ], "5d")
        for i in range(1, n):
            for j in range(2, n + 1):
                self.add_clause([
                    -self.x(i, j, 5), -self.x(i + 1, j, 5), -self.x(i + 1, j - 1, 5),
                    self.x(i, j - 1, 5), self.x(i, j - 1, 1)
                ], "5c")

        self.log("c --- Triangle adjacency exclusion constraints ---")
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i < n:
                    self.add_clause([-self.x(i, j, 1), -self.x(i + 1, j, 6)], "k1-k6")
                    self.add_clause([-self.x(i, j, 1), -self.x(i + 1, j, 4)], "k1-k4")
                    self.add_clause([-self.x(i, j, 1), -self.x(i + 1, j, 1)], "k1-k1")
                if j < n:
                    self.add_clause([-self.x(i, j, 1), -self.x(i, j + 1, 6)], "k1-k6")
                    self.add_clause([-self.x(i, j, 1), -self.x(i, j + 1, 1)], "k1-k1")
                    self.add_clause([-self.x(i, j, 1), -self.x(i, j + 1, 2)], "k1-k2")
                if i > 1:
                    self.add_clause([-self.x(i, j, 2), -self.x(i - 1, j, 6)], "k2-k6")
                    self.add_clause([-self.x(i, j, 2), -self.x(i - 1, j, 2)], "k2-k2")
                    self.add_clause([-self.x(i, j, 2), -self.x(i - 1, j, 3)], "k2-k3")
                if j < n:
                    self.add_clause([-self.x(i, j, 2), -self.x(i, j + 1, 6)], "k2-k6")
                    self.add_clause([-self.x(i, j, 2), -self.x(i, j + 1, 1)], "k2-k1")
                    self.add_clause([-self.x(i, j, 2), -self.x(i, j + 1, 2)], "k2-k2")
                if i > 1:
                    self.add_clause([-self.x(i, j, 3), -self.x(i - 1, j, 6)], "k3-k6")
                    self.add_clause([-self.x(i, j, 3), -self.x(i - 1, j, 2)], "k3-k2")
                    self.add_clause([-self.x(i, j, 3), -self.x(i - 1, j, 3)], "k3-k3")
                if j > 1:
                    self.add_clause([-self.x(i, j, 3), -self.x(i, j - 1, 6)], "k3-k6")
                    self.add_clause([-self.x(i, j, 3), -self.x(i, j - 1, 4)], "k3-k4")
                    self.add_clause([-self.x(i, j, 3), -self.x(i, j - 1, 3)], "k3-k3")
                if i < n:
                    self.add_clause([-self.x(i, j, 4), -self.x(i + 1, j, 6)], "k4-k6")
                    self.add_clause([-self.x(i, j, 4), -self.x(i + 1, j, 1)], "k4-k1")
                    self.add_clause([-self.x(i, j, 4), -self.x(i + 1, j, 4)], "k4-k4")
                if j > 1:
                    self.add_clause([-self.x(i, j, 4), -self.x(i, j - 1, 6)], "k4-k6")
                    self.add_clause([-self.x(i, j, 4), -self.x(i, j - 1, 3)], "k4-k3")
                    self.add_clause([-self.x(i, j, 4), -self.x(i, j - 1, 4)], "k4-k4")

    def print_dimacs(self):
        num_vars = self.n * self.n * 6
        num_clauses = len(self.cnf.clauses)
        
        print("")
        print("c ============================================")
        print("c DIMACS CNF FORMAT")
        print("c ============================================")
        print(f"c Variables: x(i,j,k) for i,j in [1,{self.n}], k in [1,6]")
        print(f"c Variable encoding: x(i,j,k) = (i-1)*{self.n}*6 + (j-1)*6 + (k-1) + 1")
        print("c")
        print(f"p cnf {num_vars} {num_clauses}")
        
        for clause in self.cnf.clauses:
            clause_str = " ".join(str(lit) for lit in clause)
            print(f"{clause_str} 0")

    def write_dimacs_file(self, filename="shakashaka.cnf"):
        num_vars = self.n * self.n * 6
        num_clauses = len(self.cnf.clauses)
        
        with open(filename, 'w') as f:
            f.write(f"c Shakashaka SAT instance\n")
            f.write(f"c Grid size: {self.n}x{self.n}\n")
            f.write(f"c Variables: x(i,j,k) for i,j in [1,{self.n}], k in [1,6]\n")
            f.write(f"c Variable encoding: x(i,j,k) = (i-1)*{self.n}*6 + (j-1)*6 + (k-1) + 1\n")
            f.write(f"c k=1: triangle top-left\n")
            f.write(f"c k=2: triangle bottom-left\n")
            f.write(f"c k=3: triangle bottom-right\n")
            f.write(f"c k=4: triangle top-right\n")
            f.write(f"c k=5: white\n")
            f.write(f"c k=6: black\n")
            f.write(f"c\n")
            f.write(f"p cnf {num_vars} {num_clauses}\n")
            
            for clause in self.cnf.clauses:
                clause_str = " ".join(str(lit) for lit in clause)
                f.write(f"{clause_str} 0\n")
        
        print(f"c DIMACS file written to: {filename}")

    def write_log_file(self, filename="shakashaka.log"):
        with open(filename, 'w') as f:
            for line in self.log_lines:
                f.write(line + "\n")
        print(f"c Log file written to: {filename}")

    def analyze_unsat_core(self):
        from pysat.solvers import Glucose3
        
        next_var = self.n * self.n * 6 + 1
        assumptions = []
        assumption_to_clause = {}
        
        clause_idx_to_rule = {}
        for stored_idx, rule_name, literals in self.clause_rules:
            clause_idx_to_rule[stored_idx] = (rule_name, literals)
        
        solver = Glucose3()
        
        for idx, clause in enumerate(self.cnf.clauses):
            assumption_var = next_var + idx
            assumptions.append(assumption_var)
            assumption_to_clause[assumption_var] = idx
            extended_clause = clause + [-assumption_var]
            solver.add_clause(extended_clause)
        
        if solver.solve(assumptions=assumptions):
            solver.delete()
            return None
        
        core = solver.get_core()
        solver.delete()
        
        if core is None:
            return None
        
        conflicting_clauses = []
        for assumption_var in core:
            if assumption_var in assumption_to_clause:
                clause_idx = assumption_to_clause[assumption_var]
                if clause_idx in clause_idx_to_rule:
                    rule_name, literals = clause_idx_to_rule[clause_idx]
                    conflicting_clauses.append((clause_idx, rule_name, literals))
                else:
                    conflicting_clauses.append((clause_idx, "unknown", self.cnf.clauses[clause_idx]))
        
        return conflicting_clauses

    def write_reason_file(self, filename="shakashaka_reason.log"):
        conflicting = self.analyze_unsat_core()
        
        with open(filename, 'w') as f:
            f.write("c ============================================\n")
            f.write("c UNSAT CORE ANALYSIS\n")
            f.write("c ============================================\n")
            f.write("c\n")
            f.write("c The following clauses form an unsatisfiable core:\n")
            f.write("c These rules together make the problem impossible to solve.\n")
            f.write("c\n")
            
            if conflicting is None:
                f.write("c Could not extract UNSAT core.\n")
            else:
                rule_counts = {}
                for clause_idx, rule_name, literals in conflicting:
                    rule_counts[rule_name] = rule_counts.get(rule_name, 0) + 1
                
                f.write("c --- Conflicting rules summary ---\n")
                for rule_name, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
                    f.write(f"c Rule [{rule_name}]: {count} clause(s)\n")
                f.write("c\n")
                
                f.write("c --- Detailed conflicting clauses ---\n")
                for clause_idx, rule_name, literals in conflicting:
                    clause_str = " ".join([self.literal_to_string(l) for l in literals])
                    f.write(f"c Clause {clause_idx} [{rule_name}]: {clause_str}\n")
        
        print(f"c Reason file written to: {filename}")
        
        if conflicting:
            print("c")
            print("c --- UNSAT CORE SUMMARY ---")
            rule_counts = {}
            for clause_idx, rule_name, literals in conflicting:
                rule_counts[rule_name] = rule_counts.get(rule_name, 0) + 1
            for rule_name, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
                print(f"c Conflicting rule [{rule_name}]: {count} clause(s)")

    def solve(self):
        self.generate_constraints()

        if self.verbose:
            self.print_dimacs()

        if self.debug_files:
            self.write_dimacs_file()
            self.write_log_file()

        if self.verbose:
            print("")
            print("c ============================================")
            print("c SOLVING")
            print("c ============================================")
            print(f"c Variables: {self.n * self.n * 6}")
            print(f"c Clauses: {len(self.cnf.clauses)}")
            print("c")

        with Glucose3(bootstrap_with=self.cnf, with_proof=True) as solver:
            if solver.solve():
                model = solver.get_model()
                if self.verbose:
                    print("s SATISFIABLE")
                    self.print_solution(model)
                return self.model_to_grid(model)
            if self.verbose:
                print("s UNSATISFIABLE")
            if self.debug_files:
                self.write_reason_file()
                proof = solver.get_proof()
                with open("proof.drat", "w") as f:
                    for clause in proof:
                        f.write(" ".join(map(str, clause)) + " 0\n")
            return None


    def print_solution(self, model):
        print("v", end="")
        for lit in model:
            print(f" {lit}", end="")
        print(" 0")

        print("c")
        print("c Solution grid (k values):")
        model_set = set(model)
        for i in range(1, self.n + 1):
            row_str = "c "
            for j in range(1, self.n + 1):
                for k in range(1, 7):
                    if self.x(i, j, k) in model_set:
                        row_str += f" {k}"
                        break
            print(row_str)

    def model_to_grid(self, model):
        grid = [[0] * self.n for _ in range(self.n)]
        model_set = set(model)
        for i in range(1, self.n + 1):
            for j in range(1, self.n + 1):
                for k in range(1, 7):
                    if self.x(i, j, k) in model_set:
                        grid[i - 1][j - 1] = SAT_TO_GUI[k]
                        break
        return grid


