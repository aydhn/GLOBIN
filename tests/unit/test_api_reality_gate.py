"""The second reader, driven offline.

Every network branch is exercised through an injected fetcher. That is not a
convenience: the offline guarantee is enforced by refusing sockets in *this*
process, so a real fetch here would be caught by the guard rather than by the
assertion, and the test would be proving that the guard works instead of that the
gate does.
"""

from pathlib import Path

import pytest

from tools.quality.venue.cli import USAGE, UsageError, main, parse
from tools.quality.venue.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    Fetcher,
    describe,
    fetch,
    run_api_reality,
)
from tools.quality.venue.manifest import ManifestError, build, digest, load, render
from tools.quality.venue.plan import (
    REASON_CONDITION_MISSING,
    REASON_DUPLICATE_IDENTITY,
    REASON_ENDPOINT_ENVIRONMENT,
    REASON_FIX_UNPROTECTED,
    REASON_OBSERVED_CLAIMED,
    REASON_SOURCE_CHANGED,
    REASON_SOURCE_OFF_ALLOWLIST,
    REASON_SOURCE_UNDECLARED,
    REASON_SOURCE_UNREACHABLE,
    REASON_STRUCTURED_UNPARSEABLE,
    REASON_UNPARSEABLE_RECOVERED,
    REASONS,
    RegistryError,
    findings_for,
    host_permitted,
    parse_declaration,
)

MINIMAL = """
schema = 1

[[source]]
id = "doc"
title = "A document"
location = "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/a.md"
authority = "primary"
regime = "digest"
accessed = "2026-08-19"

[[environment]]
family = "spot"
environment = "production"
semantics = "The live exchange."
carries_real_capital = true
status = "supported"
evidence = "documented"
source = "doc"
"""


def answering(body: bytes) -> Fetcher:
    """A fetcher that always returns one body.

    Args:
        body: What every fetch returns.

    Returns:
        The double. Named rather than a lambda so that the unused arguments are
        visibly part of the contract being satisfied.
    """

    def fetcher(url: str, timeout: float = 0.0) -> bytes:  # noqa: ARG001
        return body

    return fetcher


def reasons(text: str) -> set[str]:
    """Every reason the gate reports for one declaration.

    Args:
        text: The registry.

    Returns:
        The reasons.
    """
    return {item.reason for item in findings_for(parse_declaration(text))}


class TestAllowlist:
    """A location is judged on its parsed hostname, never on its spelling."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/a.md",
            "https://github.com/binance/binance-spot-api-docs",
            "https://developers.binance.com/docs",
        ],
    )
    def test_an_official_location_is_permitted(self, url: str) -> None:
        """The four hosts the registry may cite."""
        assert host_permitted(url)

    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("http://raw.githubusercontent.com/binance/a", id="not-https"),
            pytest.param("https://evil.test/raw.githubusercontent.com/binance/a", id="in-path"),
            pytest.param("https://raw.githubusercontent.com.evil.test/binance/a", id="suffixed"),
            pytest.param("https://raw.githubusercontent.com/someone/fork/a.md", id="wrong-org"),
            pytest.param("https://github.com/someone/fork", id="wrong-org-on-github"),
            pytest.param("file:///etc/passwd", id="local-file"),
            pytest.param("https://", id="no-host"),
        ],
    )
    def test_anything_else_is_refused(self, url: str) -> None:
        """A host that merely contains an approved name is not an approved host.

        The three most interesting cases are the last three of the first four: a URL
        whose *path* names the allowlisted host, one whose host merely ends with it,
        and one on the right host in somebody else's repository.
        """
        assert not host_permitted(url)

    def test_the_fetcher_refuses_before_it_opens_anything(self) -> None:
        """An off-allowlist URL never reaches the network layer at all.

        Asserted here rather than trusted, because this is the one place where a
        mistake would open a socket to somewhere nobody approved.
        """
        with pytest.raises(RegistryError, match="not an allowlisted"):
            fetch("https://evil.test/a.md")


class TestDeclaration:
    """The gate parses the registry without the package's reader."""

    def test_a_minimal_registry_has_nothing_wrong_with_it(self) -> None:
        """The base case, so a later assertion of findings means something."""
        assert not findings_for(parse_declaration(MINIMAL))

    def test_unparseable_toml_is_refused(self) -> None:
        """A registry that does not parse is not a registry with findings."""
        with pytest.raises(RegistryError, match="not valid TOML"):
            parse_declaration("[[[")

    def test_an_unrecognised_schema_is_refused_rather_than_read(self) -> None:
        """Reading a document announcing a shape this gate does not know is guessing."""
        with pytest.raises(RegistryError, match="announces schema"):
            parse_declaration("schema = 99")


class TestFindings:
    """Each rule, made to fail on purpose."""

    def test_an_undeclared_source_is_reported(self) -> None:
        """Provenance pointing nowhere reads as provenance."""
        assert REASON_SOURCE_UNDECLARED in reasons(
            MINIMAL.replace('source = "doc"', 'source = "x"')
        )

    def test_an_off_allowlist_source_is_reported(self) -> None:
        """The registry may not cite somebody's blog."""
        broken = MINIMAL.replace(
            "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/a.md",
            "https://example.invalid/a.md",
        )
        assert REASON_SOURCE_OFF_ALLOWLIST in reasons(broken)

    def test_a_claim_of_observation_is_reported(self) -> None:
        """GLOBIN has never contacted the venue, so no row may say it has.

        The member exists for a later phase that will have a transport. Until then
        writing it is a lie the gate refuses.
        """
        assert REASON_OBSERVED_CLAIMED in reasons(MINIMAL.replace('"documented"', '"observed"'))

    def test_a_restricted_row_without_a_condition_is_reported(self) -> None:
        """A restricted row that names no condition is an unknown wearing a better word."""
        assert REASON_CONDITION_MISSING in reasons(MINIMAL.replace('"supported"', '"restricted"'))

    def test_a_repeated_identity_is_reported(self) -> None:
        """Two environments with one identity make a lookup ambiguous."""
        doubled = MINIMAL + MINIMAL[MINIMAL.index("[[environment]]") :]
        assert REASON_DUPLICATE_IDENTITY in reasons(doubled)

    def test_a_live_host_filed_under_a_marked_environment_is_reported(self) -> None:
        """The failure that routes believed-paper trading at real capital."""
        mixed = (
            MINIMAL
            + """
[[environment]]
family = "spot"
environment = "testnet"
semantics = "Paper."
carries_real_capital = false
host_marker = "testnet"
status = "supported"
evidence = "documented"
source = "doc"

[[endpoint]]
family = "spot"
environment = "testnet"
protocol = "rest"
url = "https://api.binance.com/api"
transport = "https"
request_encoding = "json"
response_encoding = "json"
auth = "signed"
status = "supported"
evidence = "documented"
source = "doc"
"""
        )
        assert REASON_ENDPOINT_ENVIRONMENT in reasons(mixed)

    def test_a_fix_endpoint_without_sni_is_reported(self) -> None:
        """A client omitting SNI may receive an unexpected certificate."""
        unprotected = (
            MINIMAL
            + """
[[endpoint]]
family = "spot"
environment = "production"
protocol = "fix_order_entry"
url = "tcp+tls://fix-oe.binance.com:9000"
transport = "tcp_tls"
request_encoding = "fix_text"
response_encoding = "fix_text"
auth = "signed"
port = 9000
tls_required = true
sni_required = false
status = "supported"
evidence = "documented"
source = "doc"
"""
        )
        assert REASON_FIX_UNPROTECTED in reasons(unprotected)


class TestRefresh:
    """The networked half, driven without a network."""

    def registry(self, tmp_path: Path, text: str) -> Path:
        """Write one registry into a temporary tree.

        Args:
            tmp_path: The tree.
            text: The declaration.

        Returns:
            The root.
        """
        target = tmp_path / "docs" / "engineering"
        target.mkdir(parents=True)
        (target / "binance-api-reality.toml").write_text(text, encoding="utf-8")
        return tmp_path

    def test_a_matching_digest_reports_nothing(self, tmp_path: Path) -> None:
        """The record still holds, which is the answer refresh usually gives."""
        body = b"hello"
        recorded = "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        root = self.registry(
            tmp_path,
            MINIMAL.replace('regime = "digest"', f'regime = "digest"\ndigest = "{recorded}"'),
        )
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(body))
        assert outcome.code == EXIT_OK
        assert outcome.checked == 1

    def test_a_changed_digest_is_reported(self, tmp_path: Path) -> None:
        """A changed document is a question for a person, not an answer."""
        recorded = "sha256:" + "0" * 64
        root = self.registry(
            tmp_path,
            MINIMAL.replace('regime = "digest"', f'regime = "digest"\ndigest = "{recorded}"'),
        )
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(b"moved"))
        assert outcome.code == EXIT_GATE_FAILED
        assert {item.reason for item in outcome.findings} == {REASON_SOURCE_CHANGED}

    def test_an_unreachable_source_is_reported_rather_than_raised(self, tmp_path: Path) -> None:
        """A gate that crashed on a network fault would report nothing at all."""

        def refuse(url: str, timeout: float = 0.0) -> bytes:  # noqa: ARG001
            msg = f"{url} is unreachable"
            raise RegistryError(msg)

        root = self.registry(tmp_path, MINIMAL)
        outcome = run_api_reality(root=root, refresh=True, fetcher=refuse)
        assert {item.reason for item in outcome.findings} == {REASON_SOURCE_UNREACHABLE}

    def test_a_manual_source_is_skipped_rather_than_failed(self, tmp_path: Path) -> None:
        """A source with no fetchable text form cannot be re-checked and says so."""
        manual = MINIMAL.replace('regime = "digest"', 'regime = "manual"')
        root = self.registry(tmp_path, manual)
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(b"x"))
        assert outcome.code == EXIT_OK
        assert outcome.checked == 0

    def test_an_owned_unparseable_source_is_recorded_rather_than_failed(
        self, tmp_path: Path
    ) -> None:
        """Three of the venue's four lifecycle files do not parse today.

        Failing on that would make the gate red for a defect nobody here can fix, and
        a signal that is always red is a signal nobody reads.
        """
        owned = MINIMAL.replace(
            'regime = "digest"', 'regime = "structured"\nknown_unparseable = true'
        )
        root = self.registry(tmp_path, owned)
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(b"{,}"))
        assert outcome.code == EXIT_OK

    def test_an_unowned_unparseable_source_fails(self, tmp_path: Path) -> None:
        """A newly broken structured source is news."""
        root = self.registry(
            tmp_path, MINIMAL.replace('regime = "digest"', 'regime = "structured"')
        )
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(b"{,}"))
        assert {item.reason for item in outcome.findings} == {REASON_STRUCTURED_UNPARSEABLE}

    def test_a_recovered_source_fails_so_the_exemption_is_removed(self, tmp_path: Path) -> None:
        """The other half of the rule, and the half that stops it outliving its reason.

        A source declared unparseable that now parses means the venue fixed it and
        the registry row is stale. Without this the exemption would quietly disable
        the check for ever.
        """
        owned = MINIMAL.replace(
            'regime = "digest"', 'regime = "structured"\nknown_unparseable = true'
        )
        root = self.registry(tmp_path, owned)
        outcome = run_api_reality(root=root, refresh=True, fetcher=answering(b"{}"))
        assert {item.reason for item in outcome.findings} == {REASON_UNPARSEABLE_RECOVERED}


class TestOutcome:
    """What a run publishes, and what it reports when it cannot run."""

    def test_an_absent_registry_is_unmeasured_rather_than_clean(self, tmp_path: Path) -> None:
        """Nothing was established, which is not the same as nothing being wrong."""
        outcome = run_api_reality(root=tmp_path)
        assert outcome.code == EXIT_UNMEASURED

    def test_the_manifest_is_written_even_when_nothing_could_be_read(self, tmp_path: Path) -> None:
        """Evidence that the gate ran is worth more than an empty directory."""
        run_api_reality(root=tmp_path)
        written = tmp_path / ".globin" / "venue" / "api-reality-manifest.json"
        assert written.is_file()
        assert load(written.read_text(encoding="utf-8"))["verdict"] == {
            "code": EXIT_UNMEASURED,
            "reasons": ["API_REALITY_REGISTRY_UNREADABLE"],
        }

    def test_two_runs_over_one_tree_produce_one_manifest(self, tmp_path: Path) -> None:
        """Determinism, asserted by running twice rather than by rendering twice."""
        target = tmp_path / "docs" / "engineering"
        target.mkdir(parents=True)
        (target / "binance-api-reality.toml").write_text(MINIMAL, encoding="utf-8")
        written = tmp_path / ".globin" / "venue" / "api-reality-manifest.json"
        run_api_reality(root=tmp_path)
        first = written.read_text(encoding="utf-8")
        run_api_reality(root=tmp_path)
        assert written.read_text(encoding="utf-8") == first

    def test_describe_names_every_finding(self, tmp_path: Path) -> None:
        """A summary that hid a finding would be worse than no summary."""
        outcome = run_api_reality(root=tmp_path)
        rendered = describe(outcome)
        assert all(item.reason in rendered for item in outcome.findings)

    def test_every_reported_reason_is_a_declared_one(self, tmp_path: Path) -> None:
        """The reason set is closed, so a typo cannot invent a new one."""
        outcome = run_api_reality(root=tmp_path)
        assert {item.reason for item in outcome.findings} <= REASONS


class TestManifest:
    """The evidence verifies itself."""

    def test_the_digest_covers_everything_except_itself(self) -> None:
        """A digest that included itself could never be computed twice."""
        document = build(run={"a": 1}, findings={}, verdict={})
        assert document["digest"] == digest(document)

    def test_content_edited_after_the_digest_was_taken_is_refused(self) -> None:
        """The point of the digest, asserted rather than assumed."""
        document = build(run={"a": 1}, findings={}, verdict={})
        document["run"] = {"a": 2}
        with pytest.raises(ManifestError, match="edited after"):
            load(render(document))

    def test_a_manifest_of_another_schema_is_refused(self) -> None:
        """Two manifests describe this registry, and they are not interchangeable."""
        document = build(run={}, findings={}, verdict={})
        document["schema"] = "globin.api_reality.manifest"
        with pytest.raises(ManifestError, match="announces schema"):
            load(render(document))

    def test_a_manifest_carries_no_timestamp(self) -> None:
        """No manifest in this repository does.

        One that changed because it was built on a different day could not be
        compared with itself, and the determinism check would be measuring the clock.
        """
        rendered = render(build(run={}, findings={}, verdict={}))
        assert "generated" not in rendered
        assert "timestamp" not in rendered


class TestCommandLine:
    """Two words, and the offline one is the default."""

    def test_no_argument_means_the_offline_verb(self) -> None:
        """The default must be the one that reaches nothing."""
        assert parse([]) is False

    def test_check_is_offline_and_refresh_is_not(self) -> None:
        """The networked word is opt-in, which is the shape every such gate uses."""
        assert parse(["check"]) is False
        assert parse(["refresh"]) is True

    @pytest.mark.parametrize("argv", [["probe"], ["check", "refresh"], ["--json"]])
    def test_anything_else_is_a_usage_error(self, argv: list[str]) -> None:
        """A word that silently did nothing is how a caller believes it asked."""
        with pytest.raises(UsageError):
            parse(argv)

    def test_the_usage_text_names_both_verbs_and_every_code(self) -> None:
        """The usage block is the only place an operator reads the exit codes."""
        for token in ("check", "refresh", "0", "1", "2", "3"):
            assert token in USAGE


class TestEntryPoint:
    """The wiring, reachable without starting a process."""

    def test_a_usage_error_reports_two_and_prints_the_usage(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An operator who typed the wrong word gets told which words exist."""
        assert main(["probe"]) == 2
        assert "unrecognised argument" in capsys.readouterr().err

    def test_a_run_reports_the_gate_code(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The offline default over the real tree, which is what CI runs."""
        assert main([]) == EXIT_OK
        assert "api-reality" in capsys.readouterr().out
