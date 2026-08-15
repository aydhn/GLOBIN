"""The only module here that touches disk or starts a process.

Everything else in this package maps values to values. The separation is the
same one ``tools/quality/mutation`` makes, and for the same reason stated in its
``__init__``: ``tools`` is measured under branch coverage, and a judgement
entangled with a subprocess is tested once and hoped about.

Nothing is written outside the run directory. The four things that would
otherwise leak are each closed at the source rather than cleaned up afterwards:
``.pytest_cache`` by ``-p no:cacheprovider``, ``__pycache__`` by
``PYTHONDONTWRITEBYTECODE``, ``.hypothesis`` by the ``ci`` profile's
``database=None``, and the repository's own ``.coverage`` by giving every child
its own ``COVERAGE_FILE``. That last one matters more than it looks: without it a
shard run would overwrite the coverage data the last ``full`` gate left behind.
"""

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.quality.mutation.sandbox import ProcessRunner, spawn

__all__ = ["ProcessRunner", "prepare", "spawn", "write_args_file"]


def prepare(reports: Path) -> None:
    """Make the run directory, discarding whatever a previous run left.

    Args:
        reports: Where this run writes.

    Only this package's own artefacts are removed, and only from inside the run
    directory. Pruning matters: a four-shard run's leftovers combined into a
    three-shard run would report coverage from tests that did not run this time,
    which is a wrong answer rather than a missing one.
    """
    reports.mkdir(parents=True, exist_ok=True)
    for pattern in ("shard-*.args", "shard-*.coverage*", "serial.coverage*", "combined.coverage*"):
        for stale in reports.glob(pattern):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            else:
                stale.unlink()


def write_args_file(path: Path, node_ids: Sequence[str]) -> None:
    r"""Write one shard's node IDs where pytest can read them.

    Args:
        path: The file to write.
        node_ids: This shard's tests.

    ``pytest @file`` is :mod:`argparse`'s ``fromfile_prefix_chars``, and its
    behaviour decides this function's shape. It splits on
    :meth:`str.splitlines`, and the default line converter returns each line
    **verbatim** — so a blank line becomes an empty positional argument, which
    pytest then treats as a path and refuses. There are therefore no blank
    lines, no comments and no trailing blank. Expansion is also recursive, which
    is why a node ID beginning with ``@`` is refused back in
    :mod:`tools.quality.execution.manifest` rather than here.

    Written with an explicit ``newline="\\n"``: CRLF would survive
    ``splitlines`` intact, but a file this tool writes should not depend on the
    platform that wrote it.
    """
    path.write_text("".join(f"{node_id}\n" for node_id in node_ids), encoding="utf-8", newline="\n")


def run_child(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    run_process: ProcessRunner = spawn,
) -> tuple[int | None, str]:
    """Start one child and wait for it.

    Args:
        argv: Arguments after the interpreter.
        cwd: Where the child runs.
        env: Its environment.
        timeout: How long to wait before giving up.
        run_process: How to start it. Injected so that the timeout path can be
            driven by a double raising immediately, rather than by a test that
            sleeps — ``docs/TESTING_STRATEGY.md`` forbids synchronising a test
            with the clock.

    Returns:
        The exit code and the child's combined output, or ``None`` and an
        explanation if it never returned.
    """
    import subprocess

    try:
        code, output = run_process(argv, cwd=cwd, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"the child did not finish within {timeout:.0f}s"
    return code, output.decode("utf-8", errors="replace")
