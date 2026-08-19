"""The api-reality command group, driven through the real entry point.

Everything here goes through :func:`globin.runtime.cli.main`, so the parser, the
dispatch, the reader and the rendering are exercised together. Nothing reaches a
network: the product CLI has no verb that could, which is the property
``tests/architecture/test_library_discipline.py`` proves.
"""

import io
import json
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.runtime.cli import main


def run(*argv: str, start: Path | None = None) -> tuple[int, str, str]:
    """One invocation, with both streams captured.

    Args:
        *argv: The arguments after the program name.
        start: Where to begin looking for the repository root.

    Returns:
        The exit code, standard output and standard error.
    """
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, start=start)
    return code, out.getvalue(), err.getvalue()


class TestReading:
    """Seven verbs, each answering from the committed registry."""

    @pytest.mark.parametrize(
        "verb", ["show", "products", "surfaces", "environments", "capability", "verify"]
    )
    def test_every_read_verb_answers(self, verb: str, repo_root: Path) -> None:
        """A verb that could not answer would be a verb nobody could use."""
        code, out, _ = run("api-reality", verb, start=repo_root)
        assert code == int(ExitCode.OK)
        assert out.strip()

    def test_the_default_verb_is_show(self, repo_root: Path) -> None:
        """A bare group name answers rather than refusing."""
        bare = run("api-reality", start=repo_root)
        named = run("api-reality", "show", start=repo_root)
        assert bare == named

    def test_products_names_every_family(self, repo_root: Path) -> None:
        """The roadmap row's own deliverable, reachable in one command."""
        _, out, _ = run("api-reality", "products", start=repo_root)
        for family in ("spot", "usds_m_futures", "options", "portfolio_margin"):
            assert family in out

    def test_capability_can_be_asked_about_one_status(self, repo_root: Path) -> None:
        """The word that matters most is the one worth being able to list."""
        code, out, _ = run("api-reality", "capability", "unknown", start=repo_root)
        assert code == int(ExitCode.OK)
        assert out.count("\n") > 1

    def test_an_unrecognised_status_is_a_usage_error(self, repo_root: Path) -> None:
        """Six words, and a seventh is refused rather than silently matching nothing."""
        code, _, err = run("api-reality", "capability", "maybe", start=repo_root)
        assert code == int(ExitCode.USAGE)
        assert "is not a status" in err

    def test_an_unrecognised_verb_is_a_usage_error(self, repo_root: Path) -> None:
        """The subcommand tuple is closed."""
        code, _, _ = run("api-reality", "refresh", start=repo_root)
        assert code == int(ExitCode.USAGE)


class TestJsonDiscipline:
    """Under `--json`, standard output carries JSON and nothing else."""

    @pytest.mark.parametrize("verb", ["show", "products", "environments", "verify"])
    def test_standard_output_is_only_json(self, verb: str, repo_root: Path) -> None:
        """The one contract the flag makes, asserted by parsing the whole stream."""
        code, out, err = run("api-reality", verb, "--json", start=repo_root)
        assert code == int(ExitCode.OK)
        assert isinstance(json.loads(out), dict)
        assert err.strip()

    def test_the_human_report_moves_to_standard_error(self, repo_root: Path) -> None:
        """It is not discarded, it is moved -- an operator still sees it."""
        _, _, err = run("api-reality", "show", "--json", start=repo_root)
        assert "api-reality" in err


class TestUnmeasured:
    """No registry is unmeasured, which is not the same as clean."""

    def test_a_tree_without_a_registry_reports_unmeasured(self, tmp_path: Path) -> None:
        """Nothing was established. Exit 3, as every gate in this repository spells it."""
        code, out, _ = run("api-reality", "show", start=tmp_path)
        assert code == int(ExitCode.UNMEASURED)
        assert "unmeasured" in out

    def test_an_invalid_registry_fails_rather_than_reporting_unmeasured(
        self, tmp_path: Path
    ) -> None:
        """A broken document is a defect; flattening it into absence would hide one."""
        target = tmp_path / "docs" / "engineering"
        target.mkdir(parents=True)
        (target / "binance-api-reality.toml").write_text("schema = 99\n", encoding="utf-8")
        code, _, err = run("api-reality", "show", start=tmp_path)
        assert code == int(ExitCode.GATE_FAILED)
        assert "did not validate" in err


class TestDiff:
    """A pure comparison, needing neither a network nor a clock."""

    def test_a_registry_does_not_differ_from_itself(self, repo_root: Path) -> None:
        """The committed registry against itself is the empty diff."""
        registry = repo_root / "docs" / "engineering" / "binance-api-reality.toml"
        code, out, _ = run("api-reality", "diff", str(registry), start=repo_root)
        assert code == int(ExitCode.OK)
        assert "0 findings" in out

    def test_an_endpoint_the_registry_no_longer_has_is_breaking(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Losing a live endpoint is breaking, and the exit code says so.

        The direction matters and is easy to get backwards: `diff PATH` compares the
        named snapshot as the earlier one, so an endpoint present *there* and absent
        from the registry is the loss.
        """
        registry = repo_root / "docs" / "engineering" / "binance-api-reality.toml"
        richer = (
            registry.read_text(encoding="utf-8")
            + """
[[endpoint]]
family = "spot"
environment = "production"
protocol = "rest"
url = "https://api5.binance.com/api"
transport = "https"
request_encoding = "json"
response_encoding = "json"
auth = "signed"
capabilities = ["market_data"]
status = "supported"
evidence = "documented"
source = "spot-rest"
"""
        )
        other = tmp_path / "older.toml"
        other.write_text(richer, encoding="utf-8")
        code, out, _ = run("api-reality", "diff", str(other), start=repo_root)
        assert code == int(ExitCode.GATE_FAILED)
        assert "endpoint_removed" in out
        assert "breaking" in out

    def test_an_endpoint_the_registry_has_gained_is_informational(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Gaining a capability breaks nothing, so the command still exits zero."""
        registry = repo_root / "docs" / "engineering" / "binance-api-reality.toml"
        text = registry.read_text(encoding="utf-8")
        first = text.index("[[endpoint]]")
        second = text.index("[[endpoint]]", first + 1)
        other = tmp_path / "older.toml"
        other.write_text(text[:first] + text[second:], encoding="utf-8")
        code, out, _ = run("api-reality", "diff", str(other), start=repo_root)
        assert code == int(ExitCode.OK)
        assert "endpoint_added" in out

    def test_diff_needs_something_to_compare_against(self, repo_root: Path) -> None:
        """A diff against nothing would compare the registry with itself and agree."""
        code, _, err = run("api-reality", "diff", start=repo_root)
        assert code == int(ExitCode.USAGE)
        assert "needs a snapshot" in err

    def test_an_absent_comparison_is_unmeasured(self, repo_root: Path, tmp_path: Path) -> None:
        """Nothing to compare against establishes nothing, rather than agreement."""
        code, _, err = run("api-reality", "diff", str(tmp_path / "gone.toml"), start=repo_root)
        assert code == int(ExitCode.UNMEASURED)
        assert "unmeasured" in err


class TestUsageText:
    """The group appears where an operator looks for it."""

    def test_the_help_text_names_the_group(self) -> None:
        """A command absent from the usage block is one nobody finds."""
        _, out, _ = run("--help")
        assert "api-reality" in out

    def test_the_help_text_names_every_verb(self) -> None:
        """Seven verbs, each documented where the others are."""
        _, out, _ = run("--help")
        for verb in (
            "show",
            "products",
            "surfaces",
            "environments",
            "capability",
            "verify",
            "diff",
        ):
            assert verb in out
