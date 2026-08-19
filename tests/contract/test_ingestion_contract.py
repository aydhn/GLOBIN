"""The two readers of the ingestion policy, compared against each other.

``src/globin/adapters/ingestion.py`` and ``tools/quality/venue/ingestion.py`` parse
the same committed document and share no code. That is deliberate — it is the same
arrangement Phase 033 built for the registry — and it is only worth anything if
something compares what the two see. This does.

**They read different halves on purpose.** The package takes ``[default]`` and
``[cadence]``, because staleness is what the transport fails closed on. The gate
takes ``[review]`` as well, because acknowledging a changed document is a repository
act rather than a runtime one. What must agree is the arithmetic: given the same
source and the same date, both must call it stale or both must not.
"""

from pathlib import Path

import pytest

from globin.adapters.ingestion import POLICY_PATH, read_policy
from globin.domain.api_reality import (
    ApiRealitySnapshot,
    SourceAuthority,
    SourceObservation,
    SourceRegime,
)
from globin.domain.ingestion import assess
from tools.quality.venue.ingestion import ACKNOWLEDGEMENTS_PATH, read_acknowledgements
from tools.quality.venue.ingestion import Policy as GatePolicy
from tools.quality.venue.ingestion import ages as gate_ages
from tools.quality.venue.ingestion import read_policy as gate_read_policy
from tools.quality.venue.plan import Source as GateSource

REGIMES = ("structured", "digest", "manual", "a-regime-nobody-declared")
"""Every declared regime, plus one nobody declared, so the default is compared too."""

DATES = ("2026-08-19", "2026-09-19", "2026-11-19", "2027-08-19")
"""Dates spanning fresh through long past every declared interval."""


@pytest.fixture(scope="module")
def package_policy(repo_root: Path) -> object:
    """The cadence as the package reads it."""
    found = read_policy(repo_root / POLICY_PATH)
    assert found is not None, f"{POLICY_PATH} is absent"
    return found


@pytest.fixture(scope="module")
def gate_policy(repo_root: Path) -> GatePolicy:
    """The cadence as the gate reads it."""
    found = gate_read_policy(repo_root)
    assert found is not None, f"{POLICY_PATH} is absent"
    return found


class TestTheTwoReadersAgree:
    """Same document, same arithmetic, no shared code."""

    @pytest.mark.parametrize("regime", REGIMES)
    def test_both_readers_derive_the_same_interval(
        self, package_policy: object, gate_policy: GatePolicy, regime: str
    ) -> None:
        """Including the regime nobody declared, where both must fall back the same way."""
        assert package_policy.days_for(regime) == gate_policy.days_for(regime)  # type: ignore[attr-defined]

    @pytest.mark.parametrize("regime", ["structured", "digest", "manual"])
    @pytest.mark.parametrize("as_of", DATES)
    def test_both_readers_call_the_same_source_stale(
        self, package_policy: object, gate_policy: GatePolicy, regime: str, as_of: str
    ) -> None:
        """The off-by-one this test exists to catch.

        Both implementations use *strictly greater than*, so a source read exactly
        ``recheck_days`` ago is fresh. Written independently, that is exactly the
        boundary two people would get differently — and a disagreement would mean
        the gate reporting a source as fresh while the transport refused to use it.
        """
        source = SourceObservation(
            identifier="s1",
            title="A document",
            location="https://example.invalid/doc.md",
            authority=SourceAuthority.PRIMARY,
            accessed="2026-08-19",
            regime=SourceRegime(regime),
            digest="" if regime == "manual" else "sha256:" + "0" * 64,
        )
        package = assess(ApiRealitySnapshot(sources=(source,)), package_policy, as_of=as_of)  # type: ignore[arg-type]
        gate = gate_ages(
            (
                GateSource(
                    identifier="s1", location="x", regime=regime, digest="", accessed="2026-08-19"
                ),
            ),
            gate_policy,
            as_of=as_of,
        )
        assert bool(package.stale) is gate[0].stale
        assert package.ages[0].age_days == gate[0].age_days
        assert package.ages[0].allowed_days == gate[0].allowed_days

    def test_both_readers_see_the_same_committed_registry_as_fresh(
        self, repo_root: Path, package_policy: object, gate_policy: GatePolicy
    ) -> None:
        """The real document, aged by both, on the date it was recorded.

        This is the one that would fail if somebody edited a source's ``accessed``
        date and only one reader noticed.
        """
        from globin.adapters.api_reality import REGISTRY_PATH, read_registry
        from tools.quality.venue.plan import parse_declaration

        snapshot = read_registry(repo_root / REGISTRY_PATH)
        declaration = parse_declaration((repo_root / REGISTRY_PATH).read_text(encoding="utf-8"))
        assert snapshot is not None
        as_of = "2026-08-19"
        package = assess(snapshot, package_policy, as_of=as_of)  # type: ignore[arg-type]
        gate = gate_ages(declaration.sources, gate_policy, as_of=as_of)
        assert len(package.ages) == len(gate)
        assert list(package.stale) == sorted(item.identifier for item in gate if item.stale)


class TestTheGateHalf:
    """The review workflow, which the package deliberately does not read."""

    def test_the_gate_reads_the_review_table_and_the_package_does_not(
        self, package_policy: object, gate_policy: GatePolicy
    ) -> None:
        """Two readers of one document, each taking the half it acts on."""
        assert gate_policy.acknowledged_reasons
        assert not hasattr(package_policy, "acknowledged_reasons")

    def test_the_acknowledgement_ledger_is_readable_and_currently_empty(
        self, repo_root: Path
    ) -> None:
        """Empty is the measured state, not an unfinished one.

        Every source digest was verified during Phase 034 and every one still
        matched Phase 033's record, so there has been no drift to acknowledge. An
        empty ledger is not permissive: with no rows, *any* source-changed finding
        fails the gate.
        """
        assert (repo_root / ACKNOWLEDGEMENTS_PATH).is_file()
        assert read_acknowledgements(repo_root) == ()

    def test_an_absent_ledger_reads_as_empty_rather_than_as_permission(
        self, tmp_path: Path
    ) -> None:
        """The safe direction: nothing acknowledged means nothing excused."""
        assert read_acknowledgements(tmp_path) == ()

    def test_the_declared_reason_is_one_the_gate_actually_emits(
        self, gate_policy: GatePolicy
    ) -> None:
        """A policy naming a reason nothing produces would be a rule that never fires."""
        from tools.quality.venue.plan import REASON_SOURCE_CHANGED

        assert REASON_SOURCE_CHANGED in gate_policy.acknowledged_reasons


class TestUnacknowledgedDrift:
    """The ledger fails in both directions."""

    def test_a_finding_with_no_row_is_unacknowledged(self, gate_policy: GatePolicy) -> None:
        """Somebody has to write down what a moved document means."""
        from tools.quality.venue.ingestion import unacknowledged

        findings = [("API_REALITY_SOURCE_CHANGED", "spot-rest")]
        assert unacknowledged(findings, gate_policy, ()) == (
            ("API_REALITY_SOURCE_CHANGED", "spot-rest"),
        )

    def test_a_finding_the_policy_does_not_name_needs_no_row(self, gate_policy: GatePolicy) -> None:
        """Only the declared reasons need a decision; the rest fail on their own terms."""
        from tools.quality.venue.ingestion import unacknowledged

        findings = [("API_REALITY_SOURCE_UNREACHABLE", "spot-rest")]
        assert unacknowledged(findings, gate_policy, ()) == ()

    def test_an_acknowledgement_whose_finding_stopped_occurring_is_superseded(self) -> None:
        """A standing permission nobody re-examined is how an exemption outlives its reason.

        The same bargain ``wheel-survey.toml`` strikes for an owned gap: fine until
        the gap closes, and then the record must go.
        """
        from tools.quality.venue.ingestion import Acknowledgement, superseded

        row = Acknowledgement(
            finding="API_REALITY_SOURCE_CHANGED",
            subject="spot-rest",
            phase=34,
            decided_on="2026-08-19",
            note="a heading moved and no capability changed",
        )
        assert superseded([], (row,)) == (row,)
        assert superseded([("API_REALITY_SOURCE_CHANGED", "spot-rest")], (row,)) == ()


class TestTheIngestionGuideStatesWhatIsTrue:
    """The one counted claim in `DOCUMENTATION_INGESTION.md`, recomputed.

    Phase 034's REST guide got two counts wrong on its first draft, which is the
    argument for binding every restatement rather than the confident ones.
    `SOURCE_OF_TRUTH.md` permits a restatement only where a test compares it to its
    source; this is that comparison.
    """

    GUIDE = "docs/engineering/DOCUMENTATION_INGESTION.md"

    def test_the_declared_source_count_matches_the_registry(self, repo_root: Path) -> None:
        """The guide names a number of sources; the registry is what has them."""
        from globin.adapters.api_reality import REGISTRY_PATH, read_registry

        registry = read_registry(repo_root / REGISTRY_PATH)
        assert registry is not None
        spelled = {
            10: "Ten",
            11: "Eleven",
            12: "Twelve",
            13: "Thirteen",
            14: "Fourteen",
            15: "Fifteen",
            16: "Sixteen",
            17: "Seventeen",
            18: "Eighteen",
            19: "Nineteen",
            20: "Twenty",
        }
        claim = f"{spelled[len(registry.sources)]} sources are declared"
        text = (repo_root / self.GUIDE).read_text(encoding="utf-8")
        assert claim in text, f"{self.GUIDE} does not state {claim!r}; the registry carries that"

    def test_every_declared_regime_has_a_row_in_the_guide(
        self, repo_root: Path, gate_policy: GatePolicy
    ) -> None:
        """A cadence nobody documented is a number an operator cannot argue with.

        The other direction matters more than the count: a regime added to the
        policy without a row in the guide is a rule that fires and is never
        explained.
        """
        text = (repo_root / self.GUIDE).read_text(encoding="utf-8")
        missing = [item.regime for item in gate_policy.rules if f"`{item.regime}`" not in text]
        assert not missing, f"{self.GUIDE} documents no cadence for: {missing}"

    def test_every_documented_interval_is_the_one_declared(
        self, repo_root: Path, gate_policy: GatePolicy
    ) -> None:
        """The interval beside each regime, not merely the regime's name."""
        text = (repo_root / self.GUIDE).read_text(encoding="utf-8")
        wrong = [
            item.regime
            for item in gate_policy.rules
            if f"| `{item.regime}` | {item.recheck_days} days |" not in text
        ]
        assert not wrong, f"{self.GUIDE} states the wrong interval for: {wrong}"
