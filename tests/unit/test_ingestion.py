"""The ingestion cadence: how old a record is, and when it stops being trusted.

The date is always an argument, never a reading, which is what lets these tests ask
what the registry looks like in two years without waiting.
"""

from pathlib import Path

import pytest

from globin.adapters.ingestion import IngestionPolicyError, parse_policy, read_policy
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
)
from globin.domain.ingestion import (
    MAX_RECHECK_DAYS,
    CadenceRule,
    Freshness,
    IngestionPolicy,
    age_of,
    assess,
)
from globin.errors import ValidationError

POLICY = """
schema = 1
[target]
phase = 34
[default]
recheck_days = 7
reason = "an unknown regime gets the tightest cadence"
[[cadence]]
regime = "structured"
recheck_days = 14
reason = "machine-readable and cheap to re-check"
[[cadence]]
regime = "digest"
recheck_days = 30
reason = "a digest is exact and a change needs a person"
[review]
acknowledged_reasons = ["API_REALITY_SOURCE_CHANGED"]
reason = "a moved document needs a written decision"
"""


def _policy() -> IngestionPolicy:
    """The cadence the tests below reason about."""
    return parse_policy(POLICY)


def _source(
    identifier: str = "s1",
    *,
    accessed: str = "2026-08-01",
    regime: SourceRegime = SourceRegime.DIGEST,
) -> SourceObservation:
    """One declared source read on a chosen date."""
    return SourceObservation(
        identifier=identifier,
        title="A document",
        location="https://example.invalid/doc.md",
        authority=SourceAuthority.PRIMARY,
        accessed=accessed,
        regime=regime,
        digest="" if regime is SourceRegime.MANUAL else "sha256:" + "0" * 64,
    )


class TestCadenceLookup:
    """Which interval applies to which regime."""

    def test_a_declared_regime_gets_its_declared_interval(self) -> None:
        """The straightforward half."""
        assert _policy().days_for("digest") == 30
        assert _policy().days_for("structured") == 14

    def test_an_undeclared_regime_gets_the_default(self) -> None:
        """A regime added to the registry later is bounded from the moment it appears.

        Raising instead would leave the new regime unbounded until somebody
        remembered to add a row, which is exactly when nobody would.
        """
        assert _policy().days_for("a-regime-nobody-wrote-a-rule-for") == 7

    def test_the_default_is_the_tightest_interval_declared(self) -> None:
        """A regime nobody reasoned about is the one GLOBIN understands least."""
        policy = _policy()
        assert policy.default_days <= min(item.recheck_days for item in policy.rules)


class TestAgeing:
    """Fresh, stale, and the state that means the clock is wrong."""

    @pytest.mark.parametrize(
        ("accessed", "as_of", "freshness"),
        [
            pytest.param("2026-08-01", "2026-08-01", Freshness.FRESH, id="read-today"),
            pytest.param("2026-08-01", "2026-08-15", Freshness.FRESH, id="halfway"),
            pytest.param("2026-08-01", "2026-08-31", Freshness.FRESH, id="exactly-at-the-limit"),
            pytest.param("2026-08-01", "2026-09-01", Freshness.STALE, id="one-day-past"),
            pytest.param("2026-08-01", "2027-08-01", Freshness.STALE, id="a-year-past"),
            pytest.param("2026-08-01", "2026-07-30", Freshness.AHEAD_OF_CLOCK, id="clock-behind"),
        ],
    )
    def test_the_boundary_is_strictly_greater_than(
        self, accessed: str, as_of: str, freshness: Freshness
    ) -> None:
        """A source read exactly ``recheck_days`` ago is still fresh.

        The alternative makes ``recheck_days = 1`` mean *stale after zero days*,
        which is not what anybody writing that intends. The exactly-at-the-limit and
        one-day-past cases are both here so the boundary cannot move unnoticed.
        """
        age = age_of(_source(accessed=accessed), _policy(), as_of=as_of)
        assert age.freshness is freshness

    def test_a_clock_behind_the_record_is_never_reported_as_stale(self) -> None:
        """A record cannot be too old to trust because *this machine's* clock is wrong.

        Nor is it silently called fresh: an operator whose clock is days out wants
        to know that before they debug anything else.
        """
        age = age_of(_source(accessed="2026-08-01"), _policy(), as_of="2026-07-01")
        assert age.freshness is Freshness.AHEAD_OF_CLOCK
        assert age.freshness.blocks is False
        assert age.age_days < 0

    def test_only_staleness_blocks(self) -> None:
        """Three states, and exactly one of them refuses a resolution."""
        assert Freshness.STALE.blocks is True
        assert Freshness.FRESH.blocks is False
        assert Freshness.AHEAD_OF_CLOCK.blocks is False

    def test_a_malformed_comparison_date_is_refused(self) -> None:
        """The registry validates its own access dates, so this bites on the caller's."""
        with pytest.raises(ValidationError, match="ISO calendar date"):
            age_of(_source(), _policy(), as_of="not-a-date")


class TestAssessment:
    """The whole registry, aged at once."""

    def _snapshot(self, *sources: SourceObservation) -> ApiRealitySnapshot:
        return ApiRealitySnapshot(sources=sources)

    def test_stale_identifiers_are_what_the_resolver_is_handed(self) -> None:
        """The join between this phase's two halves, as a list of names."""
        snapshot = self._snapshot(
            _source("fresh-one", accessed="2026-08-15"),
            _source("stale-one", accessed="2026-01-01"),
        )
        report = assess(snapshot, _policy(), as_of="2026-08-19")
        assert report.stale == ("stale-one",)

    def test_the_counts_include_the_zeroes(self) -> None:
        """An absent key would read as an absent question."""
        report = assess(self._snapshot(_source()), _policy(), as_of="2026-08-19")
        assert set(report.counts()) == {item.value for item in Freshness}

    def test_the_report_is_ordered_so_two_runs_agree(self) -> None:
        """Evidence that reordered itself would digest differently every run."""
        snapshot = self._snapshot(_source("zzz"), _source("aaa"), _source("mmm"))
        report = assess(snapshot, _policy(), as_of="2026-08-19")
        identifiers = [item.identifier for item in report.ages]
        assert identifiers == sorted(identifiers)

    def test_a_clock_behind_the_registry_is_reported_separately(self) -> None:
        """Worth saying out loud before an operator concludes anything else."""
        report = assess(
            self._snapshot(_source("ahead", accessed="2026-09-01")),
            _policy(),
            as_of="2026-08-19",
        )
        assert report.ahead_of_clock == ("ahead",)
        assert report.stale == ()


class TestPolicyValidation:
    """What a cadence refuses to be."""

    def test_a_repeated_regime_is_refused(self) -> None:
        """Two intervals for one regime is a lookup nobody can predict."""
        rule = CadenceRule(regime="digest", recheck_days=30, reason="because")
        with pytest.raises(ValidationError, match="more than once"):
            IngestionPolicy(rules=(rule, rule), default_days=7, default_reason="because")

    @pytest.mark.parametrize("days", [0, -1, MAX_RECHECK_DAYS + 1])
    def test_an_interval_outside_the_permitted_range_is_refused(self, days: int) -> None:
        """Zero is not a cadence, and a typo that adds a digit is not a decade."""
        with pytest.raises(ValidationError, match="outside"):
            CadenceRule(regime="digest", recheck_days=days, reason="because")

    def test_a_boolean_interval_is_refused(self) -> None:
        """``bool`` subclasses ``int``, so ``True`` would pass as a one-day cadence."""
        with pytest.raises(ValidationError, match="whole number"):
            CadenceRule(regime="digest", recheck_days=True, reason="because")

    def test_a_rule_must_argue_for_itself(self) -> None:
        """Every rule states why.

        A cadence is GLOBIN's own judgement rather than a venue fact, so it carries
        an argument where a registry row carries a citation.
        """
        with pytest.raises(ValidationError, match="no reason"):
            CadenceRule(regime="digest", recheck_days=30, reason="")


class TestPolicyReading:
    """The package's reader, and what it deliberately does not read."""

    def test_the_package_does_not_parse_the_review_table(self) -> None:
        """Acknowledging a change is a repository act rather than a runtime one.

        The gate under ``tools/`` reads ``[review]``; the package reads the cadence,
        because staleness is what the transport fails closed on. Two readers of one
        document, each taking the half it acts on — proved here by removing the
        table and watching the package still parse.
        """
        without_review = POLICY.split("[review]")[0]
        policy = parse_policy(without_review)
        assert policy.days_for("digest") == 30

    def test_malformed_toml_is_refused_rather_than_raised_through(self) -> None:
        """``TOMLDecodeError`` is a ``ValueError``, which Phase 030 found the hard way."""
        with pytest.raises(IngestionPolicyError, match="not valid TOML"):
            parse_policy("this is not [ toml")

    def test_a_missing_default_table_is_refused(self) -> None:
        """Without it a regime nobody declared would be unbounded."""
        with pytest.raises(IngestionPolicyError, match=r"\[default\]"):
            parse_policy("schema = 1\n")

    def test_an_absent_document_reads_as_nothing_rather_than_as_permissive(
        self, tmp_path: Path
    ) -> None:
        """``None`` means unmeasured, and a caller must not read it as *nothing is stale*.

        Treating a missing document as permission to trust every record for ever is
        precisely the optimistic acceptance this phase exists to refuse.
        """
        assert read_policy(tmp_path / "absent.toml") is None

    def test_the_committed_policy_parses(self, repo_root: Path) -> None:
        """The document this repository actually ships."""
        from globin.adapters.ingestion import POLICY_PATH

        policy = read_policy(repo_root / POLICY_PATH)
        assert policy is not None
        assert policy.days_for("digest") > 0
        assert policy.days_for("manual") > policy.days_for("structured")

    @pytest.mark.parametrize(
        ("document", "match"),
        [
            pytest.param(
                'schema = 1\n[default]\nreason = "x"\n',
                "not an integer",
                id="a-default-with-no-interval",
            ),
            pytest.param(
                "schema = 1\n[default]\nrecheck_days = 7\n",
                "not a string",
                id="a-default-with-no-reason",
            ),
            pytest.param(
                'schema = 1\ncadence = "no"\n[default]\nrecheck_days = 7\nreason = "x"\n',
                "array of tables",
                id="cadence-that-is-not-an-array",
            ),
            pytest.param(
                'schema = 1\ncadence = [1]\n[default]\nrecheck_days = 7\nreason = "x"\n',
                "not a table",
                id="a-cadence-entry-that-is-not-a-table",
            ),
            pytest.param(
                'schema = 1\n[[cadence]]\nregime = 7\nrecheck_days = 7\nreason = "x"\n'
                '[default]\nrecheck_days = 7\nreason = "x"\n',
                "not a string",
                id="a-regime-that-is-not-a-string",
            ),
        ],
    )
    def test_every_malformation_is_refused(self, document: str, match: str) -> None:
        """The branches a correct document never reaches.

        Each would otherwise let a malformed cadence read as *no cadence*, which
        reports every source fresh for ever — the failure direction that matters,
        because it silently unblocks the transport rather than blocking it.
        """
        with pytest.raises(IngestionPolicyError, match=match):
            parse_policy(document)
