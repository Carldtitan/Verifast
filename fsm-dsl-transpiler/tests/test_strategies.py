"""Self-test for the shared Hypothesis strategies (task 11.1, Req 17.1).

These tests confirm that:

* :func:`valid_program` produces models that satisfy all four safety rules
  structurally and render to source that the real parser accepts (and, once
  the AST builder lands, that ``build_ast`` accepts too);
* each perturbation strategy yields a still-*parseable* program tagged with the
  expected violation kind, so downstream safety / CLI property tests can rely
  on the ``(program, expected_violation_kind)`` contract.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from transpiler.errors import ParseError
from transpiler.parser import parse

from tests import strategies as S

# build_ast (task 3.2) may be implemented in parallel. Import it if present so
# the self-test exercises the full front end; otherwise fall back to a
# parse-only check.
try:  # pragma: no cover - depends on parallel task 3.2
    from transpiler.ast_builder import build_ast  # type: ignore
except Exception:  # pragma: no cover
    build_ast = None  # type: ignore[assignment]


@settings(max_examples=100)
@given(S.valid_program())
def test_valid_program_satisfies_invariants(program) -> None:
    S.assert_valid_program_invariants(program)


@settings(max_examples=100)
@given(S.valid_program())
def test_valid_program_renders_and_parses(program) -> None:
    source = S.render_program(program)
    # The rendered source must always parse against the real grammar.
    tree = parse(source, file=program.source_file)
    assert tree.data == "start"
    machines = [c for c in tree.children if getattr(c, "data", None) == "machine"]
    assert len(machines) == 1
    if build_ast is not None:  # pragma: no cover - only when task 3.2 is done
        build_ast(tree, file=program.source_file)


@settings(max_examples=50)
@given(S.invalid_program())
def test_perturbations_stay_parseable_and_tagged(case) -> None:
    program, kind = case
    assert kind in S.VIOLATION_KINDS
    # Perturbations break *semantic* safety rules, not syntax, so the rendered
    # source must still parse (the violation is caught by later stages).
    source = S.render_program(program)
    parse(source, file=program.source_file)


@pytest.mark.parametrize("kind", sorted(S.VIOLATION_KINDS))
@settings(max_examples=20)
@given(data=st.data())
def test_each_perturbation_kind_is_reachable(data, kind) -> None:
    program, reported = data.draw(S.PERTURBATIONS[kind])
    assert reported == kind
    # Rendered output parses regardless of the semantic break.
    parse(S.render_program(program), file=program.source_file)


def test_render_port_type_scalar_and_vector() -> None:
    from transpiler.ast import PortType

    assert S.render_port_type(PortType(high=0, low=0)) == "bit"
    assert S.render_port_type(PortType(high=7, low=0)) == "bit[7:0]"
    assert S.render_port_type(PortType(high=2, low=2)) == "bit[2:2]"


@settings(max_examples=25)
@given(case=S.drop_output())
def test_drop_output_actually_drops_an_output(case) -> None:
    # The perturbed program must violate total-outputs in at least one state.
    program, kind = case
    assert kind == "drop_output"
    machine = program.machines[0]
    required = {p.name for p in machine.outputs}
    assert any(
        {a.output_name for a in s.outputs} != required for s in machine.states
    )


@settings(max_examples=25)
@given(case=S.duplicate_output_across_machines())
def test_duplicate_output_across_machines_shares_a_name(case) -> None:
    program, kind = case
    assert kind == "duplicate_output_across_machines"
    assert len(program.machines) == 2
    names0 = {p.name for p in program.machines[0].outputs}
    names1 = {p.name for p in program.machines[1].outputs}
    assert names0 & names1, "the two machines should share an output name"
