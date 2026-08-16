"""The watchdog's promises to the rest of the repository, asserted rather than written.

Three of these exist because a document claims something, and a claim nobody
compares against the code is a claim that will eventually be false. The fourth —
the bundle exclusion — is the whole enforcement behind ADR-0066, and editing it
should read as editing that decision.
"""

from pathlib import Path

from globin.domain.bootstrap import ExitCode
from globin.domain.configuration import WATCHDOG_SECTION, WatchdogConfig, default_config
from globin.domain.watchdog import (
    REASONS,
    WATCHDOG_EVENTS,
    WATCHDOG_SCHEMA,
    WatchdogPolicy,
    WatchdogState,
    transitions,
)
from globin.runtime.composition import WATCHDOG_FILE, build_runtime_state, bundle_candidates
from tests.support import markdown_prose

DOCUMENT = Path("docs/engineering/RUNTIME_WATCHDOG.md")
"""The subject owner, per the table in ``DOCUMENTATION_STANDARD.md``."""


def test_a_stall_incident_is_not_a_support_bundle_candidate(
    tmp_path: Path, repo_root: Path
) -> None:
    """The whole enforcement behind ADR-0066, and it is one line.

    Phase 024 refused stacks in the health surface because that surface *travels*:
    into a bundle, and from there to whoever an operator sends it to. Phase 025
    answers that by destination rather than by redaction — the incident is a local
    post-mortem. If a later phase adds ``state/*.json`` to the allowlist as a
    convenience, stall evidence starts travelling and this is what says so.
    """
    assert repo_root.exists()
    state = build_runtime_state(environment={"LOCALAPPDATA": str(tmp_path)})
    members = {candidate.member for candidate in bundle_candidates(state, b"{}")}
    assert not any(WATCHDOG_FILE in member for member in members)


def test_the_document_and_the_code_agree_about_how_many_settings_there_are() -> None:
    """A count in prose is bound to its source, as ``MEMORY.md`` requires."""
    prose = markdown_prose(DOCUMENT.read_text(encoding="utf-8"))
    assert len(WatchdogConfig().__dataclass_fields__) == 6
    assert "Six settings" in prose


def test_the_document_names_the_exit_code_the_code_actually_uses() -> None:
    """Read from the raw text rather than the prose.

    ``markdown_prose`` strips inline code, and the identifier is spelled in
    backticks in the document — which is the right way to spell it and the wrong
    thing to search the stripped text for.
    """
    text = DOCUMENT.read_text(encoding="utf-8")
    assert f"**{int(ExitCode.WATCHDOG_STALLED)}**" in markdown_prose(text)
    assert ExitCode.WATCHDOG_STALLED.name in text


def test_every_state_the_document_tabulates_is_a_real_one() -> None:
    """The state table is the operator's map; a stale row is a wrong map."""
    text = DOCUMENT.read_text(encoding="utf-8")
    for state in WatchdogState:
        assert f"`{state.value}`" in text, state


def test_the_schema_name_is_spellable_by_the_serialization_policy() -> None:
    """Lower case and dots only — an underscore would be refused at write time."""
    permitted = set("abcdefghijklmnopqrstuvwxyz0123456789.")
    assert set(WATCHDOG_SCHEMA) <= permitted


def test_the_watchdog_section_is_registered_under_its_own_name() -> None:
    settings = default_config().watchdog
    assert isinstance(settings, WatchdogConfig)
    assert WATCHDOG_SECTION == "watchdog"


def test_the_declared_defaults_build_a_policy_that_validates() -> None:
    """A default set that could not be honoured would make the model unusable."""
    assert isinstance(default_config().watchdog.policy(), WatchdogPolicy)


def test_no_transition_leaves_the_escalating_state_except_to_stop() -> None:
    """Escalation is terminal; the only way out is standing down."""
    outbound = {target for source, target in transitions() if source is WatchdogState.ESCALATING}
    assert outbound == {WatchdogState.DISABLED}


def test_the_reason_and_event_vocabularies_are_disjoint_from_each_other() -> None:
    """Two closed sets that shared a member would make a log field ambiguous."""
    assert not set(REASONS) & set(WATCHDOG_EVENTS)
