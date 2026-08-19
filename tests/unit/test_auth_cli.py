"""The ``auth`` command group: what it parses, what it prints, and what it exits.

**Nothing here reaches the venue, and nothing reads a credential.** Four of the
five verbs are pure; the fifth, ``probe``, is exercised only in the state every
host is in today — no credential configured — where it reports a deterministic
skip and sends nothing.

The assertions worth reading twice are the ones about what is *absent* from the
output. A command group that names a credential is one whose output ends up in a
support bundle, an issue report or a screenshot, so every printed document is
checked for what it must not carry rather than only for what it must.
"""

import io
import json
import re
from pathlib import Path

import pytest

from globin.adapters.signing import known_armour, pkcs8_header
from globin.domain.bootstrap import ExitCode
from globin.runtime.cli import AUTH_SUBCOMMANDS, USAGE, UsageError, main, parse


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

    def test_the_default_verb_reaches_nothing(self) -> None:
        """A bare ``auth`` must not be the one that opens a socket."""
        parsed = parse(["auth", "--family", "spot", "--environment", "testnet"])
        assert parsed.command == "auth capabilities"

    @pytest.mark.parametrize("verb", AUTH_SUBCOMMANDS)
    def test_every_declared_verb_parses(self, verb: str) -> None:
        """The register and the parser agree, in the direction that matters most."""
        words = ["auth", verb]
        if verb in {"capabilities", "probe"}:
            words += ["--family", "spot", "--environment", "testnet"]
        assert parse(words).command == f"auth {verb}"

    def test_a_sixth_verb_is_a_usage_error(self) -> None:
        """The claim that there is no sixth verb, checked rather than written."""
        with pytest.raises(UsageError, match="unrecognised"):
            parse(["auth", "sign"])

    @pytest.mark.parametrize("verb", ["capabilities", "probe"])
    def test_a_surface_verb_requires_both_flags(self, verb: str) -> None:
        """There is no default environment, and with more force than for ``rest``.

        Defaulting it would mean the live exchange could be reached by typing
        nothing.
        """
        with pytest.raises(UsageError, match="--family"):
            parse(["auth", verb, "--environment", "testnet"])
        with pytest.raises(UsageError, match="--environment"):
            parse(["auth", verb, "--family", "spot"])

    @pytest.mark.parametrize("verb", ["classes", "selftest", "evidence"])
    def test_a_non_surface_verb_refuses_the_flags(self, verb: str) -> None:
        """An option that silently did nothing is how a caller believes they asked."""
        with pytest.raises(UsageError, match="mean nothing here"):
            parse(["auth", verb, "--family", "spot", "--environment", "testnet"])

    def test_an_unknown_option_is_refused(self) -> None:
        """Refused rather than ignored."""
        with pytest.raises(UsageError):
            parse(["auth", "selftest", "--verbose"])

    def test_the_usage_text_names_the_group(self) -> None:
        """A group nobody can discover is one nobody uses."""
        assert "auth" in USAGE


class TestClasses:
    """The verb that answers *what does each environment promise*."""

    def test_it_reports_every_class_and_exits_zero(self, repo_root: Path) -> None:
        """The committed document and the package agree, so this is the healthy case."""
        code, out, _ = _run("auth", "classes", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "internal_simulation" in out
        assert "live_capital" in out
        assert "agree on every guarantee" in out

    def test_the_json_form_carries_the_classification(self, repo_root: Path) -> None:
        """Deterministic schema, matching every other command group here."""
        code, out, _ = _run("auth", "classes", "--json", start=repo_root)
        assert code == int(ExitCode.OK)
        document = json.loads(out)
        assert document["schema"] == "globin.rest.auth"
        assert document["disagreements"] == []
        names = {row["name"] for row in document["classification"]["environments"]}
        assert {"production", "testnet", "demo", "paper", "live"} <= names

    def test_the_simulated_class_is_reported_as_accepting_no_credential(
        self, repo_root: Path
    ) -> None:
        """Gate 1, visible to an operator rather than only to a gate."""
        _, out, _ = _run("auth", "classes", "--json", start=repo_root)
        classes = {row["class"]: row for row in json.loads(out)["classes"]}
        assert classes["internal_simulation"]["accepts_credential"] is False
        assert classes["internal_simulation"]["reaches_venue"] is False


class TestCapabilities:
    """The verb that answers *what could sign a request here, and what could not*."""

    def test_a_supported_surface_reports_its_documented_key_types(self, repo_root: Path) -> None:
        """Read from the registry rather than from a table in the auth layer."""
        code, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "spot",
            "--environment",
            "testnet",
            start=repo_root,
        )
        assert code == int(ExitCode.OK)
        assert "ed25519, hmac, rsa" in out
        assert "venue_testnet" in out

    def test_no_credential_configured_is_reported_as_what_to_do(self, repo_root: Path) -> None:
        """The state every host is in today, and the message names the remedy."""
        _, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "spot",
            "--environment",
            "testnet",
            start=repo_root,
        )
        assert "missing_credential" in out
        assert "globin secrets set" in out
        assert "not configured" in out

    def test_a_simulated_environment_refuses_at_gate_one(self, repo_root: Path) -> None:
        """And the message says no credential was read, not that one was declined."""
        _, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "spot",
            "--environment",
            "paper",
            start=repo_root,
        )
        assert "environment_forbids_credential" in out
        assert "no credential is read" in out

    def test_an_unclassified_environment_refuses_rather_than_assuming(
        self, repo_root: Path
    ) -> None:
        """ADR-0006's rule, reachable from the command line."""
        _, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "spot",
            "--environment",
            "staging",
            start=repo_root,
        )
        assert "environment_unclassified" in out
        assert "refused rather than assumed safe" in out

    def test_an_undocumented_product_refuses_before_authentication(self, repo_root: Path) -> None:
        """Twelve of thirteen families, and the refusal names the registry's own word."""
        _, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "usds_m_futures",
            "--environment",
            "testnet",
            start=repo_root,
        )
        assert "endpoint_unresolved" in out
        assert "unknown" in out

    def test_the_report_names_no_credential_and_no_fingerprint(self, repo_root: Path) -> None:
        """This command reads nothing from the store, so it has nothing to publish."""
        _, out, _ = _run(
            "auth",
            "capabilities",
            "--family",
            "spot",
            "--environment",
            "production",
            "--json",
            start=repo_root,
        )
        document = json.loads(out)
        assert document["configured_key_type"] is None
        assert "fingerprint" not in document
        assert "secret" not in out.lower() or "venue_secret" not in out


class TestSelfTest:
    """The offline recomputation, including the check that is not a comparison."""

    def test_every_check_passes(self, repo_root: Path) -> None:
        """Eight checks, one of them against the venue's own published answers."""
        code, out, _ = _run("auth", "selftest", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "FAIL" not in out
        assert "both published HMAC vectors reproduce exactly" in out
        assert "0 of 8 checks failed" in out

    def test_the_json_form_lists_every_finding(self, repo_root: Path) -> None:
        """So a manifest can carry the verdicts rather than the prose."""
        code, out, _ = _run("auth", "selftest", "--json", start=repo_root)
        assert code == int(ExitCode.OK)
        document = json.loads(out)
        assert document["passed"] is True
        assert document["checked"] == 8
        assert {item["check"] for item in document["findings"]} >= {
            "auth.known_answer",
            "auth.wire_equality",
            "auth.redaction",
        }


class TestProbe:
    """The one verb that could reach the venue, in the state where it does not."""

    def test_it_skips_deterministically_and_exits_zero(self, repo_root: Path) -> None:
        """A skip is an answer rather than a failure.

        The brief's own rule is that an unconfigured credential must not fail a
        suite, and *nothing was configured* is a true report.
        """
        code, out, _ = _run(
            "auth", "probe", "--family", "spot", "--environment", "testnet", start=repo_root
        )
        assert code == int(ExitCode.OK)
        assert "SKIP" in out
        assert "nothing was sent" in out

    def test_it_names_every_reason_it_did_not_send(self, repo_root: Path) -> None:
        """Two switches and a missing credential, each reported rather than the first only."""
        _, out, _ = _run(
            "auth", "probe", "--family", "spot", "--environment", "testnet", start=repo_root
        )
        assert "auth.probe_enabled is off" in out
        assert "missing_credential" in out

    def test_the_production_switch_is_named_separately(self, repo_root: Path) -> None:
        """An operator who enabled a testnet probe has not consented to the live exchange."""
        _, out, _ = _run(
            "auth", "probe", "--family", "spot", "--environment", "production", start=repo_root
        )
        assert "allow_production_probe" in out

    def test_the_json_form_records_that_nothing_was_sent(self, repo_root: Path) -> None:
        """The field a manifest reads, rather than prose it would have to parse."""
        code, out, _ = _run(
            "auth",
            "probe",
            "--family",
            "spot",
            "--environment",
            "testnet",
            "--json",
            start=repo_root,
        )
        assert code == int(ExitCode.OK)
        document = json.loads(out)
        assert document["sent"] is False
        assert document["verdict"] == "SKIP"
        assert document["operation"] == "spot.account"


class TestEvidence:
    """The manifest, and what it must not carry."""

    def test_it_writes_a_manifest_and_exits_zero(self, repo_root: Path) -> None:
        """Written into the repository's own evidence tree, like every other manifest."""
        code, out, _ = _run("auth", "evidence", start=repo_root)
        assert code == int(ExitCode.OK)
        assert "auth-manifest.json" in out
        written = repo_root / ".globin" / "auth" / "auth-manifest.json"
        assert written.is_file()
        document = json.loads(written.read_text(encoding="utf-8"))
        assert document["phase"] == 35
        assert document["self_test"]["passed"] is True

    def test_the_manifest_carries_no_credential_and_no_signature(self, repo_root: Path) -> None:
        """Nothing to redact, which is the property the record is built for.

        Checked for signature- and key-**shaped values** rather than for the word
        "signature", which appears legitimately in a check description — the first
        draft asserted the word and failed on the self-test finding that says
        *"str, repr, format and as_record all withhold the signature"*. A scan that
        cannot tell a value from prose about values is one somebody weakens.
        """
        _run("auth", "evidence", start=repo_root)
        text = (repo_root / ".globin" / "auth" / "auth-manifest.json").read_text(encoding="utf-8")
        assert not re.search(r"[0-9a-f]{64}", text), "a hex signature or digest"
        assert not re.search(r"[A-Za-z0-9+/]{80,}={0,2}", text), "a base64 signature"
        # Derived from the module rather than spelled here, so this list cannot
        # fall behind the armour the loader actually recognises — and so a second
        # copy of a PEM header does not enter the tree to say so.
        forbidden = (pkcs8_header(), *(armour for armour, _ in known_armour()), "secretKey")
        for armour in forbidden:
            assert armour not in text, armour

    def test_the_manifest_is_byte_stable_between_runs(self, repo_root: Path) -> None:
        """No wall clock reaches it, so two runs of an unchanged tree agree."""
        written = repo_root / ".globin" / "auth" / "auth-manifest.json"
        _run("auth", "evidence", start=repo_root)
        first = written.read_bytes()
        _run("auth", "evidence", start=repo_root)
        assert written.read_bytes() == first


class TestAbsentDocuments:
    """What happens where the committed documents are not."""

    def test_an_absent_registry_is_unmeasured_rather_than_a_failure(self, tmp_path: Path) -> None:
        """Established nothing, which is ``3`` — the same answer ``rest`` gives."""
        code, _out, err = _run("auth", "classes", start=tmp_path)
        assert code == int(ExitCode.UNMEASURED)
        assert "is absent" in err
        assert "nothing was established" in err
