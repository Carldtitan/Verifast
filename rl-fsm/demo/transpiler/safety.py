"""Safety_Checker for the FSM_DSL transpiler.

The Safety_Checker enforces the four compile-time safety rules that stand
between a parsed-and-typed :class:`~transpiler.ast.Program` and code
generation:

* **total outputs** (Req 7) -- every declared output is assigned in every
  declared state;
* **total transitions** (Req 8) -- every state ends with a final
  ``else -> STATE`` clause;
* **single driver** (Req 9) -- every output is driven by exactly one machine;
* **name resolution** (Req 10) -- every transition/reset target resolves to a
  declared state.

Each check is an independent, side-effect-free function that reads the model
and returns a list of :class:`~transpiler.errors.SafetyError`. A later task
adds the :func:`check` driver that runs all four to completion and returns the
aggregated, ordered diagnostics (Req 16.1); the empty list means the program is
safe to generate.

Diagnostics are produced in a deterministic order so the CLI emits stable
output: checks iterate states in declared order and, within a state, the
relevant elements (e.g. declared outputs) in declared order.
"""

from __future__ import annotations

from transpiler.ast import Machine, Port, Program
from transpiler.errors import SafetyError

__all__ = [
    "check",
    "check_total_outputs",
    "check_total_transitions",
    "check_single_driver",
    "check_name_resolution",
]


def check(program: Program) -> list[SafetyError]:
    """Run all four safety checks to completion and aggregate the diagnostics.

    This is the Safety_Checker driver (Req 16.1, 16.5). It runs every check
    without short-circuiting so that *every* violation is reported rather than
    stopping at the first failing rule (Property 13): the per-machine checks
    (:func:`check_total_outputs`, :func:`check_total_transitions`,
    :func:`check_name_resolution`) run once for each machine in
    ``program.machines``, and the cross-machine :func:`check_single_driver`
    runs once over the whole program.

    Ordering is deterministic so the CLI emits stable output. For each machine,
    in declared order, the checks contribute their errors in this order:

    1. total outputs (Req 7)
    2. total transitions (Req 8)
    3. name resolution (Req 10)

    After every machine has been checked, the single-driver errors (Req 9) for
    the whole program are appended last. The lists are simply concatenated;
    each individual check already orders its own diagnostics deterministically.

    Args:
        program: The parsed-and-typed program to verify.

    Returns:
        The aggregated, ordered list of :class:`SafetyError`. An empty list
        means the program is safe to generate (Req 16.5).
    """
    errors: list[SafetyError] = []
    for machine in program.machines:
        errors.extend(check_total_outputs(machine))
        errors.extend(check_total_transitions(machine))
        errors.extend(check_name_resolution(machine))
    errors.extend(check_single_driver(program))
    return errors


def check_total_outputs(m: Machine) -> list[SafetyError]:
    """Verify every declared output is assigned in every declared state (Req 7).

    For each declared state ``S`` and each declared output port ``x`` of the
    machine, if ``S`` contains no output assignment for ``x`` then one error is
    emitted in the exact form ``state S does not assign output 'x'`` (Req 7.2).
    A state that leaves several outputs unassigned yields one error per
    unassigned output (Req 7.3). When the machine declares zero states or zero
    outputs the check reports nothing (Req 7.4); when every output is assigned
    in every state it likewise reports nothing (Req 7.6).

    Errors are ordered deterministically: states in declared order, and within
    each state the declared outputs in declared order, so the aggregated
    diagnostics are stable.

    Args:
        m: The machine to check.

    Returns:
        A list of :class:`SafetyError` with ``rule == "total_outputs"``; empty
        when every output is assigned in every state (including the
        zero-states / zero-outputs case).
    """
    errors: list[SafetyError] = []
    for state in m.states:
        assigned = {a.output_name for a in state.outputs}
        for out in m.outputs:
            if out.name not in assigned:
                errors.append(
                    SafetyError(
                        "total_outputs",
                        state.loc,
                        f"state {state.name} does not assign output "
                        f"'{out.name}'",
                    )
                )
    return errors


def check_total_transitions(m: Machine) -> list[SafetyError]:
    """Verify every state ends with a final ``else -> STATE`` transition (Req 8).

    A state's transition list is *total* when its last clause is an ``else``
    transition, which guarantees a defined next state for every input (Req 8.1).
    For each declared state whose transition list is empty or whose final clause
    is not an ``else`` transition, one error is emitted naming the offending
    state in the form ``state S does not end with a final 'else -> STATE'
    transition`` (Req 8.2). A machine with several offending states yields one
    error per offending state (Req 8.3).

    Errors are ordered deterministically by declared state order so the
    aggregated diagnostics are stable.

    Args:
        m: The machine to check.

    Returns:
        A list of :class:`SafetyError` with ``rule == "total_transitions"``;
        empty when every state ends with a final ``else`` transition.
    """
    errors: list[SafetyError] = []
    for state in m.states:
        if not state.transitions or state.transitions[-1].kind != "else":
            errors.append(
                SafetyError(
                    "total_transitions",
                    state.loc,
                    f"state {state.name} does not end with a final "
                    f"'else -> STATE' transition",
                )
            )
    return errors


def check_single_driver(p: Program) -> list[SafetyError]:
    """Verify every output is driven by exactly one machine (Req 9).

    This check spans the whole :class:`Program` because the single-driver
    property is cross-machine. Two distinct violations are detected:

    * **Duplicate declaration** (Req 9.3): when the same output *name* is
      declared by more than one machine, one error is emitted for each
      duplicate declaration (every declaring machine after the first, in
      declared order). Each error is located at the duplicate port's
      :class:`Loc` and its message names the output together with the source
      location of every machine that declares it.
    * **Cross-machine assignment** (Req 9.1, 9.2): when a state assigns an
      output whose name is *not* declared by that state's own machine but *is*
      declared by some other machine, one error is emitted at the offending
      assignment's :class:`Loc`, naming the output, the assigning state and
      machine, and the machine that declares the output.

    An assignment whose ``output_name`` is declared by no machine at all is out
    of scope here: that is a name-resolution concern handled elsewhere, so only
    names that *are* declared somewhere (but in a different machine) are
    flagged. Every detected violation is reported rather than stopping at the
    first (Req 9.4).

    Errors are ordered deterministically: all duplicate-declaration errors
    first (by declared output name, then by declaring machine order), followed
    by all cross-machine assignment errors (machines, then states, then
    assignments, each in declared order), so the aggregated diagnostics are
    stable.

    Note: the AST builder currently enforces exactly one machine per source
    file, so multi-machine programs cannot be produced from source today. This
    check is nonetheless implemented generally over ``p.machines`` so it stays
    correct for any constructed :class:`Program`.

    Args:
        p: The whole program to check.

    Returns:
        A list of :class:`SafetyError` with ``rule == "single_driver"``; empty
        when every output is declared by exactly one machine and assigned only
        within that machine's states.
    """
    # Map each output name to the machines that declare it, preserving declared
    # machine order and recording the first declaring port per machine (used as
    # that machine's declaration location).
    declarers: dict[str, list[tuple[Machine, Port]]] = {}
    for machine in p.machines:
        seen_here: set[str] = set()
        for port in machine.outputs:
            if port.name in seen_here:
                # Ignore intra-machine repeats; this is not a cross-machine
                # concern (and is rejected upstream).
                continue
            seen_here.add(port.name)
            declarers.setdefault(port.name, []).append((machine, port))

    errors: list[SafetyError] = []

    # (Req 9.3) Same output name declared by more than one machine.
    for name, decls in declarers.items():
        if len(decls) <= 1:
            continue
        locations = ", ".join(
            f"{mach.name} ({port.loc.file}:{port.loc.line})"
            for mach, port in decls
        )
        # Emit one error per duplicate declaration (every machine after the
        # first), located at that duplicate port.
        for _mach, port in decls[1:]:
            errors.append(
                SafetyError(
                    "single_driver",
                    port.loc,
                    f"output '{name}' is declared by more than one machine: "
                    f"{locations}",
                )
            )

    # (Req 9.1, 9.2) Output assigned within a machine other than the one that
    # declares it.
    for machine in p.machines:
        own_outputs = {port.name for port in machine.outputs}
        for state in machine.states:
            for assignment in state.outputs:
                name = assignment.output_name
                if name in own_outputs:
                    continue
                if name not in declarers:
                    # Declared by no machine: out of scope here (a name-
                    # resolution / typo concern, not a single-driver one).
                    continue
                owner = declarers[name][0][0]
                errors.append(
                    SafetyError(
                        "single_driver",
                        assignment.loc,
                        f"output '{name}' is assigned in state {state.name} of "
                        f"machine {machine.name} but is declared by machine "
                        f"{owner.name}",
                    )
                )

    return errors


def check_name_resolution(m: Machine) -> list[SafetyError]:
    """Verify every transition/reset target resolves to a declared state (Req 10).

    A *declared state* is one whose name appears in ``m.states``. The check
    confirms that every transition's ``target`` -- including the target of a
    final ``else -> STATE`` clause (Req 8.4, 10.1, 10.3) -- and the
    ``reset = STATE`` target (Req 10.2, 10.4) name a declared state. Each
    unresolved target yields exactly one error naming it, so a program with
    several dangling references produces one error per reference (Req 10.5);
    when every target resolves the check reports nothing (Req 10.6).

    Diagnostic order is deterministic: transition targets are reported first,
    iterating states in declared order and, within a state, transitions in
    declared order; the reset-target error, if any, is reported last. This
    keeps the aggregated diagnostics stable.

    Args:
        m: The machine to check.

    Returns:
        A list of :class:`SafetyError` with ``rule == "name_resolution"``;
        empty when every transition target and the reset target resolve to a
        declared state.
    """
    declared = {s.name for s in m.states}
    errors: list[SafetyError] = []
    for state in m.states:
        for transition in state.transitions:
            if transition.target not in declared:
                errors.append(
                    SafetyError(
                        "name_resolution",
                        transition.loc,
                        f"transition in state {state.name} targets undeclared "
                        f"state '{transition.target}'",
                    )
                )
    if m.reset_state not in declared:
        errors.append(
            SafetyError(
                "name_resolution",
                m.loc,
                f"reset target '{m.reset_state}' is not a declared state",
            )
        )
    return errors
