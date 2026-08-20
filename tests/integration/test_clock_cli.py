"""The `globin clock` surface, end to end, against the committed documents.

Every command here runs against the real registry and the real transport contract,
so the counts asserted are the counts an operator sees. None of them opens a socket:
`calibrate` is the only verb that would, and it is exercised only in its refusing
form — the one that proves a domain with no recorded endpoint is turned away before
anything is sent.

The two assertions that matter most:

* **nothing this surface prints carries a secret**, which is structural here rather
  than redacted — the clock layer holds no credential, reads no store and produces
  no signature;
* **two runs produce byte-identical evidence**, so a manifest can be diffed across
  machines.
"""

import io
import json
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.runtime.cli import UsageError, main, parse


def _run(*argv: str, start: Path | None = None) -> tuple[int, str, str]:
    """Run one command and capture both streams.

    Args:
        *argv: The arguments after the program name.
        start: Where to begin the search for the project root.

    Returns:
        The exit code, standard output and standard error.
    """
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, start=start)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_the_default_subcommand_is_status() -> None:
    """The verb that opens nothing is what a bare `globin clock` does."""
    assert parse(["clock"]).command == "clock status"


@pytest.mark.parametrize("subcommand", ["domains", "status", "calibrate", "selftest", "evidence"])
def test_every_declared_subcommand_parses(subcommand: str) -> None:
    """Five verbs and no sixth."""
    argv = ["clock", subcommand]
    if subcommand == "calibrate":
        argv += ["--family", "spot", "--environment", "testnet"]
    assert parse(argv).command == f"clock {subcommand}"


def test_an_unrecognised_subcommand_is_refused() -> None:
    """There is no `set`, no `adjust` and no `correct`."""
    for word in ("set", "adjust", "correct", "sync"):
        with pytest.raises(UsageError, match="unrecognised argument"):
            parse(["clock", word])


def test_calibrate_refuses_to_name_no_surface() -> None:
    """A command that reaches a network says which network."""
    with pytest.raises(UsageError, match="needs --family"):
        parse(["clock", "calibrate"])
    with pytest.raises(UsageError, match="needs --environment"):
        parse(["clock", "calibrate", "--family", "spot"])


def test_status_may_name_no_surface() -> None:
    """Reading what GLOBIN already believes costs nothing, so it needs no argument."""
    invocation = parse(["clock", "status"])
    assert invocation.family == ""
    assert invocation.environment == ""


def test_selftest_refuses_arguments_that_mean_nothing_to_it() -> None:
    """A flag that silently does nothing is how a caller believes they asked."""
    with pytest.raises(UsageError, match="names no single surface"):
        parse(["clock", "selftest", "--family", "spot"])


# ---------------------------------------------------------------------------
# The verbs that open nothing
# ---------------------------------------------------------------------------


def test_domains_lists_every_declared_pair_and_marks_the_reachable_ones(
    repo_root: Path,
) -> None:
    """Refusals are listed, not filtered — they are the evidence the gate works."""
    code, out, _ = _run("clock", "domains", "--json", start=repo_root)
    document = json.loads(out)
    assert code == int(ExitCode.OK)
    assert document["declared"] == len(document["domains"])
    assert document["available"] == 3
    assert document["unavailable"] == document["declared"] - 3
    reachable = {item["domain"]["label"] for item in document["domains"] if item["available"]}
    assert reachable == {
        "spot/production/rest",
        "spot/demo/rest",
        "spot/testnet/rest",
    }


def test_an_unreachable_domain_names_the_registry_status_rather_than_a_path(
    repo_root: Path,
) -> None:
    """A path is never guessed, so the refusal cannot mention one."""
    _, out, _ = _run("clock", "domains", "--json", start=repo_root)
    document = json.loads(out)
    futures = [item for item in document["domains"] if item["domain"]["family"] == "usds_m_futures"]
    assert futures
    for item in futures:
        assert not item["available"]
        assert "unknown" in item["detail"]
        assert "/fapi" not in json.dumps(item)


def test_status_reports_uninitialized_and_exits_three_on_a_fresh_process(
    repo_root: Path,
) -> None:
    """Nothing established is `3`, the same answer `drift` gives an unrecorded baseline."""
    code, out, _ = _run("clock", "status", "--json", start=repo_root)
    document = json.loads(out)
    assert code == int(ExitCode.UNMEASURED)
    assert document["synchronized"] == 0
    assert document["counts"]["uninitialized"] == len(document["statuses"])


def test_status_carries_the_policy_in_force(repo_root: Path) -> None:
    """An operator can read the thresholds without touching a venue."""
    _, out, _ = _run("clock", "status", "--json", start=repo_root)
    discipline = json.loads(out)["discipline"]
    assert discipline["freshness_ttl_millis"] == 300_000
    assert discipline["max_uncertainty_millis"] == 250
    assert discipline["future_tolerance_millis"] == 1_000


def test_status_may_be_narrowed_to_one_family(repo_root: Path) -> None:
    """The same report, filtered, rather than a different one."""
    _, out, _ = _run("clock", "status", "--family", "spot", "--json", start=repo_root)
    document = json.loads(out)
    assert len(document["statuses"]) == 3
    for item in document["statuses"]:
        assert item["domain"]["family"] == "spot"


def test_the_selftest_passes_and_exits_zero(repo_root: Path) -> None:
    """Eight checks, one of them against the venue's own published rule."""
    code, out, _ = _run("clock", "selftest", "--json", start=repo_root)
    document = json.loads(out)
    assert code == int(ExitCode.OK)
    assert document["passed"] is True
    assert document["checked"] == 8
    assert {item["check"] for item in document["findings"]} == {
        "clock.estimator",
        "clock.units",
        "clock.state_machine",
        "clock.admission",
        "clock.recv_window",
        "clock.recovery",
        "clock.venue_rule",
        "clock.buckets",
    }


# ---------------------------------------------------------------------------
# The verb that would open something
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    ["usds_m_futures", "coin_m_futures", "options", "cross_margin"],
    ids=["usds-m", "coin-m", "options", "cross-margin"],
)
def test_calibrating_an_undocumented_family_refuses_before_anything_is_sent(
    repo_root: Path, family: str
) -> None:
    """Fail-closed, and *before* a socket — the offline guard would catch it otherwise.

    The autouse network guard in `conftest.py` refuses an outbound connection, so a
    version of this that reached for one would fail loudly rather than quietly. That
    the test passes is itself part of the assertion.
    """
    code, out, _ = _run(
        "clock",
        "calibrate",
        "--family",
        family,
        "--environment",
        "production",
        "--json",
        start=repo_root,
    )
    document = json.loads(out)
    assert code == int(ExitCode.CONFIGURATION_INVALID)
    assert document["calibrated"] is False
    assert "unknown" in document["detail"]
    assert document["domain"]["family"] == family


def test_a_refused_calibration_says_plainly_that_nothing_was_sent(
    repo_root: Path,
) -> None:
    """The human rendering, because an operator reads that one."""
    _, out, _ = _run(
        "clock",
        "calibrate",
        "--family",
        "options",
        "--environment",
        "testnet",
        start=repo_root,
    )
    assert "REFUSED" in out
    assert "Nothing was sent." in out


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_the_evidence_manifest_is_written_and_records_that_nothing_was_measured(
    repo_root: Path, tmp_path: Path
) -> None:
    """A machine that calibrated nothing records `unmeasured`, never a zero."""
    code, out, _ = _run("clock", "evidence", start=repo_root)
    assert code == int(ExitCode.OK)
    assert "clock-manifest.json" in out
    target = repo_root / ".globin" / "clock" / "clock-manifest.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["phase"] == 36
    assert document["calibration_results"] == "unmeasured"
    assert document["reached_network"] is False
    assert document["self_test"]["passed"] is True
    del tmp_path


def test_two_evidence_runs_produce_identical_bytes(repo_root: Path) -> None:
    """Deterministic, so a manifest can be diffed across machines and across runs."""
    target = repo_root / ".globin" / "clock" / "clock-manifest.json"
    _run("clock", "evidence", start=repo_root)
    first = target.read_bytes()
    _run("clock", "evidence", start=repo_root)
    assert target.read_bytes() == first


def test_the_evidence_carries_the_declared_contract_rather_than_a_copy(
    repo_root: Path,
) -> None:
    """What was in force, read from the committed document at the time of writing."""
    _run("clock", "evidence", start=repo_root)
    target = repo_root / ".globin" / "clock" / "clock-manifest.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["contract"]["estimator"] == "lowest_round_trip"
    assert document["contract"]["phase"] == 36
    assert document["recovery"]["code"] == -1021
    assert document["recovery"]["max_retries"] == 1


# ---------------------------------------------------------------------------
# Nothing leaks
# ---------------------------------------------------------------------------


CREDENTIAL_SHAPED = (
    "X-MBX-APIKEY",
    "signature",
    "apiKey",
    "secret",
    "PRIVATE KEY",
    "BEGIN ",
)


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(("clock", "domains", "--json"), id="domains"),
        pytest.param(("clock", "status", "--json"), id="status"),
        pytest.param(("clock", "selftest", "--json"), id="selftest"),
    ],
)
def test_no_command_output_carries_anything_credential_shaped(
    repo_root: Path, argv: tuple[str, ...]
) -> None:
    """Structural rather than redacted: there is no credential in this layer to leak."""
    _, out, err = _run(*argv, start=repo_root)
    rendered = out + err
    for token in CREDENTIAL_SHAPED:
        assert token not in rendered, token


def test_the_evidence_manifest_carries_nothing_credential_shaped(
    repo_root: Path,
) -> None:
    """The manifest travels, so it is checked separately from the console output."""
    _run("clock", "evidence", start=repo_root)
    target = repo_root / ".globin" / "clock" / "clock-manifest.json"
    rendered = target.read_text(encoding="utf-8")
    for token in CREDENTIAL_SHAPED:
        assert token not in rendered, token


def test_no_command_publishes_an_unbounded_timing_value(repo_root: Path) -> None:
    """Buckets are published; raw nanoseconds and timestamps are not.

    A dashboard built on this surface has a cardinality that can be counted from
    `clock-contract.toml`, which is what `TELEMETRY_POLICY.md` requires.
    """
    _, out, _ = _run("clock", "status", "--json", start=repo_root)
    rendered = json.dumps(json.loads(out))
    assert "round_trip_micros" not in rendered
    assert "epoch_micros" not in rendered
    assert "timestamp" not in rendered


# ---------------------------------------------------------------------------
# The surface is in the usage text
# ---------------------------------------------------------------------------


def test_the_usage_text_names_every_clock_verb(repo_root: Path) -> None:
    """A command absent from `--help` is one nobody finds."""
    _, out, _ = _run("--help", start=repo_root)
    for verb in ("clock domains", "clock status", "clock calibrate", "clock selftest"):
        assert verb in out, verb


def test_the_usage_text_says_which_verb_reaches_the_venue(repo_root: Path) -> None:
    """The verb is the opt-in, so the text has to say which one it is."""
    _, out, _ = _run("--help", start=repo_root)
    calibrate = out[out.index("clock calibrate") :]
    assert "REACHES THE VENUE" in calibrate[:400]
