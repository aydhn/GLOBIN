"""The endpoint manifest's seal, and the command line that writes it.

Two things nothing else reaches. The manifest's five refusals are each unreachable
through the gate — it only ever reads a document it just wrote — so a reader that
accepted a tampered or mis-versioned manifest would ship unexercised, and a seal nobody
has seen break is not a seal. The command line is called **directly** rather than only
through a subprocess, because a subprocess proves the wiring works and measures none of
the parsing.
"""

import json
from pathlib import Path
from typing import Final

import pytest

from tools.quality.endpoint.cli import (
    EXIT_USAGE,
    USAGE,
    UsageError,
    main,
    parse,
)
from tools.quality.endpoint.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    MANIFEST_NAME,
    declaration_of,
    run_endpoint,
)
from tools.quality.endpoint.gate import _report as report
from tools.quality.endpoint.gate import _sha as sha
from tools.quality.endpoint.gate import _verdict_of as verdict_of
from tools.quality.endpoint.manifest import (
    DIGEST_KEY,
    DIGEST_PREFIX,
    PHASE,
    SCHEMA,
    SCHEMA_VERSION,
    EndpointManifestError,
    build,
    digest,
    load,
    render,
)
from tools.quality.endpoint.plan import EndpointContractError
from tools.quality.execution.plan import Verdict

RUN: Final[dict[str, object]] = {"repository": "aydhn/GLOBIN", "commit": "a" * 40}
"""A minimal ``run`` section, so every assembly below has something to seal."""

FINDINGS: Final[dict[str, object]] = {"routes": {"verdict": "passed", "problems": []}}
"""A minimal ``findings`` section."""

VERDICT: Final[dict[str, object]] = {"verdict": "passed", "reasons": []}
"""A minimal ``verdict`` section."""


def _document() -> dict[str, object]:
    """A sealed manifest."""
    return build(run=RUN, findings=FINDINGS, verdict=VERDICT)


# ---------------------------------------------------------------------------
# Rendering and sealing
# ---------------------------------------------------------------------------


def test_a_manifest_renders_canonically() -> None:
    """Sorted keys, no incidental whitespace, one trailing newline.

    Two runs producing the same values must produce the same bytes, or the digest
    identifies the formatting rather than the content.
    """
    rendered = render({"b": 2, "a": 1})
    assert rendered == '{"a":1,"b":2}\n'


def test_a_manifest_escapes_nothing_ambiguously() -> None:
    """ASCII-only output, so a console's code page cannot change the bytes."""
    assert render({"note": "café"}) == '{"note":"caf\\u00e9"}\n'


def test_the_digest_covers_everything_except_itself() -> None:
    """Otherwise sealing the document would change what the seal is over."""
    document = _document()
    without = {key: value for key, value in document.items() if key != DIGEST_KEY}
    assert document[DIGEST_KEY] == digest(without)
    assert digest(document) == digest(without)


def test_the_digest_announces_its_algorithm() -> None:
    """A bare hex string leaves a reader guessing which function produced it."""
    assert str(_document()[DIGEST_KEY]).startswith(DIGEST_PREFIX)


def test_a_manifest_declares_what_it_is_and_which_phase_built_it() -> None:
    """The three fields every gate's manifest carries."""
    document = _document()
    assert document["schema"] == SCHEMA
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["phase"] == PHASE


def test_changing_one_value_changes_the_digest() -> None:
    """A seal that did not would be decoration."""
    first = build(run=RUN, findings=FINDINGS, verdict=VERDICT)
    second = build(run={**RUN, "commit": "b" * 40}, findings=FINDINGS, verdict=VERDICT)
    assert first[DIGEST_KEY] != second[DIGEST_KEY]


# ---------------------------------------------------------------------------
# The five refusals, none of which the gate can reach
# ---------------------------------------------------------------------------


def test_a_well_formed_manifest_loads() -> None:
    """The positive case, without which every refusal below is untested."""
    assert load(render(_document())) == _document()


def test_text_that_is_not_json_is_refused() -> None:
    """A truncated write is the realistic way this happens."""
    with pytest.raises(EndpointManifestError, match="not valid JSON"):
        load("{ this is not json")


def test_a_json_value_that_is_not_an_object_is_refused() -> None:
    """A list is valid JSON and is not a manifest."""
    with pytest.raises(EndpointManifestError, match="expected an object"):
        load("[1, 2, 3]")


def test_another_gates_manifest_is_refused() -> None:
    """Every gate writes the same *shape*, so the schema is what tells them apart."""
    document = _document()
    document["schema"] = "globin.gpu.manifest"
    with pytest.raises(EndpointManifestError, match="declares schema"):
        load(json.dumps(document))


def test_an_unknown_schema_version_is_refused_rather_than_read() -> None:
    """A reader that guessed would report confidently about fields it misunderstood."""
    document = _document()
    document["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(EndpointManifestError, match="this reader implements"):
        load(json.dumps(document))


def test_a_document_that_does_not_match_its_own_digest_is_refused() -> None:
    """The seal breaking is the whole point of there being one."""
    document = _document()
    document["phase"] = 999
    with pytest.raises(EndpointManifestError, match="digests to"):
        load(json.dumps(document))


def test_a_manifest_with_no_digest_at_all_is_refused() -> None:
    """An unsealed document is not a weaker manifest; it is not one."""
    document = {key: value for key, value in _document().items() if key != DIGEST_KEY}
    with pytest.raises(EndpointManifestError, match="records None"):
        load(json.dumps(document))


# ---------------------------------------------------------------------------
# The command line, called directly
# ---------------------------------------------------------------------------


def test_no_argument_is_the_default_subcommand() -> None:
    """`check` is the default, and it changes nothing outside the run directory.

    The parser returns nothing, so what is asserted is that it does not *refuse*.
    """
    parse([])


def test_the_one_subcommand_is_accepted() -> None:
    """Spelled in full: no abbreviation, on every command line in this repository."""
    parse(["check"])


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["nonsense"], id="an-unknown-word"),
        pytest.param(["ch"], id="an-abbreviation"),
        pytest.param(["check", "check"], id="the-same-word-twice"),
        pytest.param(["check", "extra"], id="a-trailing-word"),
        pytest.param(["--json"], id="a-flag-this-gate-has-no-use-for"),
    ],
)
def test_anything_else_is_refused(argv: list[str]) -> None:
    """Refused rather than ignored: a word that silently does nothing is worse."""
    with pytest.raises(UsageError, match="unrecognised argument"):
        parse(argv)


def test_a_usage_error_prints_the_usage_and_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """So a caller who mistyped learns the surface rather than only that they failed."""
    assert main(["nonsense"]) == EXIT_USAGE
    printed = capsys.readouterr().out
    assert "unrecognised argument" in printed
    assert USAGE in printed


def test_the_usage_text_names_what_the_gate_does_not_do() -> None:
    """The claim an operator most needs: it binds nothing.

    A gate whose usage did not say so would be one somebody hesitated to run.
    """
    assert "Binds nothing" in USAGE
    assert "reaches nothing" in USAGE
    for code in ("0", "1", "2", "3"):
        assert f"  {code}  " in USAGE


def test_running_the_gate_through_the_command_line_writes_the_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole path, in-process, so the parsing is measured rather than only wired."""
    assert main([]) == EXIT_OK
    assert "endpoint: verdict passed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The gate's own edges
# ---------------------------------------------------------------------------


def test_an_unreadable_contract_raises_rather_than_returning_a_default(
    tmp_path: Path,
) -> None:
    """`declaration_of` is for a test asking about *this* repository's contract.

    Returning a default would let a caller assert against a contract that is not there.
    """
    with pytest.raises(EndpointContractError, match="could not be read"):
        declaration_of(tmp_path)


def test_a_package_module_that_cannot_be_read_is_skipped_rather_than_fatal(
    tmp_path: Path,
) -> None:
    """The wildcard sweep looks for a token's presence, and an unreadable file has none.

    Built as a directory named like a module, which is the cheapest thing that reads as
    a path and refuses to be read as a file.
    """
    tree = tmp_path / "tree"
    declaration = declaration_of()
    for relative in (
        "docs/engineering/endpoint-contract.toml",
        "src/globin/domain/diagnostics_http.py",
        "src/globin/domain/configuration.py",
        "src/globin/domain/metrics.py",
        declaration.binding_module,
    ):
        source = Path(relative)
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (tree / "src" / "globin" / "unreadable.py").mkdir(parents=True, exist_ok=True)
    reports = tmp_path / "reports"
    # The tests the contract names are absent from this tree, so the verdict is a
    # failure -- what is asserted is that the sweep did not raise on the way there.
    assert run_endpoint(root=tree, reports=reports) == EXIT_GATE_FAILED
    assert (reports / MANIFEST_NAME).is_file()


def test_a_gate_that_cannot_write_its_artefacts_is_unmeasured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unmeasured rather than failed, because nothing was established either way.

    ``QUALITY_GATES.md``'s rule: a gate is passed, failed, or not run, and "not run"
    never reports as "passed".
    """

    def refuse(**_kwargs: object) -> int:
        message = "the run directory is read-only"
        raise OSError(message)

    monkeypatch.setattr("tools.quality.endpoint.cli.run_endpoint", refuse)
    assert main([]) == EXIT_UNMEASURED
    assert "could not write its artefacts" in capsys.readouterr().out


def test_a_finding_that_is_not_a_mapping_is_unmeasured() -> None:
    """Reachable only if a check returned something unrecognised.

    Unmeasured rather than passed, so a shape nobody planned for cannot become a green
    verdict.
    """
    assert verdict_of("not a mapping") is Verdict.UNMEASURED
    assert verdict_of({"verdict": "invented"}) is Verdict.UNMEASURED
    assert verdict_of({"verdict": "passed"}) is Verdict.PASSED


def test_a_report_skips_an_entry_it_cannot_read(capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed finding must not stop the rest of the report being printed."""
    report(
        {"good": {"verdict": "passed", "problems": []}, "bad": "not a mapping"},
        Verdict.PASSED,
        [],
    )
    printed = capsys.readouterr().out
    assert "endpoint: good: passed" in printed
    assert "bad" not in printed


def test_a_report_prints_every_problem_and_every_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A verdict with no reasons beside it sends a reader back to the code."""
    report(
        {"routes": {"verdict": "failed", "problems": ["a route drifted"]}},
        Verdict.FAILED,
        ["ENDPOINT_ROUTES_DIVERGED"],
    )
    printed = capsys.readouterr().out
    assert "! a route drifted" in printed
    assert "ENDPOINT_ROUTES_DIVERGED" in printed


def test_the_commit_is_read_from_git_in_every_shape_it_takes(tmp_path: Path) -> None:
    """Read from ``.git`` directly, so a manifest can be produced without Git installed.

    Four shapes: a detached head holding a SHA, a file holding something that is not
    one, a symbolic ref pointing nowhere, and no repository at all. Each is recorded as
    unknown rather than guessed at, because a wrong commit on a manifest is worse than
    an absent one.
    """
    detached = tmp_path / "detached"
    (detached / ".git").mkdir(parents=True)
    (detached / ".git" / "HEAD").write_text("c" * 40, encoding="utf-8")
    assert sha(detached) == "c" * 40

    truncated = tmp_path / "truncated"
    (truncated / ".git").mkdir(parents=True)
    (truncated / ".git" / "HEAD").write_text("not-a-sha", encoding="utf-8")
    assert sha(truncated) == "unknown"

    dangling = tmp_path / "dangling"
    (dangling / ".git").mkdir(parents=True)
    (dangling / ".git" / "HEAD").write_text("ref: refs/heads/nowhere", encoding="utf-8")
    assert sha(dangling) == "unknown"

    assert sha(tmp_path / "absent") == "unknown"
