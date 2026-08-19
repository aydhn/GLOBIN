"""The ``rest`` command group: what it parses, what it prints, and what it exits.

**Nothing here reaches the venue.** The four read-only verbs are all that is
exercised; ``ping`` and ``server-time`` open a socket by definition and live in
``tests/integration/test_rest_probe_external.py``, behind the ``external`` marker
that every quality selection excludes.
"""

import io
import json
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.runtime.cli import USAGE, UsageError, main, parse


def _run(*argv: str, start: Path | None = None) -> tuple[int, str, str]:
    """Run one command line and capture both streams.

    Args:
        argv: The arguments after the program name.
        start: Where to begin the search for the project root.

    Returns:
        The exit code, standard output, and standard error.
    """
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, start=start)
    return code, out.getvalue(), err.getvalue()


class TestParsing:
    """Which words are accepted, and which options mean something where."""

    def test_the_default_verb_is_the_read_only_one(self) -> None:
        """A bare ``rest`` must not be the one that opens a socket."""
        assert parse(["rest", "--family", "spot", "--environment", "testnet"]).command == (
            "rest resolve"
        )

    @pytest.mark.parametrize(
        "verb", ["resolve", "endpoints", "ping", "server-time", "selftest", "evidence"]
    )
    def test_every_declared_verb_parses(self, verb: str) -> None:
        """Six verbs, and the parser knows all of them."""
        surface = verb in {"resolve", "ping", "server-time"}
        argv = ["rest", verb]
        if surface:
            argv += ["--family", "spot", "--environment", "testnet"]
        assert parse(argv).command == f"rest {verb}"

    def test_a_seventh_verb_is_a_usage_error(self) -> None:
        """A word that silently did nothing is how a caller believes it asked."""
        with pytest.raises(UsageError, match="unrecognised argument"):
            parse(["rest", "probe"])

    @pytest.mark.parametrize("verb", ["resolve", "ping", "server-time"])
    def test_a_surface_verb_requires_both_flags(self, verb: str) -> None:
        """No environment is defaulted, and that is deliberate.

        Defaulting it would mean one of production, testnet or demo was reached by
        typing nothing — and which one is exactly the decision an operator must make
        out loud.
        """
        with pytest.raises(UsageError, match="--environment"):
            parse(["rest", verb, "--family", "spot"])
        with pytest.raises(UsageError, match="--family"):
            parse(["rest", verb, "--environment", "testnet"])

    @pytest.mark.parametrize("verb", ["endpoints", "selftest", "evidence"])
    def test_a_non_surface_verb_refuses_the_flags(self, verb: str) -> None:
        """An argument that does nothing is worse than one that is rejected."""
        with pytest.raises(UsageError, match="names no single surface"):
            parse(["rest", verb, "--family", "spot", "--environment", "testnet"])

    def test_an_unknown_option_is_refused(self) -> None:
        """No abbreviation and no prefix matching: every word is compared for equality."""
        with pytest.raises(UsageError, match="unrecognised argument"):
            parse(["rest", "selftest", "--verbose"])

    def test_a_repeated_json_flag_is_refused(self) -> None:
        """The shape rule every option reader in this file already applies."""
        with pytest.raises(UsageError, match="twice"):
            parse(["rest", "selftest", "--json", "--json"])

    def test_a_flag_given_no_value_is_refused(self) -> None:
        """Otherwise ``--family --json`` silently swallows the second flag."""
        with pytest.raises(UsageError):
            parse(["rest", "resolve", "--family", "--environment", "testnet"])

    def test_the_usage_text_names_the_group_and_both_networked_verbs(self) -> None:
        """The usage block is where an operator learns which verbs reach the venue."""
        assert "rest resolve" in USAGE
        assert "rest ping" in USAGE
        assert "REACHES THE VENUE" in USAGE


class TestResolve:
    """The verb that answers *may this request go anywhere, and where*."""

    def test_a_supported_surface_resolves_and_exits_zero(self, repo_root: Path) -> None:
        """Spot has a documented REST surface in all three environments."""
        code, out, _ = _run(
            "rest", "resolve", "--family", "spot", "--environment", "testnet", start=repo_root
        )
        assert code == int(ExitCode.OK)
        assert "resolved" in out
        assert "testnet" in out

    def test_an_undocumented_product_refuses_and_exits_fourteen(self, repo_root: Path) -> None:
        """The acceptance criterion for fail-closed resolution.

        Nine of the twelve recorded families have no documented REST surface, so
        this is the ordinary case rather than a contrived one — and ``14`` is
        ``CONFIGURATION_INVALID``, which already means *the ask cannot be
        satisfied*. No twenty-sixth exit code was added.
        """
        code, out, _ = _run(
            "rest",
            "resolve",
            "--family",
            "usds_m_futures",
            "--environment",
            "production",
            start=repo_root,
        )
        assert code == int(ExitCode.CONFIGURATION_INVALID)
        assert "surface_undocumented" in out
        assert "unknown" in out

    def test_a_refusal_prints_no_endpoint(self, repo_root: Path) -> None:
        """A caller skimming the output must not find a plausible host in a refusal."""
        _, out, _ = _run(
            "rest",
            "resolve",
            "--family",
            "options",
            "--environment",
            "production",
            start=repo_root,
        )
        assert "binance" not in out.lower()

    def test_the_report_names_whether_real_capital_is_at_risk(self, repo_root: Path) -> None:
        """What an operator is actually checking before they run anything else."""
        _, production, _ = _run(
            "rest", "resolve", "--family", "spot", "--environment", "production", start=repo_root
        )
        _, testnet, _ = _run(
            "rest", "resolve", "--family", "spot", "--environment", "testnet", start=repo_root
        )
        assert "real capital" in production
        assert "YES" in production
        assert "YES" not in testnet

    def test_the_report_says_nothing_fails_over_to_the_alternates(self, repo_root: Path) -> None:
        """Six alternates are recorded for Spot production and none is a fallback."""
        _, out, _ = _run(
            "rest", "resolve", "--family", "spot", "--environment", "production", start=repo_root
        )
        assert "alternate" in out
        assert "nothing fails over" in out

    def test_json_output_carries_json_and_nothing_else(self, repo_root: Path) -> None:
        """The rule every command group in this file already follows."""
        _, out, _ = _run(
            "rest",
            "resolve",
            "--family",
            "spot",
            "--environment",
            "testnet",
            "--json",
            start=repo_root,
        )
        document = json.loads(out)
        assert document["outcome"] == "resolved"
        assert document["endpoint"]["environment"] == "testnet"


class TestEndpoints:
    """Every declared surface, refusals included."""

    def test_the_survey_counts_refusals_rather_than_hiding_them(self, repo_root: Path) -> None:
        """A survey listing only what resolves would report a fail-closed registry as empty.

        Twenty-one of the twenty-four declared pairs refuse today, and those are the
        evidence the gate works.
        """
        code, out, _ = _run("rest", "endpoints", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "resolved" in out
        assert "refused" in out

    def test_the_json_form_carries_the_freshness_report(self, repo_root: Path) -> None:
        """The cadence half of the phase, visible where an operator would look."""
        _, out, _ = _run("rest", "endpoints", "--json", start=repo_root)
        document = json.loads(out)
        assert document["counts"]["resolved"] >= 1
        assert "freshness" in document
        assert document["freshness"]["as_of"]


class TestSelfTest:
    """The package against its own declared contract."""

    def test_it_passes_and_exits_zero(self, repo_root: Path) -> None:
        """Eight checks, all of them comparing two things this repository controls."""
        code, out, _ = _run("rest", "selftest", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "0 failed" in out

    def test_every_check_is_reported_by_name(self, repo_root: Path) -> None:
        """A summary with no names is a summary nobody can act on."""
        _, out, _ = _run("rest", "selftest", "--json", start=repo_root)
        document = json.loads(out)
        assert document["passed"] is True
        names = {item["check"] for item in document["findings"]}
        assert "outcome.classification" in names
        assert "negotiation.sbe" in names


class TestEvidence:
    """The Phase 034 manifest."""

    def test_it_writes_a_manifest_and_exits_zero(self, repo_root: Path) -> None:
        """The document the phase is judged on."""
        code, out, _ = _run("rest", "evidence", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "rest-manifest.json" in out

    def test_two_runs_produce_the_same_digest(self, repo_root: Path) -> None:
        """Determinism, asserted rather than intended.

        Paths and timings are normalised out, so an unchanged tree digests
        identically — which is what makes the manifest worth comparing between runs
        at all.
        """
        manifest = repo_root / ".globin" / "rest" / "rest-manifest.json"
        _run("rest", "evidence", start=repo_root)
        first = json.loads(manifest.read_text(encoding="utf-8"))["digest"]
        _run("rest", "evidence", start=repo_root)
        second = json.loads(manifest.read_text(encoding="utf-8"))["digest"]
        assert first == second

    def test_the_manifest_records_that_no_probe_ran(self, repo_root: Path) -> None:
        """``unmeasured`` rather than a pass.

        The same answer ``drift`` gives for an unrecorded baseline: nothing was
        established, which is not the same as nothing being wrong.
        """
        _run("rest", "evidence", start=repo_root)
        manifest = repo_root / ".globin" / "rest" / "rest-manifest.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        assert document["run"]["probe_results"] == "unmeasured"
        assert document["run"]["reached_network"] is False

    def test_the_manifest_carries_no_secret_shaped_value(self, repo_root: Path) -> None:
        """Evidence is published, so it is the last place a credential may appear."""
        _run("rest", "evidence", start=repo_root)
        manifest = repo_root / ".globin" / "rest" / "rest-manifest.json"
        text = manifest.read_text(encoding="utf-8").lower()
        for token in ("apikey", "signature", "secret", "password", "token"):
            assert token not in text

    def test_the_manifest_verifies_its_own_digest(self, repo_root: Path) -> None:
        """A manifest edited after publication is refused rather than believed."""
        from globin.adapters.rest import TransportContractError, load

        _run("rest", "evidence", start=repo_root)
        manifest = repo_root / ".globin" / "rest" / "rest-manifest.json"
        text = manifest.read_text(encoding="utf-8")
        assert load(text)["phase"] == 34
        with pytest.raises(TransportContractError, match="edited"):
            load(text.replace('"phase":34', '"phase":99'))


class TestUnmeasured:
    """What happens where the committed documents are not."""

    def test_an_absent_registry_reports_unmeasured(self, tmp_path: Path) -> None:
        """Nothing was established, which is ``3`` and not a failure."""
        code, _, err = _run("rest", "selftest", start=tmp_path)
        assert code == int(ExitCode.UNMEASURED)
        assert "absent" in err
