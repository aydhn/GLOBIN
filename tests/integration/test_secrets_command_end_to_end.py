"""The `globin secrets` command group, driven through `main` over real streams.

Every verb is exercised the way an operator reaches it — an argument vector, a
captured standard output and a captured standard error — because the parser, the
composition root and the renderers are what this file exists to cover, and a test
that called the handlers directly would skip all three.

**Nothing here stores a credential.** The two writing verbs refuse before any
material exists: pytest replaces standard input, so it is not a terminal, and
collection is interactive only. That is not a limitation of the test; it is the
refusal that stops a key reaching shell history, exercised for real.

The value that would be a secret if this held one is a canary, and several tests
assert it appears in no stream and no record.
"""

import io
import json
from typing import Final

import pytest

from globin.domain.bootstrap import ExitCode
from globin.domain.entitlements import Grant, GrantDeclaration, GrantSet
from globin.domain.identifiers import EnvironmentId
from globin.domain.secrets import (
    EntryFault,
    EntryProblem,
    SecretEntryOutcome,
    SecretKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.runtime.cli import main

pytestmark = pytest.mark.integration

CANARY: Final[str] = "GLOBIN-PHASE029-SYNTHETIC-CANARY-NOT-A-REAL-SECRET"
"""A value that must reach no stream, no record and no usage text."""

REFERENCE: Final[tuple[str, ...]] = (
    "--environment",
    "paper",
    "--kind",
    "api_key",
    "--name",
    "phase029_probe",
)
"""A reference naming a credential this repository has never written."""


def run(*argv: str) -> tuple[int, str, str]:
    """One command, with both streams captured.

    Args:
        argv: The arguments after the program name.

    Returns:
        The exit code, standard output and standard error.
    """
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def test_the_group_needs_a_subcommand_and_names_them_all() -> None:
    """There is no default: two of these write and one deletes."""
    code, _out, err = run("secrets")
    assert code == int(ExitCode.USAGE)
    for verb in ("set", "verify", "list", "delete", "rotate", "health"):
        assert verb in err


def test_an_unknown_subcommand_is_refused_rather_than_guessed() -> None:
    code, _out, err = run("secrets", "frobnicate")
    assert code == int(ExitCode.USAGE)
    assert "frobnicate" in err


@pytest.mark.parametrize(
    "option",
    [
        pytest.param("--secret", id="secret"),
        pytest.param("--value", id="value"),
        pytest.param("--material", id="material"),
        pytest.param("--password", id="password"),
    ],
)
def test_no_option_can_place_material_on_a_command_line(option: str) -> None:
    """SECRET_STORE_CONTRACT.md section 5 forbids exactly this.

    Every unrecognised word is refused, so a caller reaching for one of these
    gets a usage error rather than a credential in their shell history.
    """
    code, _out, err = run("secrets", "set", option, CANARY)
    assert code == int(ExitCode.USAGE)
    assert CANARY not in err


def test_an_option_given_twice_is_refused() -> None:
    code, _out, err = run("secrets", "list", "--json", "--json")
    assert code == int(ExitCode.USAGE)
    assert "twice" in err


def test_an_option_that_needs_a_value_is_refused_without_one() -> None:
    code, _out, err = run("secrets", "verify", "--environment")
    assert code == int(ExitCode.USAGE)
    assert "needs a value" in err


def test_an_option_whose_value_is_another_option_is_refused() -> None:
    """The case that would otherwise swallow the flag after it."""
    code, _out, _err = run("secrets", "verify", "--environment", "--json")
    assert code == int(ExitCode.USAGE)


@pytest.mark.parametrize(
    "verb",
    [pytest.param("set", id="set"), pytest.param("rotate", id="rotate")],
)
def test_json_is_refused_for_a_verb_whose_act_is_a_prompt(verb: str) -> None:
    """Offering a document for a prompt invites somebody to script it."""
    code, _out, err = run("secrets", verb, "--json", *REFERENCE)
    assert code == int(ExitCode.USAGE)
    assert "--json" in err


# ---------------------------------------------------------------------------
# Building a reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(("--kind", "api_key", "--name", "x"), "--environment", id="no-environment"),
        pytest.param(("--environment", "paper", "--name", "x"), "--kind", id="no-kind"),
        pytest.param(("--environment", "paper", "--kind", "api_key"), "--name", id="no-name"),
    ],
)
def test_every_part_of_a_reference_is_required(argv: tuple[str, ...], expected: str) -> None:
    code, _out, err = run("secrets", "verify", *argv)
    assert code == int(ExitCode.USAGE)
    assert expected in err


def test_a_kind_outside_the_bounded_set_is_refused_and_lists_the_set() -> None:
    code, _out, err = run(
        "secrets", "verify", "--environment", "paper", "--kind", "nonsense", "--name", "x"
    )
    assert code == int(ExitCode.USAGE)
    assert "api_key" in err


def test_a_name_the_reference_type_refuses_is_reported_rather_than_raised() -> None:
    """`SecretReference` validates its own name; the CLI turns that into usage."""
    code, _out, err = run(
        "secrets", "verify", "--environment", "paper", "--kind", "api_key", "--name", "NOT VALID!"
    )
    assert code == int(ExitCode.USAGE)
    assert "usable reference" in err


def test_an_environment_that_is_not_an_identifier_is_refused() -> None:
    code, _out, _err = run(
        "secrets", "verify", "--environment", "NOT VALID!", "--kind", "api_key", "--name", "x"
    )
    assert code == int(ExitCode.USAGE)


# ---------------------------------------------------------------------------
# The read-only verbs
# ---------------------------------------------------------------------------


def test_listing_declarations_writes_a_document_and_nothing_else() -> None:
    """Under `--json`, standard output carries the document alone."""
    code, out, _err = run("secrets", "list", "--json")
    assert code == int(ExitCode.OK)
    document = json.loads(out)
    assert isinstance(document["declarations"], list)


def test_listing_in_human_form_says_when_nothing_is_declared() -> None:
    code, out, _err = run("secrets", "list")
    assert code == int(ExitCode.OK)
    assert "declared" in out


def test_the_store_reports_its_own_availability() -> None:
    """A backend health check, which section 5 permits and this exercises."""
    code, out, _err = run("secrets", "health", "--json")
    document = json.loads(out)
    assert isinstance(document["available"], bool)
    assert code == int(ExitCode.OK if document["available"] else ExitCode.SECRETS_UNREADY)


def test_health_in_human_form_says_which_way_it_went() -> None:
    _code, out, _err = run("secrets", "health")
    assert "secret store is" in out


def test_verifying_a_credential_nobody_wrote_reports_it_as_absent() -> None:
    """The outcome is asked for; no value is read, returned or held."""
    code, out, _err = run("secrets", "verify", "--json", *REFERENCE)
    document = json.loads(out)
    assert document["present"] is False
    assert document["name"] == "phase029_probe"
    assert code == int(ExitCode.SECRETS_UNREADY)


def test_verifying_in_human_form_names_the_reference_and_no_value() -> None:
    _code, out, _err = run("secrets", "verify", *REFERENCE)
    assert "phase029_probe" in out
    assert CANARY not in out


def test_deleting_a_credential_nobody_wrote_reports_the_fault() -> None:
    code, out, _err = run("secrets", "delete", "--json", *REFERENCE)
    document = json.loads(out)
    assert document["deleted"] is False
    assert code == int(ExitCode.SECRETS_UNREADY)


def test_deleting_in_human_form_says_what_happened() -> None:
    _code, out, _err = run("secrets", "delete", *REFERENCE)
    assert "phase029_probe" in out


# ---------------------------------------------------------------------------
# The writing verbs, which refuse here
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb",
    [pytest.param("set", id="set"), pytest.param("rotate", id="rotate")],
)
def test_a_writing_verb_refuses_because_this_is_not_a_terminal(verb: str) -> None:
    """The refusal that stops a key reaching shell history, exercised for real.

    pytest replaces standard input, so it is not a terminal. Collection is
    interactive only, and the refusal happens before `getpass` is called at all.
    """
    code, out, err = run("secrets", verb, *REFERENCE)
    assert code == int(ExitCode.SECRETS_UNREADY)
    assert "not_interactive" in out
    assert "terminal" in err


@pytest.mark.parametrize(
    "verb",
    [pytest.param("set", id="set"), pytest.param("rotate", id="rotate")],
)
def test_a_refused_collection_stores_nothing(verb: str) -> None:
    """Afterwards the credential is still absent, which is the observable claim."""
    run("secrets", verb, *REFERENCE)
    _code, out, _err = run("secrets", "verify", "--json", *REFERENCE)
    assert json.loads(out)["present"] is False


# ---------------------------------------------------------------------------
# What no surface may carry
# ---------------------------------------------------------------------------


def test_the_usage_text_offers_no_way_to_reveal_a_secret() -> None:
    """Section 5's absence requirement, read off the surface a person sees."""
    _code, out, _err = run("--help")
    lowered = out.lower()
    for forbidden in ("--secret", "--value=", "reveal", "show-secret", "print-secret"):
        assert forbidden not in lowered


def test_the_usage_text_documents_the_group_and_its_exit_code() -> None:
    _code, out, _err = run("--help")
    assert "secrets set" in out
    assert "secrets rotate" in out
    assert "--environment" in out
    assert str(int(ExitCode.CREDENTIAL_NOT_ENTITLED)) in out


# ---------------------------------------------------------------------------
# The rendering paths, with the composition root substituted
# ---------------------------------------------------------------------------


class _Register:
    """A grant register holding whatever a test declares."""

    def __init__(self, declarations: tuple[GrantDeclaration, ...] = ()) -> None:
        self._declarations = declarations
        self.declared: list[GrantDeclaration] = []

    def declarations(self) -> tuple[GrantDeclaration, ...]:
        return self._declarations

    def declare(self, declaration: GrantDeclaration) -> bool:
        self.declared.append(declaration)
        return True


class _Store:
    """A store that actually holds what it is given, per slot.

    Holding rather than answering a fixed value matters for `rotate`: the
    four-step procedure writes the replacement and then **reads it back and
    compares**, so a double that always returned the same string would make
    every rotation fail verification. Encoding that here is cheaper than
    rediscovering it.
    """

    def __init__(self, fault: StoreFault | None = None) -> None:
        self.fault = fault
        self.stored: list[SecretReference] = []
        self.held: dict[tuple[SecretReference, SecretSlot], str] = {}

    def health(self) -> StoreFault | None:
        return self.fault

    def resolve(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> SecretResolution:
        if self.fault is not None:
            return SecretResolution(reference=reference, fault=self.fault)
        material = self.held.get((reference, slot))
        if material is None:
            return SecretResolution(reference=reference, fault=StoreFault.ABSENT)
        return SecretResolution(reference=reference, value=SecretValue(material))

    def store(
        self,
        reference: SecretReference,
        value: SecretValue,
        slot: SecretSlot = SecretSlot.CURRENT,
    ) -> StoreFault | None:
        if self.fault is not None:
            return self.fault
        self.stored.append(reference)
        self.held[(reference, slot)] = value.material()
        return None

    def delete(
        self, reference: SecretReference, slot: SecretSlot = SecretSlot.CURRENT
    ) -> StoreFault | None:
        if self.fault is not None:
            return self.fault
        self.held.pop((reference, slot), None)
        return None

    def inventory(self) -> tuple[SecretReference, ...]:
        return ()


class _Entry:
    """A console entry that answers however a test needs."""

    def __init__(self, outcome: SecretEntryOutcome) -> None:
        self.outcome = outcome

    def collect(self, prompt: str) -> SecretEntryOutcome:
        del prompt
        return self.outcome


def substitute(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: _Store | None = None,
    register: _Register | None = None,
    entry: _Entry | None = None,
) -> None:
    """Replace the three builders the secrets commands reach for.

    Patched where they are *used* rather than where they are defined, which is
    what `docs/TESTING_STRATEGY.md` requires.
    """
    monkeypatch.setattr("globin.runtime.cli.build_secret_store", lambda: store or _Store())
    monkeypatch.setattr(
        "globin.runtime.cli.build_grant_register", lambda _state: register or _Register()
    )
    if entry is not None:
        monkeypatch.setattr("globin.runtime.cli.build_secret_entry", lambda _stream: entry)


REFERENCE_OBJECT: Final[SecretReference] = SecretReference(
    environment=EnvironmentId("paper"),
    kind=SecretKind.API_KEY,
    name="phase029_probe",
)


def test_an_unavailable_store_reports_the_fault_and_its_remedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    substitute(monkeypatch, store=_Store(fault=StoreFault.BACKEND_UNAVAILABLE))
    code, out, err = run("secrets", "health")
    assert code == int(ExitCode.SECRETS_UNREADY)
    assert "unavailable" in out
    assert err.strip()


def test_declarations_are_listed_one_per_line_with_their_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register = _Register(
        (
            GrantDeclaration(
                reference=REFERENCE_OBJECT, declared=GrantSet((Grant.READ, Grant.SUBMIT))
            ),
        )
    )
    substitute(monkeypatch, register=register)
    code, out, _err = run("secrets", "list")
    assert code == int(ExitCode.OK)
    assert "paper/api_key/phase029_probe: read, submit" in out


def test_a_declaration_of_nothing_says_nothing_rather_than_showing_a_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register = _Register((GrantDeclaration(reference=REFERENCE_OBJECT, declared=GrantSet()),))
    substitute(monkeypatch, register=register)
    _code, out, _err = run("secrets", "list")
    assert "nothing" in out


def test_a_credential_that_resolves_is_reported_present_with_its_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register = _Register(
        (GrantDeclaration(reference=REFERENCE_OBJECT, declared=GrantSet((Grant.READ,))),)
    )
    store = _Store()
    store.store(REFERENCE_OBJECT, SecretValue("material"), SecretSlot.CURRENT)
    substitute(monkeypatch, store=store, register=register)
    code, out, _err = run("secrets", "verify", *REFERENCE)
    assert code == int(ExitCode.OK)
    assert "is present" in out
    assert "read" in out


def test_a_credential_that_is_deleted_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    substitute(monkeypatch, store=_Store())
    code, out, _err = run("secrets", "delete", *REFERENCE)
    assert code == int(ExitCode.OK)
    assert "was removed" in out


def test_a_collected_credential_is_stored_and_declared_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path, and it declares nothing -- which is Phase 039's flow."""
    store, register = _Store(), _Register()
    substitute(
        monkeypatch,
        store=store,
        register=register,
        entry=_Entry(SecretEntryOutcome(value=SecretValue(CANARY))),
    )
    code, out, err = run("secrets", "set", *REFERENCE)
    assert code == int(ExitCode.OK)
    assert "was stored" in out
    assert store.stored == [REFERENCE_OBJECT]
    assert register.declared[0].declared.names() == ()
    assert CANARY not in out
    assert CANARY not in err


def test_a_rotation_reaches_the_store_through_the_four_step_procedure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()
    substitute(
        monkeypatch,
        store=store,
        entry=_Entry(SecretEntryOutcome(value=SecretValue("replacement"))),
    )
    code, out, _err = run("secrets", "rotate", *REFERENCE)
    assert code == int(ExitCode.OK)
    assert "was stored" in out


def test_a_store_that_refuses_the_write_reports_its_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    substitute(
        monkeypatch,
        store=_Store(fault=StoreFault.BACKEND_REFUSED),
        entry=_Entry(SecretEntryOutcome(value=SecretValue("material"))),
    )
    code, out, err = run("secrets", "set", *REFERENCE)
    assert code == int(ExitCode.SECRETS_UNREADY)
    assert "backend_refused" in out
    assert err.strip()


def test_a_refused_format_names_every_rule_it_broke_and_no_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    substitute(
        monkeypatch,
        entry=_Entry(
            SecretEntryOutcome(
                fault=EntryFault.REFUSED_FORMAT,
                problems=(EntryProblem.SURROUNDING_WHITESPACE, EntryProblem.TOO_LARGE),
            )
        ),
    )
    code, out, err = run("secrets", "set", *REFERENCE)
    assert code == int(ExitCode.SECRETS_UNREADY)
    assert "refused_format" in out
    assert "surrounding_whitespace" in err
    assert "too_large" in err
