"""Run the mutation gate: build a sandbox, mutate one site at a time, compare.

Reached as ``python -m tools.quality.mutation``, which is what the ``mutation``
entry in ``tools/quality/commands.py`` launches.

:func:`run` takes the repository root and the way to start a child process as
arguments rather than reading them from the module. That is what lets the two
control runs below — the ones this design exists for — be tested against a
miniature repository and a hand-written child, instead of shipping unexercised.

The order of what happens is the design. Two control runs precede every verdict,
and both exist to make a specific silent failure impossible:

1. **The unmutated subset must pass.** Otherwise there is nothing to measure, and
   every mutant would be reported killed by a test that was already failing.
2. **A deliberately broken module must fail.** If replacing the target with
   ``raise ImportError`` still leaves the subset passing, the sandbox is not
   being imported — the real module is — and every mutant would be reported as
   surviving. That is the failure this whole design is shaped around, so it is
   checked rather than assumed.

Only then does the run mutate anything. Exit codes distinguish the three states
``docs/engineering/QUALITY_GATES.md`` allows: passed, failed, and not run.
"""

import os
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Final

from tools.quality.mutation import baseline as baseline_module
from tools.quality.mutation import operators, plan, sandbox
from tools.quality.mutation.plan import (
    Configuration,
    MutationConfigurationError,
    Target,
    Verdict,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_USAGE: Final[int] = 2

#: Neither passed nor failed. `QUALITY_GATES.md` names three states and insists
#: "not run" never reports as "passed"; this is that third state.
EXIT_UNMEASURED: Final[int] = 3

#: What replaces a target module to prove the sandbox is the one being imported.
CANARY_SOURCE: Final[str] = 'raise ImportError("globin mutation sandbox canary")\n'


def run(repo_root: Path, *, run_process: sandbox.ProcessRunner = sandbox.spawn) -> int:
    """Run the gate against a repository and return the exit code.

    Args:
        repo_root: What to measure.
        run_process: How to start a child. Injectable so that the control runs
            below can be exercised without a real pytest.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_GATE_FAILED`, :data:`EXIT_USAGE` or
        :data:`EXIT_UNMEASURED`.
    """
    try:
        configuration = plan.read_configuration(
            tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        )
    except (MutationConfigurationError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"mutation: {error}", file=sys.stderr)
        return EXIT_USAGE

    missing = plan.validate(configuration, repo_root)
    if missing:
        for line in missing:
            print(f"mutation: {line}", file=sys.stderr)
        return EXIT_USAGE

    try:
        expectations = baseline_module.load(
            tomllib.loads((repo_root / configuration.baseline).read_text(encoding="utf-8"))
        )
    except (MutationConfigurationError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"mutation: {configuration.baseline}: {error}", file=sys.stderr)
        return EXIT_USAGE

    with tempfile.TemporaryDirectory(
        prefix="globin-mutation-", ignore_cleanup_errors=True
    ) as scratch:
        root = Path(scratch)
        sandbox.build(repo_root, configuration.sandbox, root)
        return _measure(configuration, expectations, root, repo_root, run_process)


def _measure(
    configuration: Configuration,
    expectations: dict[str, baseline_module.Expectation],
    root: Path,
    repo_root: Path,
    run_process: sandbox.ProcessRunner,
) -> int:
    """Run every target and compare the result against the baseline."""
    environment = plan.child_environment(dict(os.environ))
    failures: list[str] = []
    suggestions: list[str] = []

    for target in configuration.targets:
        outcome = _measure_target(target, configuration, root, repo_root, environment, run_process)
        if isinstance(outcome, int):
            return outcome
        survivors, examined = outcome
        print(
            f"  {target.module}: {examined - len(survivors)}/{examined} killed, "
            f"{len(survivors)} survived"
        )
        disagreement = baseline_module.compare(target.module, survivors, expectations)
        if disagreement:
            failures.extend(disagreement)
            suggestions.append(baseline_module.render(target.module, survivors))

    if not failures:
        print("mutation: the baseline still describes this tree.")
        return EXIT_OK

    print(file=sys.stderr)
    print(
        f"mutation: {configuration.baseline} no longer describes this tree.",
        file=sys.stderr,
    )
    for line in failures:
        print(line, file=sys.stderr)
    print(
        "\nNothing was written. This tool has no --update: the standard library reads"
        "\nTOML and does not write it, and a baseline a machine can refresh is a"
        "\nbaseline nobody reads. Edit it by hand. What this run would describe:\n",
        file=sys.stderr,
    )
    for block in suggestions:
        print(block, file=sys.stderr)
    return EXIT_GATE_FAILED


def _measure_target(
    target: Target,
    configuration: Configuration,
    root: Path,
    repo_root: Path,
    environment: dict[str, str],
    run_process: sandbox.ProcessRunner,
) -> tuple[frozenset[str], int] | int:
    """Measure one target, or return an exit code if it could not be measured."""
    original = (repo_root / target.module).read_text(encoding="utf-8")
    argv = (plan.interpreter(), *plan.child_argv(target.tests))

    control = sandbox.run_subset(
        argv,
        sandbox=root,
        env=environment,
        timeout=float(configuration.timeout_floor_seconds),
        run_process=run_process,
    )
    if plan.classify(control.exit_code, timed_out=control.timed_out) is not Verdict.SURVIVED:
        print(
            f"mutation: the subset for {target.module} does not pass on the unmutated tree"
            f" (exit {control.exit_code}); there is nothing to measure.",
            file=sys.stderr,
        )
        print(control.output.decode("utf-8", errors="replace"), file=sys.stderr)
        return EXIT_UNMEASURED

    budget = plan.timeout_seconds(control.seconds, configuration)

    sandbox.write_module(root, target.module, CANARY_SOURCE)
    canary = sandbox.run_subset(
        argv, sandbox=root, env=environment, timeout=budget, run_process=run_process
    )
    if plan.classify(canary.exit_code, timed_out=canary.timed_out) is not Verdict.KILLED:
        print(
            f"mutation: the sandbox is not being imported for {target.module}.\n"
            f"  The unmutated subset passed, and so did one whose module was replaced by\n"
            f"  `raise ImportError`. Every mutant would be reported as surviving and the\n"
            f"  score would be a lie. Check `pythonpath` in the sandbox pyproject.toml.",
            file=sys.stderr,
        )
        return EXIT_UNMEASURED

    sites = operators.sites(original)
    survivors: set[str] = set()
    for site in sites:
        sandbox.write_module(root, target.module, operators.apply(original, site.identity))
        result = sandbox.run_subset(
            argv, sandbox=root, env=environment, timeout=budget, run_process=run_process
        )
        verdict = plan.classify(result.exit_code, timed_out=result.timed_out)
        if verdict is Verdict.SURVIVED:
            survivors.add(site.identity)
        elif verdict is not Verdict.KILLED:
            print(
                f"mutation: {target.module} mutant {site.identity} was not measured"
                f" ({verdict}, exit {result.exit_code}).",
                file=sys.stderr,
            )
            print(result.output.decode("utf-8", errors="replace"), file=sys.stderr)
            return EXIT_UNMEASURED

    sandbox.write_module(root, target.module, original)
    return frozenset(survivors), len(sites)
