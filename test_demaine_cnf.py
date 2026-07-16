"""Test the exact Demaine A-F to CNF translation."""

from __future__ import annotations

import itertools
import sys

from artificial import artificial_instance
from demaine_cnf import DemaineCNFEncoder, exactly_k_clauses


def _satisfies(clauses: list[list[int]], values: tuple[bool, ...]) -> bool:
    assignment = {
        index + 1: value for index, value in enumerate(values)
    }
    return all(
        any(
            assignment[abs(literal)] if literal > 0 else not assignment[abs(literal)]
            for literal in clause
        )
        for clause in clauses
    )


def test_cardinality_truth_tables() -> None:
    for width in range(9):
        literals = list(range(1, width + 1))
        for bound in range(-1, width + 2):
            clauses = exactly_k_clauses(literals, bound)
            for values in itertools.product((False, True), repeat=width):
                expected = sum(values) == bound
                actual = _satisfies(clauses, values)
                assert actual == expected, (width, bound, values, clauses)


def test_encoder_idempotence() -> None:
    encoder = DemaineCNFEncoder(artificial_instance(3), corrected=True)
    encoder.encode()
    snapshot = (
        encoder.num_vars,
        encoder.num_clauses,
        encoder.num_nonzeros,
        encoder.num_source_constraints,
        encoder.num_source_nonzeros,
        [list(clause) for clause in encoder.clauses],
    )
    encoder.encode()
    assert snapshot == (
        encoder.num_vars,
        encoder.num_clauses,
        encoder.num_nonzeros,
        encoder.num_source_constraints,
        encoder.num_source_nonzeros,
        encoder.clauses,
    )


def main() -> int:
    test_cardinality_truth_tables()
    test_encoder_idempotence()
    print("Demaine CNF cardinality and idempotence tests: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
