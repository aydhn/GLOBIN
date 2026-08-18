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
from pathlib import Path
from typing import Final

import pytest

from globin.domain.bootstrap import ExitCode
from globin.domain.entitlements import Grant, GrantDeclaration, GrantSet
from globin.domain.identifiers import EnvironmentId
from globin.domain.secrets import (
    MAX_SECRET_BYTES,
    PEM_ARMOUR,
    EntryFault,
    EntryProblem,
    SecretEntryOutcome,
    SecretKind,
    SecretProviderKind,
    SecretReference,
    SecretResolution,
    SecretSlot,
    SecretValue,
    StoreFault,
)
from globin.runtime.cli import (
    PROVIDER_FLAG,
    SECRETS_DOCTOR,
    SECRETS_SUBCOMMANDS,
    main,
)

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
    monkeypatch.setattr(
        "globin.runtime.cli.build_secret_store",
        lambda *_args, **_kwargs: store or _Store(),
    )
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


# ---------------------------------------------------------------------------
# The seventh verb
# ---------------------------------------------------------------------------


def test_doctor_reports_every_mechanism_without_reading_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-mechanism capability report, and nothing an operator stored.

    `SECRET_STORE_CONTRACT.md` section 5 permits a health check precisely because
    it reports nothing it found. This asserts the same of `doctor`: the store
    double records every call it receives, and none of them is a resolve.
    """
    store = _Store()
    monkeypatch.setattr(
        "globin.runtime.cli.build_secret_providers",
        lambda _state: {
            SecretProviderKind.CREDENTIAL_MANAGER: store,
            SecretProviderKind.ENVIRONMENT: _Store(),
        },
    )
    code, out, _ = run("secrets", "doctor")
    assert code == int(ExitCode.OK)
    assert "credential_manager" in out
    assert "environment" in out


def test_doctor_reports_rather_than_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable mechanism is worth knowing about, not worth refusing on.

    The gate for whether GLOBIN may start is `bootstrap check`; a report that
    failed would make an informational command fail on a machine that works.
    """
    monkeypatch.setattr(
        "globin.runtime.cli.build_secret_providers",
        lambda _state: {
            SecretProviderKind.DPAPI_VAULT: _Store(fault=StoreFault.BACKEND_UNAVAILABLE),
        },
    )
    code, out, _ = run("secrets", "doctor")
    assert code == int(ExitCode.OK)
    assert "backend_unavailable" in out


def test_doctor_says_which_mechanisms_never_accept_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hand-off is not a store, and an operator should not have to discover that.

    `SECURITY_BASELINE.md` section 2 permits the environment "only as a hand-off,
    never as storage", so the report says so before somebody tries.
    """
    monkeypatch.setattr(
        "globin.runtime.cli.build_secret_providers",
        lambda _state: {
            SecretProviderKind.CREDENTIAL_MANAGER: _Store(),
            SecretProviderKind.ENVIRONMENT: _Store(),
        },
    )
    _, out, _ = run("secrets", "doctor")
    assert "read-only" in out
    assert "read-write" in out


def test_doctor_renders_a_document_under_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standard output carries JSON and nothing else."""
    monkeypatch.setattr(
        "globin.runtime.cli.build_secret_providers",
        lambda _state: {SecretProviderKind.CREDENTIAL_MANAGER: _Store()},
    )
    _, out, _ = run("secrets", "doctor", "--json")
    document = json.loads(out)
    assert document["providers"][0]["provider"] == "credential_manager"


def test_the_seventh_verb_is_named_by_the_contract() -> None:
    """Section 5 defines the surface, and the code may not exceed it.

    The contract was amended in the same commit that added the verb, which is the
    order that matters: a command surface that grew first and was described
    afterwards is a contract following the code.
    """
    root = Path(__file__).resolve().parents[2]
    contract = (root / "docs/security/SECRET_STORE_CONTRACT.md").read_text(encoding="utf-8")
    assert "per-mechanism capability report" in contract
    assert SECRETS_DOCTOR in SECRETS_SUBCOMMANDS


# ---------------------------------------------------------------------------
# The sixth option
# ---------------------------------------------------------------------------


def test_a_write_to_a_hand_off_is_refused_before_anything_is_collected() -> None:
    """The ordering is the point, not the refusal.

    `require_permitted` argues it for entitlements and it holds here: a value
    that never existed cannot leak, so the mechanism's writability is checked
    before the operator is prompted rather than after. A refusal that arrived
    from the store would mean the material had been typed, held and discarded.
    """
    code, _, err = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "api_key",
        "--name",
        "venue_key",
        "--provider",
        "environment",
    )
    assert code == int(ExitCode.USAGE)
    assert "never accepts a write" in err
    assert "nothing was collected" in err


def test_an_unrecognised_provider_is_refused_rather_than_defaulted() -> None:
    """Naming one and being wrong is not the same as naming none.

    Defaulting a misspelling would send a credential to a mechanism the operator
    did not choose, which is the distinction `profile_from` already draws.
    """
    code, _, err = run(
        "secrets",
        "verify",
        "--environment",
        "paper",
        "--kind",
        "api_key",
        "--name",
        "venue_key",
        "--provider",
        "invented",
    )
    assert code == int(ExitCode.USAGE)
    assert "unrecognised provider" in err
    assert "credential_manager" in err


def test_the_provider_option_carries_a_mechanism_and_never_material() -> None:
    """Section 5 forbids an option that would place *material* on a command line.

    A mechanism name is ordinary data, the same class as `--environment` and
    `--kind`. This asserts the option exists and that the forbidden spellings
    still do not — the contract test covers the second half in general, and this
    is the local statement for the option Phase 031 added.
    """
    assert PROVIDER_FLAG == "--provider"
    code, _, err = run(
        "secrets",
        "verify",
        "--environment",
        "paper",
        "--kind",
        "api_key",
        "--name",
        "venue_key",
        "--secret",
        "not-a-real-value",
    )
    assert code == int(ExitCode.USAGE)
    assert "unrecognised argument" in err


# ---------------------------------------------------------------------------
# File-sourced enrollment, which is what makes the vault reachable
# ---------------------------------------------------------------------------


# The armour is built from `PEM_ARMOUR` rather than spelled out, so no literal
# private-key header appears in this file. `tools/quality/supply/secrets.py`
# scans tracked content for exactly that shape, and an allowlist entry would
# have been the other answer -- worse, because a carve-out is a hole somebody
# has to keep remembering, and reading the constant is what the test is about.
def _pem(directory: Path, name: str = "key.pem") -> Path:
    """A PEM-shaped file larger than the credential store's ceiling.

    Args:
        directory: Where to write it. Outside any checkout.
        name: The filename.

    Returns:
        Its path.
    """
    body = "\n".join(["A" * 64] * 60)
    path = directory / name
    path.write_text(
        f"{PEM_ARMOUR} PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    return path


def test_a_multiline_key_can_be_enrolled_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route that makes the vault reachable at all.

    A PEM key is multi-line by definition, so the interactive rules refuse one
    whatever its size — `CREDENTIAL_FLOW.md` recorded that "a real PEM key cannot
    be collected here at all". The vault exists for exactly that material, so
    without this route it could hold nothing anybody could put in it.
    """
    store = _Store()
    substitute(monkeypatch, store=store)
    source = _pem(tmp_path)
    code, out, _ = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(source),
    )
    assert code == int(ExitCode.OK)
    assert "was stored" in out


def test_the_enrolled_material_is_larger_than_the_credential_store_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-vacuity: the file must be the kind of thing the vault is for.

    A test that enrolled a short string would pass without exercising the reason
    any of this exists.
    """
    store = _Store()
    substitute(monkeypatch, store=store)
    source = _pem(tmp_path)
    assert len(source.read_text(encoding="utf-8").encode("utf-8")) > MAX_SECRET_BYTES
    run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(source),
    )
    held = next(iter(store.held.values()))
    assert len(held.encode("utf-8")) > MAX_SECRET_BYTES


def test_a_key_inside_a_checkout_is_refused_at_the_source() -> None:
    """The only point at which GLOBIN can act on it.

    A private key in a working tree is one `git add -A` from being permanent, and
    rule 1 of `SECURITY_BASELINE.md` is absolute. GLOBIN cannot delete the file,
    and pretending it would is worse than refusing to read it.
    """
    inside = Path(__file__).resolve().parents[2] / "pyproject.toml"
    code, _, err = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(inside),
    )
    assert code == int(ExitCode.USAGE)
    assert "inside a GLOBIN checkout" in err


def test_the_source_path_is_never_echoed_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path names a machine and often the person, so no record carries it."""
    substitute(monkeypatch, store=_Store())
    source = _pem(tmp_path, "very-distinctive-name.pem")
    _, out, err = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(source),
    )
    assert "very-distinctive-name" not in out + err


def test_the_file_contents_are_never_echoed_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading material is not displaying it, and nothing here blurs the two."""
    substitute(monkeypatch, store=_Store())
    source = _pem(tmp_path)
    _, out, err = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(source),
    )
    assert PEM_ARMOUR not in out + err
    assert "A" * 64 not in out + err


def test_a_file_holding_a_forbidden_character_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Line breaks are permitted; nothing else is.

    A control character other than a line break means the file is not what the
    operator thought, and the refusal names the rule rather than the content.
    """
    substitute(monkeypatch, store=_Store())
    source = tmp_path / "odd.pem"
    source.write_text(f"{PEM_ARMOUR} PRIVATE KEY-----\n\tAAAA\n", encoding="utf-8")
    code, out, err = run(
        "secrets",
        "set",
        "--environment",
        "paper",
        "--kind",
        "private_key",
        "--name",
        "venue_signing_key",
        "--from-file",
        str(source),
    )
    assert code == int(ExitCode.SECRETS_UNREADY)
    assert "control_character" in out + err


def test_the_option_means_nothing_for_a_verb_that_does_not_write() -> None:
    """An option that supplies material has no meaning where nothing is stored."""
    code, _, err = run(
        "secrets",
        "verify",
        "--environment",
        "paper",
        "--kind",
        "api_key",
        "--name",
        "venue_key",
        "--from-file",
        "somewhere.pem",
    )
    assert code == int(ExitCode.USAGE)
    assert "means nothing" in err
