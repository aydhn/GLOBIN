"""What *this repository's* scientific-stack declaration must satisfy.

The unit tests exercise the judgements against synthetic trees. These assert about
the real committed files, which is the half that goes stale: a declaration can be
internally consistent and still disagree with `pyproject.toml`, with `pylock.toml`
or with the code that implements its probes.

**These run in the ordinary suite, and the gate does not.** `python -m
tools.quality stack` writes an artefact and imports two large libraries, so it is
not in `full` — the same position `governance`, `lock` and `wheels` are in. What
must gate a commit is here, where the coverage step already runs it.

Nothing here imports `numpy` or `pandas`. Every assertion is about text and about
registries, so the CI `quality` job — which has neither library — runs all of it.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from tools.quality.lock.plan import normalise
from tools.quality.stack import gate, manifest, plan, probes
from tools.quality.stack.plan import Declaration


@pytest.fixture(scope="module")
def declaration() -> Declaration:
    """This repository's stack contract, parsed."""
    return gate.declaration_of()


@pytest.fixture(scope="module")
def manifest_document(repo_root: Path) -> dict[str, object]:
    """`pyproject.toml`, parsed."""
    with (repo_root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


# ---------------------------------------------------------------------------
# The declaration against the rest of the repository
# ---------------------------------------------------------------------------


def test_the_declaration_parses_and_declares_the_stack(declaration: Declaration) -> None:
    """The three libraries whose behaviour is measured rather than assumed.

    ``psutil`` is a declared runtime dependency and is deliberately not here: it
    reports on the host rather than computing anything, so there is no behaviour
    for a probe to defend. Membership of this set means "GLOBIN depends on what
    this library computes", not "GLOBIN installs it".
    """
    assert {library.name for library in declaration.libraries} == {"numpy", "pandas", "ta-lib"}


def test_the_declared_target_is_the_runtime_contract(
    repo_root: Path, declaration: Declaration
) -> None:
    """A stack verified on one interpreter says nothing about another.

    The gate checks this on every run; asserting it here means a runtime-contract
    change that invalidates the stack survey fails a commit rather than only the
    gate somebody may not have run.
    """
    implementation, minor_line, architecture = gate._contract_values(repo_root)  # noqa: SLF001
    assert (
        plan.target_problems(
            declaration.target,
            implementation=implementation,
            minor_line=minor_line,
            architecture=architecture,
        )
        == ()
    )


def test_every_declared_library_is_a_declared_runtime_dependency(
    declaration: Declaration, manifest_document: dict[str, object]
) -> None:
    """This file may only describe libraries GLOBIN actually depends on.

    A behaviour contract for something `pyproject.toml` does not require would be
    a claim about a library nobody installs.
    """
    project = manifest_document["project"]
    assert isinstance(project, dict)
    declared = {
        entry.split(">")[0].split("=")[0].strip() for entry in project.get("dependencies", [])
    }
    assert {library.name for library in declaration.libraries} <= declared


def test_the_four_registers_agree_about_every_declared_version(
    repo_root: Path, declaration: Declaration
) -> None:
    """The comparison the gate exists to make, asserted against the committed files.

    Only the three *file* registers participate here. What is installed is a fact
    about a machine, and the CI `quality` job has neither library — so `installed`
    is supplied from the declaration and the assertion is about the files alone.
    """
    locked = gate.locked_versions(repo_root)
    bounds = gate.declared_bounds(repo_root)
    for library in declaration.libraries:
        assert (
            plan.version_problems(
                library,
                installed=library.version,
                locked=locked.get(normalise(library.name)),
                bound=bounds.get(normalise(library.name)),
            )
            == ()
        )


def test_the_declared_wheel_tag_is_the_one_the_lock_pins(
    repo_root: Path, declaration: Declaration
) -> None:
    """Provenance is a claim about an artefact, so the two records must agree.

    `pylock.toml` names the wheel filename; the contract names the tag that
    filename encodes. A tag nobody could have installed would make the provenance
    check unfalsifiable.
    """
    lock = (repo_root / "pylock.toml").read_text(encoding="utf-8")
    for library in declaration.libraries:
        assert f"-{library.wheel_tag}.whl" in lock, library.name


# ---------------------------------------------------------------------------
# The probe registry, in every direction
# ---------------------------------------------------------------------------


def test_the_declared_and_implemented_probes_agree(declaration: Declaration) -> None:
    assert plan.registry_problems(declaration, plan.implemented_probes()) == ()


def test_the_judgement_registry_and_the_callable_registry_agree() -> None:
    """Two registries that must stay equal, compared rather than trusted."""
    assert set(probes.registry()) == plan.implemented_probes()


def test_every_library_declares_at_least_one_probe(declaration: Declaration) -> None:
    assert plan.coverage_problems(declaration.libraries) == ()


def test_every_probe_records_why_it_exists(declaration: Declaration) -> None:
    """The `because` field is what separates this file from a list of names.

    A probe that cannot name the assumption it defends is decoration, and the
    first person to see it fail will have no way to judge whether it matters.
    """
    for probe in declaration.probes:
        assert len(probe.because) > 40, probe.identifier


def test_every_probe_names_the_library_it_belongs_to(declaration: Declaration) -> None:
    """The identifier's first segment is its library, as `area.subject` elsewhere."""
    names = {library.import_name for library in declaration.libraries}
    for probe in declaration.probes:
        assert probe.identifier.split(".", maxsplit=1)[0] in names, probe.identifier


def test_no_probe_reads_the_deprecated_copy_on_write_option() -> None:
    """ADR-0058's specific commitment, enforced rather than promised.

    pandas 3.0 deprecated `mode.copy_on_write` and pandas 4.0 removes it. A probe
    reading it would emit a warning today and fail on an upgrade for a reason
    unrelated to whether GLOBIN's assumption still holds.

    Matched on the syntax tree rather than on the text, because the module
    docstring and the probe's own docstring both discuss the option by name — and
    they should. What must not exist is an attribute access.
    """
    tree = ast.parse(Path(probes.__file__).read_text(encoding="utf-8"))
    reads = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "copy_on_write"
    ]
    assert not reads, f"a probe reads the deprecated option rather than the behaviour: {reads}"


# ---------------------------------------------------------------------------
# Deferrals, reasons and boundaries
# ---------------------------------------------------------------------------


def test_no_question_is_deferred_to_a_phase_that_has_shipped(declaration: Declaration) -> None:
    assert (
        plan.deferral_problems(
            declaration.deferrals,
            delivered=gate.DELIVERED_PHASE,
            total=gate.ROADMAP_TOTAL_PHASES,
        )
        == ()
    )


def test_the_boundaries_this_gate_refuses_to_decide_are_all_named(
    declaration: Declaration,
) -> None:
    """Silence must not read as a gap.

    ADR-0058 named four questions this gate does not answer, owned by Phases 113,
    158, 23 and 25. Each must appear in the declaration, so a reader learns the
    boundary from the file rather than from the record.

    **Two of those four have since been answered, and the owners moved.** Phase 025
    provisioned TA-Lib, so its question closed and what remains of it — a
    pure-Python fallback when no wheel serves the interpreter — is Phase 114's.
    Phases 023 and 024 answered the GPU question, and its residue — whether a GPU
    accelerates *this* stack, which needs a CUDA-capable library first — is Phase
    183's. ADR-0058 is immutable and still correct on its own date; this set
    tracks where those boundaries live now.
    """
    phases = {deferral.phase for deferral in declaration.deferrals}
    assert {113, 158, 114, 183} <= phases


def test_the_reason_set_matches_what_the_gate_can_emit() -> None:
    """A reason nothing produces is a claim about a check that does not exist.

    Compared against the gate's own source rather than a second list, so a reason
    added to one and not the other fails here.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    emitted = {
        name for name in manifest.REASONS if f"REASON_{name.removeprefix('STACK_')}" in source
    }
    assert emitted == set(manifest.REASONS)


def test_the_delivered_phase_bound_never_claims_more_than_has_shipped() -> None:
    """The same tripwire the wheel survey carries, for the same reason."""
    from tests.contract.test_roadmap_contract import LAST_COMPLETED_PHASE

    assert gate.DELIVERED_PHASE <= LAST_COMPLETED_PHASE


# ---------------------------------------------------------------------------
# The handoff from the wheel survey
# ---------------------------------------------------------------------------


def test_the_wheel_survey_no_longer_names_the_adopted_stack(repo_root: Path) -> None:
    """ADR-0052's rule, applied the moment Phase 022 shipped.

    A survey entry naming a delivered phase is an adoption wearing a survey's
    clothes. The question did not close; it moved to a file that can answer the
    version of it that remains.
    """
    survey = (repo_root / "docs" / "engineering" / "wheel-survey.toml").read_text(encoding="utf-8")
    for entry in ('name = "numpy"', 'name = "pandas"'):
        assert entry not in survey, entry


def test_the_gate_reaches_no_network() -> None:
    """The property that decides where this command may run.

    Asserted on the source rather than by attempting a connection: the offline
    guard refuses sockets in the *test* process, so a gate that opened one would
    be caught as a failing test rather than as the design error it is.
    """
    for module in (gate, plan, probes, manifest):
        assert module.__file__ is not None, module.__name__
        source = Path(module.__file__).read_text(encoding="utf-8")
        for reaching in ("urllib", "socket", "http.client", "requests", "subprocess"):
            assert reaching not in source, f"{module.__name__} reaches {reaching}"
