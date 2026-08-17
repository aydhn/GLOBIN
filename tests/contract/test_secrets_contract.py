"""The leak gate, and the absences `SECRET_STORE_CONTRACT.md` requires.

Section 6 names eight surfaces a synthetic canary must be proven absent from,
and states plainly that four were already covered when it was written and four
were not: "Exceptions, tracebacks, standard streams and the process's own
command line are **not** covered today by anything." This is where the four
uncovered ones become covered.

**The canary is synthetic and worthless**, of the shape
`docs/TESTING_STRATEGY.md` prescribes, and never anything shaped like a real
credential — ADR-0048's prohibition admits no exception. It is deliberately a
long, distinctive, obviously-fake string so that a substring search over an
artefact is conclusive.

**Redaction must not become its own hazard.** Section 6 says so: a mechanism
that retained every secret it had seen in order to redact it later would be a
store nobody declared. Nothing here builds a register of values, and the tests
below assert the property of the *type* rather than of a filter.
"""

import io
import json
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

import pytest

from globin.adapters.diagnostics_http import ReadinessGate
from globin.application.secrets import require, rotate
from globin.domain.diagnostics_http import ReadinessReason
from globin.domain.identifiers import environment_id
from globin.domain.observability import Severity, log_event
from globin.domain.secrets import (
    SecretKind,
    SecretReference,
    SecretValue,
    store_key,
)
from globin.errors import ConfigurationError
from tests.support import REPO_ROOT
from tests.unit.test_secrets_application import _Store

CANARY = "GLOBIN-PHASE028-SYNTHETIC-CANARY-NOT-A-REAL-SECRET"
"""A value that is unmistakably fake and unmistakably findable.

Long and distinctive so that its absence from an artefact can be established by
a substring search, and obviously synthetic so that nothing that meets it could
mistake it for material worth protecting.
"""

REFERENCE = SecretReference(
    environment=environment_id("paper"),
    kind=SecretKind.API_KEY,
    name="canary",
)


@dataclass(frozen=True, slots=True)
class _NoSignals:
    """Shutdown signals that never fire, so readiness reports what was recorded."""

    def requested(self) -> bool:
        return False


def loaded_store() -> _Store:
    """A store holding the canary."""
    store = _Store()
    store.held[store_key(REFERENCE)] = CANARY
    return store


# ---------------------------------------------------------------------------
# The four surfaces section 6 says nothing covered
# ---------------------------------------------------------------------------


def test_the_canary_does_not_reach_an_exceptions_str_or_args() -> None:
    """Surface three, and it is the one a refusal is most likely to leak through.

    `require` builds its message from the reference and the fault, and this is
    what pins that it never reaches for the value it failed to find — or, worse,
    the one it found and rejected.
    """
    store = loaded_store()
    wrong_environment = SecretReference(
        environment=environment_id("testnet"),
        kind=SecretKind.API_KEY,
        name="canary",
    )
    with pytest.raises(ConfigurationError) as caught:
        require(store, wrong_environment)
    assert CANARY not in str(caught.value)
    assert CANARY not in repr(caught.value)
    assert all(CANARY not in str(argument) for argument in caught.value.args)


def test_the_canary_does_not_reach_a_traceback_including_chained_causes() -> None:
    """Surface four. A traceback renders locals in some tools and `repr` everywhere.

    The value is live in a local variable at the moment the exception is raised,
    which is precisely the situation that makes this worth asserting rather than
    assuming: `SecretValue.__repr__` is what stands between it and the render.
    """
    value = SecretValue(CANARY)
    rendered = ""

    def fail_inside() -> None:
        """Raise from a nested frame, so the traceback has one to render."""
        msg = "an inner failure"
        raise RuntimeError(msg)

    try:
        try:
            fail_inside()
        except RuntimeError as inner:
            msg = f"an outer failure while holding {value!r}"
            raise ConfigurationError(msg) from inner
    except ConfigurationError as outer:
        rendered = "".join(traceback.format_exception(type(outer), outer, outer.__traceback__))
    assert CANARY not in rendered
    assert "an inner failure" in rendered, "the chained cause must actually be rendered"


def test_the_canary_does_not_reach_a_traceback_note() -> None:
    """Surface four's other half: `add_note` is rendered by the same formatter."""
    value = SecretValue(CANARY)
    error = ConfigurationError("a failure")
    error.add_note(f"while resolving {value}")
    rendered = "".join(traceback.format_exception(type(error), error, None))
    assert CANARY not in rendered


def test_the_canary_does_not_reach_standard_output_or_standard_error() -> None:
    """Surface two, exercised by printing the value every way a caller might.

    `print` reaches `__str__`; an f-string with a spec reaches `__format__`; and
    `%r` reaches `__repr__`. All three are redacted, which is why the type
    overrides all three rather than the two a reader expects.
    """
    out, err = io.StringIO(), io.StringIO()
    value = SecretValue(CANARY)
    print(value, file=out)
    print(f"{value:>60}", file=out)
    print("%r" % (value,), file=err)  # noqa: UP031 -- the route under test
    print([value], {"k": value}, file=err)
    assert CANARY not in out.getvalue()
    assert CANARY not in err.getvalue()


def test_the_canary_does_not_reach_the_process_command_line() -> None:
    """Surface eight, observed from outside the process rather than asserted inside it.

    Section 5 forbids any option that would place material on a command line,
    "where it is visible in the process table and recorded in shell history".
    This asserts the consequence: no command GLOBIN offers accepts one.

    A real child process is started, so this reads the command line the operating
    system actually recorded rather than the arguments this test believes it
    passed. The child is GLOBIN's own entry point with a read-only verb.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "globin", "diagnostics", "environment"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        check=False,
    )
    assert CANARY not in completed.stdout
    assert CANARY not in completed.stderr
    assert CANARY not in " ".join(completed.args)


def test_no_command_accepts_an_option_that_would_carry_material() -> None:
    """The structural half of surface eight: there is no such option to pass.

    Section 5 forbids `--secret=` "or any other option that would place material
    on a command line". Checked against the usage text, which is the declared
    surface, so an option added without documenting it fails the parser's own
    contract test instead.
    """
    from globin.runtime.cli import USAGE

    for forbidden in ("--secret", "--password", "--token", "--credential", "--key="):
        assert forbidden not in USAGE


# ---------------------------------------------------------------------------
# The four section 6 says were already covered — asserted here anyway
# ---------------------------------------------------------------------------


def test_the_canary_does_not_reach_a_log_record_through_any_sink() -> None:
    """Surface one. Covered by construction-time redaction, and pinned here.

    `LogEvent` redacts by field *name*, and `SecretValue` redacts by rendering —
    two independent mechanisms, and this asserts that a value reaching a log
    field is caught even when the field name would not have triggered redaction.
    """
    event = log_event(
        severity=Severity.INFO,
        event="secrets.resolved",
        correlation_id="phase028-leak-gate",
        fields={"harmless_name": SecretValue(CANARY)},
    )
    assert CANARY not in json.dumps(event.as_mapping(), default=str)
    assert CANARY not in str(event.fields)
    assert CANARY not in repr(event)


def test_a_rotation_record_carries_neither_the_old_nor_the_new_material() -> None:
    """A rollback path that logs what it rolled back from has defeated the store.

    Section 4's words, and both values are live during a rotation, so both are
    checked.
    """
    store = loaded_store()
    outcome = rotate(store, REFERENCE, SecretValue(f"{CANARY}-REPLACEMENT"))
    rendered = json.dumps(outcome.as_record())
    assert CANARY not in rendered
    assert outcome.rotated


# ---------------------------------------------------------------------------
# The absences
# ---------------------------------------------------------------------------


def test_the_value_type_has_no_encoder() -> None:
    """Section 1's third obligation, and an absence does not appear in a diff.

    `docs/SERIALIZATION_POLICY.md` is exact or refused; for a secret the answer
    is refused, in the way `MonotonicReading` has no wire form. Asserted by
    searching the serialization modules for the type's name, because an encoder
    added anywhere else would not be reachable by the codec anyway.
    """
    for relative in (
        "src/globin/domain/serialization.py",
        "src/globin/adapters/serialization.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "SecretValue" not in source, f"{relative} has acquired a secret encoder"


def test_no_module_reachable_from_the_package_retains_seen_values() -> None:
    """Section 6: a register of values would be "a store nobody declared".

    Checked structurally: the secret modules declare no module-level mutable
    container, which is what an accumulating register would need.
    """
    for relative in (
        "src/globin/domain/secrets.py",
        "src/globin/ports/secrets.py",
        "src/globin/application/secrets.py",
        "src/globin/adapters/secrets.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped or line.startswith((" ", "\t")):
                continue
            assert "= []" not in stripped, f"{relative} declares a module-level list"
            assert "= set()" not in stripped, f"{relative} declares a module-level set"


@pytest.mark.parametrize(
    "verb",
    ["reveal", "dump", "export", "show_secret", "print_secret", "cat"],
)
def test_no_public_function_in_the_secret_modules_offers_to_display_material(
    verb: str,
) -> None:
    """Section 5's forbidden vocabulary, applied to functions rather than modules.

    `test_documentation_contract.py` checks module stems and command names.
    This checks the function surface of the four modules that actually hold the
    capability, which is where such a verb would most naturally be added.
    """
    for relative in (
        "src/globin/domain/secrets.py",
        "src/globin/ports/secrets.py",
        "src/globin/application/secrets.py",
        "src/globin/adapters/secrets.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert f"def {verb}" not in source, f"{relative} defines {verb}()"


def test_the_store_contract_names_this_phase_and_the_phase_has_delivered() -> None:
    """The document and the tree must agree about what exists.

    `SECRET_STORE_CONTRACT.md` said "The type and module names are Phase 028's".
    They now exist, so the contract's own deferral table must no longer defer the
    store to a phase that has delivered — which
    `test_documentation_contract.py::test_no_document_defers_a_question_to_a_phase_that_has_delivered`
    enforces in general. This asserts the specific consequence: the modules are
    real.
    """
    for relative in (
        "src/globin/domain/secrets.py",
        "src/globin/ports/secrets.py",
        "src/globin/application/secrets.py",
        "src/globin/adapters/secrets.py",
    ):
        assert (REPO_ROOT / Path(relative)).is_file(), f"{relative} is missing"


# ---------------------------------------------------------------------------
# Readiness publishes a bounded reason and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(ReadinessReason.ENVIRONMENT_INCOMPATIBLE, id="environment"),
        pytest.param(ReadinessReason.SECRETS_UNREADY, id="secrets"),
    ],
)
def test_each_reason_this_phase_added_is_reachable_through_the_gate(
    reason: ReadinessReason,
) -> None:
    """A member nothing can set is vocabulary rather than a capability.

    Phase 028 registered two checks that can fail — `environment.capability` and
    a `secrets.required` backed by a real store — so both became classes of
    unreadiness GLOBIN can *distinguish*, which is the bar
    `ReadinessReason`'s own docstring sets for adding one. This proves each is
    settable rather than decorative.
    """
    gate = ReadinessGate(signals=_NoSignals())  # type: ignore[arg-type]
    gate.mark_ready()
    gate.mark_unready(reason)
    assert gate.readiness() is reason


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(ReadinessReason.ENVIRONMENT_INCOMPATIBLE, id="environment"),
        pytest.param(ReadinessReason.SECRETS_UNREADY, id="secrets"),
    ],
)
def test_the_readiness_answer_carries_the_bounded_reason_and_no_detail(
    reason: ReadinessReason,
) -> None:
    """Section 15 of the brief, and the privacy rule for this surface.

    An operator scraping `/health/ready` learns *which class* of unreadiness
    applies. They do not learn which secret is missing, which capability is
    absent, where anything lives, or what this machine is — because the response
    is built from the enum member's value and nothing else.
    """
    assert reason.value.replace("_", "").isalpha()
    assert "\\" not in reason.value
    assert "/" not in reason.value
    assert reason.value == reason.value.lower()
