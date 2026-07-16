"""Solver adapters for the six benchmark configurations."""

from __future__ import annotations

import atexit
import multiprocessing
import threading
import time
from typing import Optional

from ortools.sat.python import cp_model
from pysat.solvers import Cadical195
from pyscipopt import Model, quicksum

from demaine_cnf import DemaineCNFEncoder
from encoder import SATEncoder
from ip_solver import IPSolver, TRIANGLES, WHITE
from puzzle import Motif, ShakashakaPuzzle


def configure_scip(
    model: Model, *, num_threads: int = 1, random_seed: int = 1
) -> None:
    """Apply the deterministic settings shared by both SCIP experiments."""

    model.setIntParam("parallel/maxnthreads", int(num_threads))
    model.setIntParam("randomization/randomseedshift", int(random_seed))
    model.setIntParam("randomization/permutationseed", int(random_seed))


def _cadical_worker(connection, encoder_kind: str) -> None:
    """Run CaDiCaL in a child process with a wall-clock timeout."""

    solver = None
    encoder = None
    try:
        connection.send(("STARTED",))
        while True:
            message = connection.recv()
            command = message[0]
            if command == "BUILD":
                _, generation, puzzle, random_seed, corrected = message
                if solver is not None:
                    solver.delete()
                build_start = time.perf_counter()
                encode_start = time.perf_counter()
                if encoder_kind == "ours-cnf":
                    encoder = SATEncoder(puzzle)
                elif encoder_kind == "demaine-a-f-cnf":
                    encoder = DemaineCNFEncoder(
                        puzzle,
                        corrected=bool(corrected),
                    )
                else:
                    raise RuntimeError(
                        f"unknown CaDiCaL encoder kind: {encoder_kind}"
                    )
                encoder.encode()
                encode_elapsed = time.perf_counter() - encode_start
                solver_start = time.perf_counter()
                solver = Cadical195()
                solver.configure({"seed": int(random_seed)})
                solver.append_formula(encoder.clauses)
                solver_elapsed = time.perf_counter() - solver_start
                build_elapsed = time.perf_counter() - build_start
                counts = (
                    encoder.num_vars,
                    encoder.num_clauses,
                    sum(len(clause) for clause in encoder.clauses),
                )
                source_counts = (
                    int(getattr(encoder, "num_vars", counts[0])),
                    int(getattr(encoder, "num_source_constraints", counts[1])),
                    int(getattr(encoder, "num_source_nonzeros", counts[2])),
                )
                connection.send(
                    (
                        "BUILT",
                        generation,
                        counts,
                        encode_elapsed,
                        solver_elapsed,
                        build_elapsed,
                        source_counts,
                    )
                )
            elif command == "SOLVE":
                _, generation = message
                if solver is None or encoder is None:
                    raise RuntimeError("CaDiCaL SOLVE received before BUILD")
                start = time.perf_counter()
                verdict = solver.solve()
                elapsed = time.perf_counter() - start
                model = solver.get_model() if verdict else None
                solution = (
                    encoder.decode_solution(model) if verdict and model else None
                )
                stats = solver.accum_stats()
                connection.send(
                    ("SOLVED", generation, verdict, solution, stats, elapsed)
                )
            elif command == "STOP":
                break
            else:
                raise RuntimeError(f"unknown CaDiCaL worker command: {command}")
    except EOFError:
        pass
    except BaseException as exc:
        try:
            connection.send(("ERROR", type(exc).__name__, str(exc)))
        except BaseException:
            pass
    finally:
        if solver is not None:
            solver.delete()
        connection.close()


class _CadicalService:
    """Serialize access to a reusable, killable CaDiCaL worker."""

    START_TIMEOUT = 30.0

    def __init__(self, *, encoder_kind: str, process_name: str) -> None:
        self._encoder_kind = encoder_kind
        self._process_name = process_name
        self._lock = threading.RLock()
        self._process = None
        self._connection = None
        self._generation = 0
        self._active_generation: Optional[int] = None

    def _stop_unlocked(self) -> None:
        connection = self._connection
        process = self._process
        self._connection = None
        self._process = None
        self._active_generation = None
        if connection is not None:
            try:
                if process is not None and process.is_alive():
                    connection.send(("STOP",))
            except (BrokenPipeError, EOFError, OSError):
                pass
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    def _start_unlocked(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._stop_unlocked()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_cadical_worker,
            args=(child, self._encoder_kind),
            name=self._process_name,
            daemon=True,
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        if not parent.poll(self.START_TIMEOUT):
            self._stop_unlocked()
            raise RuntimeError("CaDiCaL worker did not start")
        response = parent.recv()
        if response != ("STARTED",):
            self._stop_unlocked()
            raise RuntimeError(f"invalid CaDiCaL startup response: {response}")

    def _recv_unlocked(self, timeout: Optional[float] = None):
        assert self._connection is not None
        if timeout is not None and not self._connection.poll(timeout):
            self._stop_unlocked()
            return None
        try:
            response = self._connection.recv()
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._stop_unlocked()
            raise RuntimeError("CaDiCaL worker stopped unexpectedly") from exc
        if response and response[0] == "ERROR":
            self._stop_unlocked()
            raise RuntimeError(
                f"CaDiCaL worker error ({response[1]}): {response[2]}"
            )
        return response

    def build(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        random_seed: int,
        corrected: bool = True,
    ):
        with self._lock:
            self._start_unlocked()
            assert self._connection is not None
            self._generation += 1
            generation = self._generation
            self._connection.send(
                (
                    "BUILD",
                    generation,
                    puzzle,
                    int(random_seed),
                    bool(corrected),
                )
            )
            response = self._recv_unlocked()
            if response is None or response[:2] != ("BUILT", generation):
                self._stop_unlocked()
                raise RuntimeError(f"invalid CaDiCaL build response: {response}")
            self._active_generation = generation
            return (
                generation,
                tuple(int(value) for value in response[2]),
                float(response[3]),
                float(response[4]),
                float(response[5]),
                tuple(int(value) for value in response[6]),
            )

    def solve(self, generation: int, *, time_limit: Optional[float]):
        with self._lock:
            if generation != self._active_generation:
                raise RuntimeError("CaDiCaL solver instance is no longer active")
            assert self._connection is not None
            self._connection.send(("SOLVE", generation))
            response = self._recv_unlocked(time_limit)
            if response is None:
                return None
            if response[:2] != ("SOLVED", generation):
                self._stop_unlocked()
                raise RuntimeError(f"invalid CaDiCaL solve response: {response}")
            return response


_CADICAL_SERVICE = _CadicalService(
    encoder_kind="ours-cnf",
    process_name="shakashaka-ours-cadical",
)
_DEMAINE_CADICAL_SERVICE = _CadicalService(
    encoder_kind="demaine-a-f-cnf",
    process_name="shakashaka-demaine-cadical",
)
atexit.register(_CADICAL_SERVICE.stop)
atexit.register(_DEMAINE_CADICAL_SERVICE.stop)


class CNFCadicalSolver:
    """Solve the paper's exact CNF formula with CaDiCaL 1.9.5."""

    def __init__(
        self, puzzle: ShakashakaPuzzle, *, random_seed: int = 1
    ) -> None:
        self.puzzle = puzzle
        self.random_seed = random_seed
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._build_time = 0.0
        self._encode_time = 0.0
        self._solver_build_time = 0.0
        self._solve_time = 0.0
        self._satisfiable: Optional[bool] = None
        self._status_name = "NOT_SOLVED"
        self._stats: dict[str, int] = {}
        self._generation: Optional[int] = None
        self.num_vars = 0
        self.num_constraints = 0
        self.num_nonzeros = 0

    def build(self) -> None:
        if self._generation is not None:
            return
        start = time.perf_counter()
        (
            generation,
            counts,
            encode_time,
            solver_build_time,
            _worker_build_time,
            _source_counts,
        ) = _CADICAL_SERVICE.build(
            self.puzzle, random_seed=self.random_seed
        )
        self._generation = generation
        self._encode_time = encode_time
        self._solver_build_time = solver_build_time
        self.num_vars, self.num_constraints, self.num_nonzeros = counts
        self._build_time = time.perf_counter() - start

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        if self._generation is None:
            self.build()
        assert self._generation is not None
        start = time.perf_counter()
        response = _CADICAL_SERVICE.solve(
            self._generation, time_limit=time_limit
        )
        if response is None:
            self._solve_time = time.perf_counter() - start
            self._satisfiable = None
            self._solution = None
            self._status_name = "TIMEOUT"
            self._stats = {}
            return None

        _, _, verdict, solution, stats, engine_time = response
        self._solve_time = float(engine_time)
        self._satisfiable = bool(verdict)
        self._status_name = "SAT" if verdict else "UNSAT"
        self._stats = {str(key): int(value) for key, value in stats.items()}
        self._solution = solution
        return self._satisfiable

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def encode_time(self) -> float:
        return self._encode_time

    @property
    def solver_build_time(self) -> float:
        return self._solver_build_time

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def satisfiable(self) -> Optional[bool]:
        return self._satisfiable

    @property
    def status_name(self) -> str:
        return self._status_name

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)


class DemaineCadicalSolver:
    """Solve the corrected Demaine A-F model via its exact CNF translation."""

    def __init__(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        corrected: bool = True,
        random_seed: int = 1,
    ) -> None:
        self.puzzle = puzzle
        self.corrected = corrected
        self.random_seed = random_seed
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._build_time = 0.0
        self._encode_time = 0.0
        self._solver_build_time = 0.0
        self._solve_time = 0.0
        self._satisfiable: Optional[bool] = None
        self._status_name = "NOT_SOLVED"
        self._stats: dict[str, int] = {}
        self._generation: Optional[int] = None
        self.num_vars = 0
        self.num_constraints = 0
        self.num_nonzeros = 0
        self.num_source_vars = 0
        self.num_source_constraints = 0
        self.num_source_nonzeros = 0

    def build(self) -> None:
        if self._generation is not None:
            return
        start = time.perf_counter()
        (
            generation,
            counts,
            encode_time,
            solver_build_time,
            _worker_build_time,
            source_counts,
        ) = _DEMAINE_CADICAL_SERVICE.build(
            self.puzzle,
            random_seed=self.random_seed,
            corrected=self.corrected,
        )
        self._generation = generation
        self._encode_time = encode_time
        self._solver_build_time = solver_build_time
        self.num_vars, self.num_constraints, self.num_nonzeros = counts
        (
            self.num_source_vars,
            self.num_source_constraints,
            self.num_source_nonzeros,
        ) = source_counts
        self._build_time = time.perf_counter() - start

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        if self._generation is None:
            self.build()
        assert self._generation is not None
        start = time.perf_counter()
        response = _DEMAINE_CADICAL_SERVICE.solve(
            self._generation,
            time_limit=time_limit,
        )
        if response is None:
            self._solve_time = time.perf_counter() - start
            self._satisfiable = None
            self._solution = None
            self._status_name = "TIMEOUT"
            self._stats = {}
            return None

        _, _, verdict, solution, stats, engine_time = response
        self._solve_time = float(engine_time)
        self._satisfiable = bool(verdict)
        self._status_name = "SAT" if verdict else "UNSAT"
        self._stats = {str(key): int(value) for key, value in stats.items()}
        self._solution = solution
        return self._satisfiable

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def encode_time(self) -> float:
        return self._encode_time

    @property
    def solver_build_time(self) -> float:
        return self._solver_build_time

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def satisfiable(self) -> Optional[bool]:
        return self._satisfiable

    @property
    def feasible(self) -> Optional[bool]:
        return self._satisfiable

    @property
    def status_name(self) -> str:
        return self._status_name

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)


class CNFCPSATSolver:
    """Solve the paper's exact CNF formula with OR-Tools CP-SAT."""

    def __init__(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        num_workers: int = 1,
        random_seed: int = 1,
    ) -> None:
        self.puzzle = puzzle
        self.num_workers = num_workers
        self.random_seed = random_seed
        self.encoder = SATEncoder(puzzle)
        self.model: Optional[cp_model.CpModel] = None
        self.variables: dict[int, cp_model.IntVar] = {}
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._build_time = 0.0
        self._encode_time = 0.0
        self._solve_time = 0.0
        self._feasible: Optional[bool] = None
        self._status_name = "NOT_SOLVED"
        self.num_vars = 0
        self.num_constraints = 0
        self.num_nonzeros = 0

    def build(self) -> None:
        if self.model is not None:
            return

        start = time.perf_counter()
        encode_start = time.perf_counter()
        self.encoder.encode()
        self._encode_time = time.perf_counter() - encode_start

        model = cp_model.CpModel()
        id_to_key = {vid: key for key, vid in self.encoder._var_cache.items()}
        for vid in range(1, self.encoder.num_vars + 1):
            key = id_to_key.get(vid)
            name = "v_{}".format(vid)
            if key is not None:
                name = "x_{}_{}_{}".format(*key)
            self.variables[vid] = model.NewBoolVar(name)

        for clause in self.encoder.clauses:
            literals = [
                self.variables[lit]
                if lit > 0
                else self.variables[-lit].Not()
                for lit in clause
            ]
            model.AddBoolOr(literals)

        self.model = model
        self.num_vars = self.encoder.num_vars
        self.num_constraints = self.encoder.num_clauses
        self.num_nonzeros = sum(len(clause) for clause in self.encoder.clauses)
        self._build_time = time.perf_counter() - start

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        if self.model is None:
            self.build()
        assert self.model is not None

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = int(self.num_workers)
        solver.parameters.random_seed = int(self.random_seed)
        if time_limit is not None:
            solver.parameters.max_time_in_seconds = float(time_limit)

        start = time.perf_counter()
        status = solver.Solve(self.model)
        self._solve_time = time.perf_counter() - start
        self._status_name = solver.StatusName(status)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self._feasible = True
            assignment = [
                vid if solver.BooleanValue(var) else -vid
                for vid, var in self.variables.items()
            ]
            self._solution = self.encoder.decode_solution(assignment)
        elif status == cp_model.INFEASIBLE:
            self._feasible = False
            self._solution = None
        else:
            self._feasible = None
            self._solution = None
        return self._feasible

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def encode_time(self) -> float:
        return self._encode_time

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def feasible(self) -> Optional[bool]:
        return self._feasible

    @property
    def status_name(self) -> str:
        return self._status_name


class CNFSCIPSolver:
    """Solve the paper's exact CNF formula as a 0-1 SCIP model."""

    def __init__(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        num_threads: int = 1,
        random_seed: int = 1,
    ) -> None:
        self.puzzle = puzzle
        self.num_threads = num_threads
        self.random_seed = random_seed
        self.encoder = SATEncoder(puzzle)
        self.model: Optional[Model] = None
        self.variables: dict[int, object] = {}
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._build_time = 0.0
        self._encode_time = 0.0
        self._solve_time = 0.0
        self._feasible: Optional[bool] = None
        self._status_name = "NOT_SOLVED"
        self.num_vars = 0
        self.num_constraints = 0
        self.num_nonzeros = 0

    def build(self) -> None:
        if self.model is not None:
            return

        start = time.perf_counter()
        encode_start = time.perf_counter()
        self.encoder.encode()
        self._encode_time = time.perf_counter() - encode_start

        model = Model("shakashaka_cnf_scip")
        model.hideOutput()
        configure_scip(
            model,
            num_threads=self.num_threads,
            random_seed=self.random_seed,
        )

        id_to_key = {vid: key for key, vid in self.encoder._var_cache.items()}
        for vid in range(1, self.encoder.num_vars + 1):
            key = id_to_key.get(vid)
            name = "v_{}".format(vid)
            if key is not None:
                name = "x_{}_{}_{}".format(*key)
            self.variables[vid] = model.addVar(vtype="B", name=name)

        for clause in self.encoder.clauses:
            negative_count = sum(1 for lit in clause if lit < 0)
            terms = [
                self.variables[lit] if lit > 0 else -self.variables[-lit]
                for lit in clause
            ]
            model.addCons(quicksum(terms) >= 1 - negative_count)

        self.model = model
        self.num_vars = self.encoder.num_vars
        self.num_constraints = self.encoder.num_clauses
        self.num_nonzeros = sum(len(clause) for clause in self.encoder.clauses)
        self._build_time = time.perf_counter() - start

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        if self.model is None:
            self.build()
        assert self.model is not None
        if time_limit is not None:
            self.model.setRealParam("limits/time", float(time_limit))

        start = time.perf_counter()
        self.model.optimize()
        self._solve_time = time.perf_counter() - start
        status = str(self.model.getStatus())
        self._status_name = status.upper()

        if status == "optimal":
            self._feasible = True
            assignment = [
                vid if self.model.getVal(var) > 0.5 else -vid
                for vid, var in self.variables.items()
            ]
            self._solution = self.encoder.decode_solution(assignment)
        elif status == "infeasible":
            self._feasible = False
            self._solution = None
        else:
            self._feasible = None
            self._solution = None
        return self._feasible

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def encode_time(self) -> float:
        return self._encode_time

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def feasible(self) -> Optional[bool]:
        return self._feasible

    @property
    def status_name(self) -> str:
        return self._status_name


class DemaineCPSATSolver:
    """Solve the corrected Demaine A-F model with CP-SAT.

    The constraint templates are imported from :class:`IPSolver` so that the
    SCIP and CP-SAT implementations cannot silently drift apart.
    """

    def __init__(
        self,
        puzzle: ShakashakaPuzzle,
        *,
        corrected: bool = True,
        num_workers: int = 1,
        random_seed: int = 1,
    ) -> None:
        self.puzzle = puzzle
        self.corrected = corrected
        self.num_workers = num_workers
        self.random_seed = random_seed
        self.model: Optional[cp_model.CpModel] = None
        self.x: dict[tuple[int, int, int], cp_model.IntVar] = {}
        self._solution: Optional[dict[tuple[int, int], Motif]] = None
        self._build_time = 0.0
        self._solve_time = 0.0
        self._feasible: Optional[bool] = None
        self._status_name = "NOT_SOLVED"
        self.num_vars = 0
        self.num_constraints = 0
        self.num_nonzeros = 0

    def _is_white_sq(self, i: int, j: int) -> bool:
        return self.puzzle.is_playable(i, j)

    def _v(self, i: int, j: int, motif: int):
        return self.x.get((i, j, motif))

    def _add(self, constraint, *, nnz: int) -> None:
        assert self.model is not None
        self.model.Add(constraint)
        self.num_constraints += 1
        self.num_nonzeros += nnz

    def _black_squares(self) -> set[tuple[int, int]]:
        p = self.puzzle
        cells = set(p.black_cells)
        for j in range(1, p.ncols + 1):
            cells.add((1, j))
            cells.add((p.nrows, j))
        for i in range(1, p.nrows + 1):
            cells.add((i, 1))
            cells.add((i, p.ncols))
        return cells

    def build(self) -> None:
        if self.model is not None:
            return

        start = time.perf_counter()
        p = self.puzzle
        self.model = cp_model.CpModel()

        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if self._is_white_sq(i, j):
                    for motif in (*TRIANGLES, WHITE):
                        self.x[(i, j, motif)] = self.model.NewBoolVar(
                            f"x_{i}_{j}_{motif}"
                        )
        self.num_vars = len(self.x)

        self._constraint_a()
        self._constraint_b()
        self._constraint_c()
        self._constraint_d()
        self._constraint_e()
        if self.corrected:
            self._constraint_f()

        self._build_time = time.perf_counter() - start

    def _constraint_a(self) -> None:
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if self._is_white_sq(i, j):
                    variables = [
                        self.x[(i, j, motif)] for motif in (*TRIANGLES, WHITE)
                    ]
                    self._add(sum(variables) == 1, nnz=5)

    def _constraint_b(self) -> None:
        p = self.puzzle
        for i, j in self._black_squares():
            for (di, dj), forbidden in IPSolver._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if self._is_white_sq(ni, nj):
                    for motif in forbidden:
                        self._add(self.x[(ni, nj, motif)] == 0, nnz=1)

        for (i, j), clue in p.indexed_cells.items():
            terms = []
            for (di, dj), forbidden in IPSolver._FORBIDDEN.items():
                ni, nj = i + di, j + dj
                if self._is_white_sq(ni, nj):
                    allowed = [m for m in TRIANGLES if m not in forbidden]
                    terms.extend(self.x[(ni, nj, m)] for m in allowed)
            if terms:
                self._add(sum(terms) == clue, nnz=len(terms))
            elif clue != 0:
                # Match IPSolver's explicit contradiction for this degenerate
                # case while keeping a valid CP-SAT model.
                impossible = self.model.NewBoolVar(f"infeas_{i}_{j}")
                self._add(impossible == 0, nnz=1)
                self._add(impossible == 1, nnz=1)

    def _constraint_c(self) -> None:
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, ((tdi, tdj), turn_motif), (cdi, cdj) in IPSolver._C_RULES:
                    rhs = []
                    turn = self._v(i + tdi, j + tdj, turn_motif)
                    continuation = self._v(i + cdi, j + cdj, motif)
                    if turn is not None:
                        rhs.append(turn)
                    if continuation is not None:
                        rhs.append(continuation)
                    self._add(
                        self.x[(i, j, motif)] <= sum(rhs),
                        nnz=1 + len(rhs),
                    )

                for motif, ((cdi, cdj), (mdi, mdj)) in IPSolver._C_MIDDLE.items():
                    continuation = self._v(i + cdi, j + cdj, motif)
                    middle = self._v(i + mdi, j + mdj, WHITE)
                    if continuation is None:
                        continue
                    if middle is not None:
                        self._add(
                            self.x[(i, j, motif)] + continuation <= middle + 1,
                            nnz=3,
                        )
                    else:
                        self._add(
                            self.x[(i, j, motif)] + continuation <= 1,
                            nnz=2,
                        )

    def _constraint_d(self) -> None:
        p = self.puzzle
        for i in range(1, p.nrows):
            for j in range(1, p.ncols):
                for whites, (cdi, cdj), closing_motif in IPSolver._D_RULES:
                    white_vars = []
                    for di, dj in whites:
                        var = self._v(i + di, j + dj, WHITE)
                        if var is None:
                            break
                        white_vars.append(var)
                    if len(white_vars) != len(whites):
                        continue
                    rhs = [
                        var
                        for var in (
                            self._v(i + cdi, j + cdj, WHITE),
                            self._v(i + cdi, j + cdj, closing_motif),
                        )
                        if var is not None
                    ]
                    self._add(
                        sum(white_vars) <= sum(rhs) + 2,
                        nnz=len(white_vars) + len(rhs),
                    )

    def _constraint_e(self) -> None:
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, opposite, column_step in IPSolver._E_RULES:
                    distance = 1
                    while True:
                        i2 = i + distance
                        j2 = j + distance * column_step
                        if not (1 <= i2 <= p.nrows and 1 <= j2 <= p.ncols):
                            break
                        if self._is_white_sq(i2, j2):
                            between = [
                                var
                                for offset in range(1, distance)
                                if (
                                    var := self._v(
                                        i + offset,
                                        j + offset * column_step,
                                        opposite,
                                    )
                                )
                                is not None
                            ]
                            self._add(
                                self.x[(i, j, motif)]
                                + self.x[(i2, j2, motif)]
                                <= sum(between) + 1,
                                nnz=2 + len(between),
                            )
                        distance += 1

    def _constraint_f(self) -> None:
        p = self.puzzle
        for i in range(1, p.nrows + 1):
            for j in range(1, p.ncols + 1):
                if not self._is_white_sq(i, j):
                    continue
                for motif, whites, (cdi, cdj), closing_motif in IPSolver._F_RULES:
                    white_vars = []
                    for di, dj in whites:
                        var = self._v(i + di, j + dj, WHITE)
                        if var is None:
                            break
                        white_vars.append(var)
                    if len(white_vars) != len(whites):
                        continue
                    rhs = [
                        var
                        for var in (
                            self._v(i + cdi, j + cdj, WHITE),
                            self._v(i + cdi, j + cdj, closing_motif),
                        )
                        if var is not None
                    ]
                    self._add(
                        self.x[(i, j, motif)] + sum(white_vars)
                        <= sum(rhs) + 2,
                        nnz=1 + len(white_vars) + len(rhs),
                    )

    def solve(self, time_limit: Optional[float] = None) -> Optional[bool]:
        if self.model is None:
            self.build()
        assert self.model is not None

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = int(self.num_workers)
        solver.parameters.random_seed = int(self.random_seed)
        if time_limit is not None:
            solver.parameters.max_time_in_seconds = float(time_limit)

        start = time.perf_counter()
        status = solver.Solve(self.model)
        self._solve_time = time.perf_counter() - start
        self._status_name = solver.StatusName(status)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self._feasible = True
            solution: dict[tuple[int, int], Motif] = {}
            p = self.puzzle
            for i in range(1, p.nrows + 1):
                for j in range(1, p.ncols + 1):
                    if self._is_white_sq(i, j):
                        for motif in (*TRIANGLES, WHITE):
                            if solver.BooleanValue(self.x[(i, j, motif)]):
                                solution[(i, j)] = Motif(motif)
                                break
                    else:
                        solution[(i, j)] = Motif.BLACK
            self._solution = solution
        elif status == cp_model.INFEASIBLE:
            self._feasible = False
            self._solution = None
        else:
            self._feasible = None
            self._solution = None
        return self._feasible

    @property
    def solution(self) -> Optional[dict[tuple[int, int], Motif]]:
        return self._solution

    @property
    def build_time(self) -> float:
        return self._build_time

    @property
    def solve_time(self) -> float:
        return self._solve_time

    @property
    def feasible(self) -> Optional[bool]:
        return self._feasible

    @property
    def status_name(self) -> str:
        return self._status_name
