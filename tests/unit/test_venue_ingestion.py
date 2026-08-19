"""The gate's half of the ingestion policy: the reader, the ledger and the journal.

**Almost every test here drives a refusal**, and that is the point. These are the
branches a correct committed document never reaches — which makes them the branches
that would silently accept the wrong thing if one broke. A gate that read a
malformed cadence as "no cadence" would report every source fresh for ever.

`tests/contract/test_ingestion_contract.py` compares this reader against the
package's. This one exercises what it does when the document is wrong.
"""

import json
from pathlib import Path

import pytest

from tools.quality.venue.ingestion import (
    ACKNOWLEDGEMENTS_PATH,
    JOURNAL_NAME,
    POLICY_PATH,
    Acknowledgement,
    Cadence,
    Policy,
    PolicyError,
    ages,
    append_journal,
    read_acknowledgements,
    read_journal,
    read_policy,
    superseded,
    today,
    unacknowledged,
)
from tools.quality.venue.plan import Source

GOOD_POLICY = """
schema = 1
[default]
recheck_days = 7
reason = "the tightest cadence"
[[cadence]]
regime = "digest"
recheck_days = 30
reason = "a digest is exact"
[review]
acknowledged_reasons = ["API_REALITY_SOURCE_CHANGED"]
reason = "a moved document needs a decision"
"""


def _write(root: Path, text: str, *, name: str = POLICY_PATH) -> Path:
    """Put a document where the reader looks for it.

    Args:
        root: A throwaway repository root.
        text: What to write.
        name: Which document.

    Returns:
        The path written.
    """
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _source(identifier: str = "s1", regime: str = "digest", accessed: str = "2026-08-01") -> Source:
    """One declared source as the gate's own reader sees it."""
    return Source(
        identifier=identifier,
        location="https://example.invalid/doc.md",
        regime=regime,
        digest="",
        accessed=accessed,
    )


class TestReadingTheCadence:
    """Every way the document can be wrong, and the one way it can be right."""

    def test_a_well_formed_policy_parses(self, tmp_path: Path) -> None:
        """So the refusals below are not the only thing proved."""
        _write(tmp_path, GOOD_POLICY)
        policy = read_policy(tmp_path)
        assert policy is not None
        assert policy.days_for("digest") == 30
        assert policy.days_for("anything-else") == 7
        assert policy.acknowledged_reasons == ("API_REALITY_SOURCE_CHANGED",)

    def test_an_absent_document_reads_as_nothing(self, tmp_path: Path) -> None:
        """Unmeasured, which a caller reports rather than treating as permissive."""
        assert read_policy(tmp_path) is None

    def test_malformed_toml_is_refused(self, tmp_path: Path) -> None:
        """``TOMLDecodeError`` is a ``ValueError``, which Phase 030 found the hard way."""
        _write(tmp_path, "this is not [ toml")
        with pytest.raises(PolicyError, match="not valid TOML"):
            read_policy(tmp_path)

    @pytest.mark.parametrize(
        ("document", "match"),
        [
            pytest.param("schema = 1\n", r"\[default\]", id="no-default-and-no-review"),
            pytest.param(
                'schema = 1\n[default]\nrecheck_days = 7\nreason = "x"\n',
                r"\[review\]",
                id="no-review",
            ),
            pytest.param(
                'schema = 1\n[default]\nreason = "x"\n[review]\nacknowledged_reasons = []\n',
                "default re-check interval",
                id="default-without-an-interval",
            ),
            pytest.param(
                'schema = 1\n[default]\nrecheck_days = true\nreason = "x"\n'
                "[review]\nacknowledged_reasons = []\n",
                "default re-check interval",
                id="a-boolean-interval",
            ),
            pytest.param(
                'schema = 1\n[default]\nrecheck_days = 7\nreason = "x"\n'
                '[review]\nacknowledged_reasons = "not-a-list"\n',
                "acknowledged_reasons",
                id="reasons-that-are-not-a-list",
            ),
            pytest.param(
                'schema = 1\n[default]\nrecheck_days = 7\nreason = "x"\n'
                "[review]\nacknowledged_reasons = [1, 2]\n",
                "acknowledged_reasons",
                id="reasons-that-are-not-strings",
            ),
            pytest.param(
                'schema = 1\n[default]\nrecheck_days = 7\nreason = "x"\n[review]\nreason = "x"\n',
                "acknowledged_reasons",
                id="a-missing-reasons-key",
            ),
            pytest.param(
                'schema = 1\ncadence = "not-an-array"\n[default]\nrecheck_days = 7\nreason = "x"\n'
                "[review]\nacknowledged_reasons = []\n",
                "array of tables",
                id="cadence-that-is-not-an-array",
            ),
            pytest.param(
                'schema = 1\ncadence = [1]\n[default]\nrecheck_days = 7\nreason = "x"\n'
                "[review]\nacknowledged_reasons = []\n",
                "not a table",
                id="a-cadence-entry-that-is-not-a-table",
            ),
            pytest.param(
                'schema = 1\n[[cadence]]\nregime = "digest"\n'
                '[default]\nrecheck_days = 7\nreason = "x"\n'
                "[review]\nacknowledged_reasons = []\n",
                "missing a regime or an interval",
                id="a-cadence-entry-with-no-interval",
            ),
        ],
    )
    def test_every_malformation_is_refused(self, tmp_path: Path, document: str, match: str) -> None:
        """Ten ways to be wrong, each producing a message naming what is wrong.

        The empty-list case is deliberately **absent** from this table: an empty
        ``acknowledged_reasons`` is a legitimate policy saying no finding needs a
        written decision. Only a *missing* key is refused, because defaulting it
        would turn a typo into permission.
        """
        _write(tmp_path, document)
        with pytest.raises(PolicyError, match=match):
            read_policy(tmp_path)

    def test_an_empty_reasons_list_is_permitted(self, tmp_path: Path) -> None:
        """The other half of the rule above, so the refusal is not over-broad."""
        _write(
            tmp_path,
            'schema = 1\n[default]\nrecheck_days = 7\nreason = "x"\n'
            "[review]\nacknowledged_reasons = []\n",
        )
        policy = read_policy(tmp_path)
        assert policy is not None
        assert policy.acknowledged_reasons == ()


class TestAgeing:
    """The arithmetic, and the one input that cannot be aged."""

    def _policy(self) -> Policy:
        return Policy(
            rules=(Cadence(regime="digest", recheck_days=30),),
            default_days=7,
            acknowledged_reasons=(),
        )

    def test_ages_are_returned_in_identifier_order(self) -> None:
        """Evidence that reordered itself would digest differently every run."""
        found = ages(
            (_source("zzz"), _source("aaa"), _source("mmm")), self._policy(), as_of="2026-08-01"
        )
        assert [item.identifier for item in found] == ["aaa", "mmm", "zzz"]

    def test_the_boundary_is_strictly_greater_than(self) -> None:
        """Read exactly ``recheck_days`` ago is still fresh."""
        exact = ages((_source(),), self._policy(), as_of="2026-08-31")
        past = ages((_source(),), self._policy(), as_of="2026-09-01")
        assert exact[0].stale is False
        assert past[0].stale is True

    def test_an_undeclared_regime_uses_the_default(self) -> None:
        """Bounded from the moment a new regime appears rather than when somebody notices."""
        found = ages((_source(regime="brand-new"),), self._policy(), as_of="2026-08-09")
        assert found[0].allowed_days == 7
        assert found[0].stale is True

    def test_a_source_with_no_access_date_is_refused(self) -> None:
        """Phase 033's registry requires one, so this bites on a hand-built row.

        Reported rather than skipped: a source silently excluded from ageing is a
        source that can never go stale.
        """
        with pytest.raises(PolicyError, match="ISO date"):
            ages((_source(accessed=""),), self._policy(), as_of="2026-08-01")

    def test_the_record_is_json_safe(self) -> None:
        """It goes into the manifest, so every leaf must survive `json.dumps`."""
        record = ages((_source(),), self._policy(), as_of="2026-08-01")[0].as_record()
        assert json.loads(json.dumps(record))["identifier"] == "s1"

    def test_today_is_an_iso_date(self) -> None:
        """The gate reads the clock so :func:`ages` stays pure and testable."""
        assert len(today()) == 10
        assert today().count("-") == 2


class TestTheAcknowledgementLedger:
    """A written decision, and every way one can be malformed."""

    def test_a_well_formed_ledger_parses(self, tmp_path: Path) -> None:
        """The happy path, so the refusals mean something."""
        _write(
            tmp_path,
            'schema = 1\n[[acknowledgement]]\nfinding = "API_REALITY_SOURCE_CHANGED"\n'
            'subject = "spot-rest"\nphase = 34\ndecided_on = "2026-08-19"\n'
            'note = "a heading moved"\n',
            name=ACKNOWLEDGEMENTS_PATH,
        )
        found = read_acknowledgements(tmp_path)
        assert len(found) == 1
        assert found[0].identity == ("API_REALITY_SOURCE_CHANGED", "spot-rest")

    def test_an_absent_ledger_is_empty_rather_than_permissive(self, tmp_path: Path) -> None:
        """The safe direction: nothing acknowledged means nothing excused."""
        assert read_acknowledgements(tmp_path) == ()

    def test_malformed_toml_is_refused(self, tmp_path: Path) -> None:
        """A ledger nobody can read must not read as a ledger with no rows."""
        _write(tmp_path, "not [ toml", name=ACKNOWLEDGEMENTS_PATH)
        with pytest.raises(PolicyError, match="not valid TOML"):
            read_acknowledgements(tmp_path)

    @pytest.mark.parametrize(
        ("document", "match"),
        [
            pytest.param(
                'acknowledgement = "not-an-array"\n', "array of tables", id="not-an-array"
            ),
            pytest.param(
                "acknowledgement = [1]\n", "not a table", id="an-entry-that-is-not-a-table"
            ),
            pytest.param(
                '[[acknowledgement]]\nfinding = "X"\n', "incomplete", id="a-row-missing-fields"
            ),
        ],
    )
    def test_every_malformation_is_refused(self, tmp_path: Path, document: str, match: str) -> None:
        """An incomplete row is refused rather than partly read."""
        _write(tmp_path, document, name=ACKNOWLEDGEMENTS_PATH)
        with pytest.raises(PolicyError, match=match):
            read_acknowledgements(tmp_path)


class TestTheLedgerFailsInBothDirections:
    """An unacknowledged change fails; an acknowledgement that outlived its finding fails."""

    def _policy(self) -> Policy:
        return Policy(
            rules=(),
            default_days=7,
            acknowledged_reasons=("API_REALITY_SOURCE_CHANGED",),
        )

    def _row(self, subject: str = "spot-rest") -> Acknowledgement:
        return Acknowledgement(
            finding="API_REALITY_SOURCE_CHANGED",
            subject=subject,
            phase=34,
            decided_on="2026-08-19",
            note="a heading moved and no capability changed",
        )

    def test_an_unacknowledged_finding_is_reported(self) -> None:
        """Somebody has to write down what a moved document means."""
        findings = [("API_REALITY_SOURCE_CHANGED", "spot-rest")]
        assert unacknowledged(findings, self._policy(), ()) == (
            ("API_REALITY_SOURCE_CHANGED", "spot-rest"),
        )

    def test_an_acknowledged_finding_is_not_reported(self) -> None:
        """The row does its job."""
        findings = [("API_REALITY_SOURCE_CHANGED", "spot-rest")]
        assert unacknowledged(findings, self._policy(), (self._row(),)) == ()

    def test_a_reason_the_policy_does_not_name_needs_no_row(self) -> None:
        """Only the declared reasons need a decision; the rest fail on their own terms."""
        findings = [("API_REALITY_SOURCE_UNREACHABLE", "spot-rest")]
        assert unacknowledged(findings, self._policy(), ()) == ()

    def test_a_row_for_a_different_subject_does_not_cover_this_one(self) -> None:
        """An acknowledgement is per source, not per reason.

        Without this, one decision about one document would excuse every future
        change to every other.
        """
        findings = [("API_REALITY_SOURCE_CHANGED", "spot-rest")]
        assert unacknowledged(findings, self._policy(), (self._row("spot-testnet"),)) != ()

    def test_an_acknowledgement_whose_finding_stopped_occurring_is_superseded(self) -> None:
        """A standing permission nobody re-examined is how an exemption outlives its reason."""
        row = self._row()
        assert superseded([], (row,)) == (row,)
        assert superseded([("API_REALITY_SOURCE_CHANGED", "spot-rest")], (row,)) == ()

    def test_the_report_is_sorted(self) -> None:
        """Two runs over one state produce one message."""
        findings = [
            ("API_REALITY_SOURCE_CHANGED", "zzz"),
            ("API_REALITY_SOURCE_CHANGED", "aaa"),
        ]
        assert unacknowledged(findings, self._policy(), ()) == (
            ("API_REALITY_SOURCE_CHANGED", "aaa"),
            ("API_REALITY_SOURCE_CHANGED", "zzz"),
        )


class TestTheChangeJournal:
    """Append-only, and a run that found nothing appends nothing."""

    def test_an_absent_journal_reads_as_empty(self, tmp_path: Path) -> None:
        """Nothing has moved, or nothing has looked."""
        assert read_journal(tmp_path) == ()

    def test_a_record_round_trips(self, tmp_path: Path) -> None:
        """What is written is what is read back."""
        append_journal(tmp_path, {"recorded_at": "2026-08-19", "findings": []})
        found = read_journal(tmp_path)
        assert len(found) == 1
        assert found[0]["recorded_at"] == "2026-08-19"

    def test_appending_never_rewrites(self, tmp_path: Path) -> None:
        """Every line is a moment something moved, and the earlier ones survive."""
        append_journal(tmp_path, {"recorded_at": "2026-08-01"})
        append_journal(tmp_path, {"recorded_at": "2026-08-19"})
        found = read_journal(tmp_path)
        assert [item["recorded_at"] for item in found] == ["2026-08-01", "2026-08-19"]

    def test_the_directory_is_created_if_absent(self, tmp_path: Path) -> None:
        """The first refresh on a fresh clone has nowhere to write yet."""
        target = tmp_path / "deep" / "nested"
        written = append_journal(target, {"recorded_at": "2026-08-19"})
        assert written.is_file()
        assert written.name == JOURNAL_NAME

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        """A trailing newline is not a record."""
        (tmp_path / JOURNAL_NAME).write_text('{"a":1}\n\n\n', encoding="utf-8")
        assert len(read_journal(tmp_path)) == 1

    def test_a_corrupt_line_is_reported_rather_than_skipped(self, tmp_path: Path) -> None:
        """Silently dropping a line would lose exactly the record somebody is looking for."""
        (tmp_path / JOURNAL_NAME).write_text('{"a":1}\nnot json\n', encoding="utf-8")
        with pytest.raises(PolicyError, match="line 2 is not JSON"):
            read_journal(tmp_path)

    def test_a_line_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        """Valid JSON that is not a record is still not a record."""
        (tmp_path / JOURNAL_NAME).write_text("[1,2,3]\n", encoding="utf-8")
        with pytest.raises(PolicyError, match="not an object"):
            read_journal(tmp_path)

    def test_the_line_is_canonical_json(self, tmp_path: Path) -> None:
        """Sorted keys and no incidental whitespace, so two writes of one record match."""
        append_journal(tmp_path, {"b": 2, "a": 1})
        assert (tmp_path / JOURNAL_NAME).read_text(encoding="utf-8") == '{"a":1,"b":2}\n'
