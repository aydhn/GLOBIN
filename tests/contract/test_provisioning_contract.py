"""The provisioning surface's contract: the verbs, the vocabulary, and the refusals.

Three kinds of assertion live here. The **verb contract** is what an operator
types and what a launcher branches on, so it is pinned rather than derived. The
**vocabulary contract** is that Phase 032 named a second enum instead of widening
an existing one, which is the decision this phase most needs held. And the
**refusal contract** is the set of things this phase deliberately does not do,
each asserted so that adding one later is a visible edit to a test rather than a
quiet capability.
"""

import json
import re
from pathlib import Path

import pytest

from globin.adapters.provisioning import (
    ENVIRONMENT_ALLOWLIST,
    MANIFEST_NAME,
    SCHEMA,
    SCHEMA_VERSION,
    build,
    child_environment,
)
from globin.application.provisioning import recreate_mutations, setup_mutations
from globin.domain.bootstrap import CheckStatus, ExitCode
from globin.domain.observability import SENSITIVE_KEY_FRAGMENTS, is_sensitive
from globin.domain.process import SHELL_METACHARACTERS, HostCapability, Tool, probe_commands
from globin.domain.provisioning import (
    ActionOutcome,
    MutationClass,
    NetworkPolicy,
    NetworkRequirement,
    Performer,
    Privilege,
    ProvisioningJournal,
    ProvisioningPlan,
    actions,
)
from globin.runtime import cli

#: Every provisioning verb, written out rather than derived from the tuple it is
#: checking. A test computing these from the constant would pass whatever the
#: constant said, which is the opposite of pinning a contract.
EXPECTED_SUBCOMMANDS: tuple[str, ...] = (
    "check",
    "evidence",
    "preflight",
    "plan",
    "setup",
    "repair",
)


def test_the_bootstrap_verbs_are_the_ones_declared() -> None:
    """What an operator may type, pinned."""
    assert cli.BOOTSTRAP_SUBCOMMANDS == EXPECTED_SUBCOMMANDS


def test_only_two_verbs_may_change_the_host() -> None:
    """`check`, `evidence`, `preflight` and `plan` are read-only, and stay so."""
    assert cli.BOOTSTRAP_MUTATING == ("setup", "repair")
    assert set(cli.BOOTSTRAP_MUTATING) <= set(cli.BOOTSTRAP_SUBCOMMANDS)


def test_the_default_verb_changes_nothing() -> None:
    """`globin bootstrap` with no subcommand must not be a mutating command."""
    assert cli.parse(["bootstrap"]).command == "bootstrap check"


def test_every_verb_appears_in_the_usage_text() -> None:
    """A verb nobody can discover is a verb nobody uses correctly."""
    missing = [word for word in cli.BOOTSTRAP_SUBCOMMANDS if f"bootstrap {word}" not in cli.USAGE]
    assert not missing, f"these verbs are undocumented in --help: {missing}"


# ---------------------------------------------------------------------------
# The retired word
# ---------------------------------------------------------------------------


def test_every_retired_word_redirects_to_a_command_that_parses() -> None:
    """The redirect cannot rot into naming something that no longer exists."""
    for word, replacement in cli.RETIRED_WORDS.items():
        assert cli.parse(replacement.split()).command == replacement, (
            f"`{word}` redirects to `{replacement}`, which is not a command line that parses"
        )


def test_verify_is_refused_by_name_rather_than_as_an_unknown_word() -> None:
    """A bare "unrecognised argument" teaches nothing.

    `verify` is the obvious name for what `bootstrap preflight` is, and the word
    is already taken at this repository's shell by `scripts/verify.ps1`. Adding a
    synonym would give one subject two owners; refusing without naming the
    replacement would make an operator guess.
    """
    with pytest.raises(cli.UsageError, match="there is no `verify`"):
        cli.parse(["bootstrap", "verify"])


def test_no_retired_word_is_also_a_live_subcommand() -> None:
    """Guard the guard: a word cannot be both refused and accepted."""
    assert not set(cli.RETIRED_WORDS) & set(cli.BOOTSTRAP_SUBCOMMANDS)


# ---------------------------------------------------------------------------
# The network policy is declared, never probed
# ---------------------------------------------------------------------------


def test_the_network_flag_defaults_to_the_most_restrictive_policy() -> None:
    """The one command that mutates must not also reach the network unasked."""
    assert cli.parse(["bootstrap", "setup"]).network == ""
    assert NetworkPolicy.OFFLINE.value == "offline"


def test_the_network_flag_takes_only_a_declared_policy() -> None:
    with pytest.raises(cli.UsageError, match="takes one of"):
        cli.parse(["bootstrap", "plan", "--network", "whatever"])


def test_the_network_flag_is_refused_where_it_would_mean_nothing() -> None:
    """A flag that silently does nothing is how a caller comes to believe it asked."""
    with pytest.raises(cli.UsageError, match="means nothing with check"):
        cli.parse(["bootstrap", "check", "--network", "offline"])


def test_the_destructive_flag_is_refused_outside_the_two_verbs_that_use_it() -> None:
    with pytest.raises(cli.UsageError, match="means nothing with setup"):
        cli.parse(["bootstrap", "setup", "--recreate"])


def test_the_destructive_flag_is_accepted_where_it_means_something() -> None:
    assert cli.parse(["bootstrap", "repair", "--recreate"]).recreate is True
    assert cli.parse(["bootstrap", "plan", "--recreate"]).recreate is True


# ---------------------------------------------------------------------------
# The vocabulary was named, not widened
# ---------------------------------------------------------------------------


def test_the_check_status_vocabulary_is_unchanged() -> None:
    """Phase 032 added no member to the enum that already existed.

    The brief asked for `BLOCKED` and `SKIPPED`. `UNMEASURED` already means what
    `BLOCKED` means -- the acceptance matrix's own header says the gate maps one
    onto the other -- and `SKIPPED` is a statement about an action rather than a
    measurement, so it went to `ActionOutcome`. A third vocabulary in the phase
    that exists to pay down inconsistency would have been the defect itself.
    """
    assert {member.name for member in CheckStatus} == {"PASS", "FAIL", "WARN", "UNMEASURED"}


def test_the_two_outcome_vocabularies_are_disjoint() -> None:
    """A word meaning two things in two enums is worse than two words."""
    assert not {member.value for member in ActionOutcome} & {member.value for member in CheckStatus}


def test_the_action_vocabulary_says_satisfied_rather_than_skipped() -> None:
    """The distinction an idempotency test turns on.

    "Skipped" is a statement about the scheduler and proves nothing about the
    host. "Satisfied" asserts the postcondition holds, which is what a second
    `setup` run needs to be able to say.
    """
    assert ActionOutcome.SATISFIED.value == "satisfied"
    assert "skipped" not in {member.value for member in ActionOutcome}


def test_no_twenty_sixth_exit_code_was_added() -> None:
    """Phase 031 left 26 free, and Phase 032 leaves it free.

    Every refusal this phase produces maps onto a code that already exists: an
    interrupted environment is `ENVIRONMENT_MISMATCH`, whose published sentence
    is exactly true of a half-built one.
    """
    assert 26 not in {int(code) for code in ExitCode}


def test_the_usage_text_still_records_that_twenty_six_is_free() -> None:
    """The claim is in the help output, so it is checked there too."""
    assert re.search(r"\b26\b", cli.USAGE) is None or "26" in cli.USAGE


# ---------------------------------------------------------------------------
# What this phase deliberately does not do
# ---------------------------------------------------------------------------


def test_no_action_can_reach_a_credential_or_a_configuration_document() -> None:
    """The structural boundary, asserted at the contract level too.

    `ActionSpec` refuses to construct one; this says the catalogue as shipped has
    none, so a reader does not have to trust the constructor.
    """
    answered = [remedy for spec in actions() for remedy in spec.remedy_for]
    assert not [name for name in answered if name.startswith(("secrets.", "config."))]


def test_nothing_installs_a_python_runtime() -> None:
    """Runtime installation stays where it already is, behind its own opt-in.

    `tools/quality/runtime` carries `--install-python`, and reports that this
    host's launcher cannot install. An action here would be a second route to a
    capability one place already owns.
    """
    assert not [spec for spec in actions() if "runtime" in spec.identifier]


def test_every_action_globin_cannot_perform_names_the_command_that_can() -> None:
    """The packaging forced this, and the wheel is the evidence.

    GLOBIN's wheel holds the package and its metadata and nothing else -- no
    `tools/`, no `scripts/` -- so an installed GLOBIN cannot invoke either. An
    executor that shelled out to one would work from a source checkout and fail
    everywhere else. Actions it cannot perform are reported with the exact
    command instead, and an action reporting a duty without naming it is refused
    at construction.
    """
    for spec in actions():
        if spec.performer is Performer.OPERATOR:
            assert spec.command, f"{spec.identifier} says an operator must act and does not say how"


def test_globin_performs_only_what_lives_inside_its_own_runtime_tree() -> None:
    """The boundary the wheel draws, asserted rather than remembered."""
    mine = {spec.identifier for spec in actions() if spec.performer is Performer.GLOBIN}
    assert mine == {"paths.create", "evidence.record"}


def test_winget_is_detected_and_never_invoked() -> None:
    """Detection is a read; installing through it is not this phase's.

    The presence is published so the phase that has a use for it inherits a
    measurement rather than a guess.
    """
    assert Tool.WINGET in set(Tool)
    permitted = {request.display() for request in probe_commands()}
    assert "winget --version" in permitted
    assert not [entry for entry in permitted if "install" in entry]


def test_the_only_commands_a_read_only_run_may_start_are_version_probes() -> None:
    """What makes `check` and `plan` read-only in production, not only under test."""
    for request in probe_commands():
        assert request.arguments == ("--version",)


def test_exactly_one_mutation_class_can_lose_work() -> None:
    assert {spec.mutation for spec in actions() if spec.destructive} == {MutationClass.REMOVE}


def test_setup_cannot_perform_the_destructive_class() -> None:
    """The one command that deletes is named, and it is not `setup`."""
    assert MutationClass.REMOVE not in setup_mutations()
    assert MutationClass.REMOVE in recreate_mutations()


def test_no_declared_action_needs_elevation_or_a_network() -> None:
    """The default path asks for neither."""
    assert not [spec for spec in actions() if spec.privilege is Privilege.ELEVATED]
    assert not [spec for spec in actions() if spec.network is NetworkRequirement.NETWORK]


# ---------------------------------------------------------------------------
# The command type cannot express a shell
# ---------------------------------------------------------------------------


def test_a_command_request_has_no_shell_field() -> None:
    """Not a field defaulting to False -- no field at all.

    A caller cannot ask for a shell because the type cannot describe one, which
    is a stronger guarantee than a default nobody is supposed to change.
    """
    from globin.domain.process import CommandRequest

    assert "shell" not in CommandRequest.__dataclass_fields__


def test_the_metacharacter_set_covers_what_a_shell_would_read() -> None:
    """A space is deliberately absent: a path with one in it is ordinary here."""
    for character in "&|;<>$`":
        assert character in SHELL_METACHARACTERS
    assert " " not in SHELL_METACHARACTERS


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_the_manifest_carries_no_timestamp() -> None:
    """Two runs over an unchanged host must compare byte for byte.

    That is what an idempotency test asserts, and a timestamp anywhere in the
    document would make it unassertable.
    """
    document = build(
        ProvisioningJournal(plan=ProvisioningPlan(policy=NetworkPolicy.OFFLINE)),
        HostCapability(),
    )
    rendered = json.dumps(document)
    assert "timestamp" not in rendered
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", rendered)


def test_the_manifest_declares_its_schema_and_version() -> None:
    document = build(
        ProvisioningJournal(plan=ProvisioningPlan(policy=NetworkPolicy.OFFLINE)),
        HostCapability(),
    )
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["phase"] == 32


def test_no_manifest_section_name_is_itself_redacted() -> None:
    """The defect Phase 032 fixed elsewhere, refused here before it can happen.

    `observed.secrets` published as the literal `[redacted]` for three phases
    because `redact` matches field names by substring. A new document is the
    cheapest possible moment to check that none of its sections has that problem.
    """
    document = build(
        ProvisioningJournal(plan=ProvisioningPlan(policy=NetworkPolicy.OFFLINE)),
        HostCapability(),
    )
    offenders = sorted(name for name in document if is_sensitive(name))
    assert not offenders, f"these manifest sections are redacted by their own name: {offenders}"


def test_the_manifest_name_is_stable() -> None:
    assert MANIFEST_NAME == "provisioning-manifest.json"


# ---------------------------------------------------------------------------
# The child environment
# ---------------------------------------------------------------------------


def test_a_child_inherits_only_what_is_named() -> None:
    """An allowlist, not a denylist.

    A variable reaches a child by being written down rather than by existing,
    which is the direction that fails safe when somebody adds a new one.
    """
    given = child_environment({"PATH": "x", "GLOBIN_API_KEY": "secret", "TEMP": "t"})
    assert set(given) == {"PATH", "TEMP"}


def test_no_allowlisted_variable_is_credential_shaped() -> None:
    """Guard the allowlist against a later addition that carries material."""
    offenders = [name for name in ENVIRONMENT_ALLOWLIST if is_sensitive(name)]
    assert not offenders, f"these inherited variables are credential-shaped: {offenders}"


def test_the_allowlist_check_would_catch_a_credential_shaped_addition() -> None:
    """Guard the guard, since the list above is clean today."""
    assert any(is_sensitive(f"GLOBIN_{fragment}") for fragment in SENSITIVE_KEY_FRAGMENTS)


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def test_the_provisioning_document_exists_and_states_the_cold_start_caveat(
    repo_root: Path,
) -> None:
    """`bootstrap setup` is installed into the environment it would create.

    It cannot be how that environment first appears, and a document that did not
    say so in its first screen would send an operator to a command that cannot
    help them.
    """
    document = (repo_root / "docs/engineering/PROVISIONING.md").read_text(encoding="utf-8")
    assert "scripts/bootstrap.ps1" in document
    for verb in cli.BOOTSTRAP_SUBCOMMANDS:
        assert f"bootstrap {verb}" in document, f"PROVISIONING.md does not cover `bootstrap {verb}`"


def test_the_provisioning_document_advises_nothing_unsafe(repo_root: Path) -> None:
    """No document here tells an operator to weaken their machine.

    Disabling execution policy, disabling antivirus and running everything as an
    administrator are the three remedies a provisioning document drifts towards,
    and all three are refusals this repository has already made elsewhere.
    """
    document = (repo_root / "docs/engineering/PROVISIONING.md").read_text(encoding="utf-8").lower()
    for phrase in ("disable antivirus", "turn off antivirus", "run as administrator"):
        assert phrase not in document, f"PROVISIONING.md advises {phrase!r}"
    assert "set-executionpolicy" not in document
