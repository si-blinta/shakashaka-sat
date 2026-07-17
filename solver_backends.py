"""Solver support used by the experiments."""

from __future__ import annotations

import atexit
import multiprocessing
import threading
import time
from typing import Optional

from pysat.solvers import Cadical195
from pyscipopt import Model

from encoder import SATEncoder
from puzzle import Motif, ShakashakaPuzzle


def configure_scip(
    model: Model, *, num_threads: int = 1, random_seed: int = 1
) -> None:
    """Apply the deterministic settings used in the experiments."""

    model.setIntParam("parallel/maxnthreads", int(num_threads))
    model.setIntParam("randomization/randomseedshift", int(random_seed))
    model.setIntParam("randomization/permutationseed", int(random_seed))


def _cadical_worker(connection) -> None:
    """Run CaDiCaL in a child process so wall-clock limits can be enforced."""

    solver = None
    encoder = None
    try:
        connection.send(("STARTED",))
        while True:
            message = connection.recv()
            command = message[0]
            if command == "BUILD":
                _, generation, puzzle, random_seed = message
                if solver is not None:
                    solver.delete()

                encode_start = time.perf_counter()
                encoder = SATEncoder(puzzle)
                encoder.encode()
                encode_elapsed = time.perf_counter() - encode_start

                solver_start = time.perf_counter()
                solver = Cadical195()
                solver.configure({"seed": int(random_seed)})
                solver.append_formula(encoder.clauses)
                solver_elapsed = time.perf_counter() - solver_start

                counts = (
                    encoder.num_vars,
                    encoder.num_clauses,
                    sum(len(clause) for clause in encoder.clauses),
                )
                connection.send(
                    (
                        "BUILT",
                        generation,
                        counts,
                        encode_elapsed,
                        solver_elapsed,
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
                connection.send(
                    (
                        "SOLVED",
                        generation,
                        verdict,
                        solution,
                        solver.accum_stats(),
                        elapsed,
                    )
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

    def __init__(self) -> None:
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
            args=(child,),
            name="shakashaka-cadical",
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

    def _receive(self, timeout: Optional[float] = None):
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

    def build(self, puzzle: ShakashakaPuzzle, *, random_seed: int):
        with self._lock:
            self._start_unlocked()
            assert self._connection is not None
            self._generation += 1
            generation = self._generation
            self._connection.send(
                ("BUILD", generation, puzzle, int(random_seed))
            )
            response = self._receive()
            if response is None or response[:2] != ("BUILT", generation):
                self._stop_unlocked()
                raise RuntimeError(f"invalid CaDiCaL build response: {response}")
            self._active_generation = generation
            return (
                generation,
                tuple(int(value) for value in response[2]),
                float(response[3]),
                float(response[4]),
            )

    def solve(self, generation: int, *, time_limit: Optional[float]):
        with self._lock:
            if generation != self._active_generation:
                raise RuntimeError("CaDiCaL solver instance is no longer active")
            assert self._connection is not None
            self._connection.send(("SOLVE", generation))
            response = self._receive(time_limit)
            if response is None:
                return None
            if response[:2] != ("SOLVED", generation):
                self._stop_unlocked()
                raise RuntimeError(f"invalid CaDiCaL solve response: {response}")
            return response


_CADICAL_SERVICE = _CadicalService()
atexit.register(_CADICAL_SERVICE.stop)


class CNFCadicalSolver:
    """Solve the paper's CNF model with CaDiCaL 1.9.5."""

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
        generation, counts, encode_time, solver_build_time = (
            _CADICAL_SERVICE.build(
                self.puzzle,
                random_seed=self.random_seed,
            )
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
    def status_name(self) -> str:
        return self._status_name

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)
