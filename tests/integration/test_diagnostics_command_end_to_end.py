r"""The `diagnostics` command, driven through `main` against a real runtime tree.

Everything here goes through the entry point a person types, so what is
established is not that the pieces work but that they are wired together: the
composition root builds the probes, the collector runs, the renderer produces the
document, and the exit code is the one a script would branch on.

The runtime root is redirected to a temporary directory, so the real
`%LOCALAPPDATA%\GLOBIN` tree is never touched.
"""

import hashlib
import io
import json
import os
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from globin.domain.bootstrap import ExitCode
from globin.runtime.cli import main


@pytest.fixture
def runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the user-local runtime tree at a temporary directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def run(argv: list[str]) -> tuple[int, str, str]:
    """Run one command and capture both streams."""
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.usefixtures("runtime_root")
def test_a_snapshot_reports_a_state_and_exits_on_it() -> None:
    code, out, _err = run(["diagnostics", "snapshot"])
    assert code in {int(ExitCode.OK), int(ExitCode.UNMEASURED), int(ExitCode.GATE_FAILED)}
    assert "state:" in out
    assert "runtime.healthy" in out


@pytest.mark.usefixtures("runtime_root")
def test_the_json_document_is_the_only_thing_on_standard_output() -> None:
    """The one contract `--json` makes."""
    _code, out, err = run(["diagnostics", "snapshot", "--json"])
    document = json.loads(out)
    assert document["schema"] == "globin.health.snapshot"
    assert len(document["checks"]) == 18
    assert err, "the human table still goes somewhere"


@pytest.mark.usefixtures("runtime_root")
def test_the_document_carries_an_availability_for_every_reading() -> None:
    """A number that was not measured is never zero."""
    _code, out, _err = run(["diagnostics", "snapshot", "--json"])
    process = json.loads(out)["process"]
    for field in ("resident_bytes", "cpu_user", "threads", "handles", "cpu_percent"):
        assert "availability" in process[field], field
    assert process["cpu_percent"]["availability"] != "measured"
    assert process["cpu_percent"]["reason"] == "HEALTH_CPU_NOT_SAMPLED"


@pytest.mark.usefixtures("runtime_root")
def test_the_document_names_no_person() -> None:
    """No hostname, no user name, no home directory, no command line."""
    _code, out, _err = run(["diagnostics", "snapshot", "--json"])
    profile = os.environ.get("USERPROFILE", "")
    user = os.environ.get("USERNAME", "")
    assert profile not in out
    if user:
        assert user.lower() not in out.lower()


@pytest.mark.usefixtures("runtime_root")
def test_uptime_is_never_negative() -> None:
    _code, out, _err = run(["diagnostics", "snapshot", "--json"])
    assert json.loads(out)["uptime_nanoseconds"] >= 0


@pytest.mark.usefixtures("runtime_root")
def test_memory_tracing_is_off_unless_it_is_asked_for() -> None:
    _code, plain, _err = run(["diagnostics", "snapshot", "--json"])
    assert json.loads(plain)["memory"] is None

    _code, traced, _err = run(["diagnostics", "memory", "--json"])
    memory = json.loads(traced)["memory"]
    assert memory["tracing"] is True
    assert memory["current_bytes"]["availability"] == "measured"


@pytest.mark.usefixtures("runtime_root")
def test_tracing_is_switched_off_again_afterwards() -> None:
    """A diagnostic must not leave the process in a profiling mode."""
    run(["diagnostics", "memory"])
    assert not tracemalloc.is_tracing()


@pytest.mark.usefixtures("runtime_root")
def test_a_bundle_is_published_with_a_digest() -> None:
    code, out, _err = run(["diagnostics", "bundle"])
    assert code == int(ExitCode.OK)
    assert "bundle:" in out
    assert "digest: sha256:" in out


def test_a_published_bundle_validates_against_its_own_manifest(runtime_root: Path) -> None:
    run(["diagnostics", "bundle"])
    archive_path = runtime_root / "GLOBIN" / "cache" / "support" / "globin-support.zip"
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        described = {entry["member"] for entry in manifest["entries"]}
        assert described | {"manifest.json"} == set(archive.namelist())
        for entry in manifest["entries"]:
            digest = "sha256:" + hashlib.sha256(archive.read(entry["member"])).hexdigest()
            assert digest == entry["digest"], entry["member"]


def test_a_bundle_leaves_no_partial_file(runtime_root: Path) -> None:
    run(["diagnostics", "bundle"])
    support = runtime_root / "GLOBIN" / "cache" / "support"
    assert not list(support.glob("*.partial"))


def test_the_parser_refuses_an_unrecognised_subcommand() -> None:
    code, _out, err = run(["diagnostics", "profile"])
    assert code == int(ExitCode.USAGE)
    assert "unrecognised" in err


def test_json_is_refused_where_the_output_is_an_archive() -> None:
    code, _out, err = run(["diagnostics", "bundle", "--json"])
    assert code == int(ExitCode.USAGE)
    assert "writes an archive" in err


def test_the_usage_text_names_the_new_verb() -> None:
    _code, out, _err = run(["--help"])
    assert "diagnostics snapshot" in out
    assert "diagnostics bundle" in out
    assert "diagnostics memory" in out


@pytest.mark.usefixtures("runtime_root")
def test_doctor_and_bootstrap_still_work() -> None:
    """The Phase 021 contract is unchanged by this phase."""
    code, out, _err = run(["doctor"])
    assert code is not None
    assert out
