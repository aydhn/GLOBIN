"""Mutation testing for GLOBIN's pure core, using nothing but the standard library.

Coverage answers "did this line run". Mutation testing answers the question that
actually matters: "would anything have noticed if it were different". The two are
separate evidence and this package does not replace the coverage gate — a line
can be executed by a test that asserts nothing, and only one of the two measures
notices.

**Why the repository grows its own.** ``mutmut`` calls :func:`os.fork`, which
Windows does not have; its own documentation says a Windows user must run it
inside WSL, and GLOBIN's declared host and its continuous integration are both
Windows (ADR-0009). ``cosmic-ray`` runs anywhere but brings thirteen transitive
dependencies — ``aiohttp``, ``gitpython`` and ``sqlalchemy`` among them — into a
repository whose ``dependencies = []`` is asserted by a contract test and whose
suite installs a guard against outbound sockets. Reviewing a dependency of that
size is Phase 014's process, and it does not exist yet. What is left is
:mod:`ast` and :mod:`subprocess`, which is enough, adds nothing to the toolchain,
and runs where the project runs.

The package is split by purity, because ``tools`` is measured under branch
coverage: :mod:`~tools.quality.mutation.operators`,
:mod:`~tools.quality.mutation.plan` and :mod:`~tools.quality.mutation.baseline`
are pure functions over syntax trees and mappings, and
:mod:`~tools.quality.mutation.sandbox` is the only module that touches a disk or
a process.
"""

from tools.quality.mutation.baseline import Expectation, compare, load, render
from tools.quality.mutation.operators import MutationSite, apply, sites
from tools.quality.mutation.plan import (
    Configuration,
    Target,
    Verdict,
    child_argv,
    child_environment,
    classify,
    read_configuration,
    timeout_seconds,
    validate,
)
from tools.quality.mutation.sandbox import Outcome, build, run_subset, write_module

__all__ = [
    "Configuration",
    "Expectation",
    "MutationSite",
    "Outcome",
    "Target",
    "Verdict",
    "apply",
    "build",
    "child_argv",
    "child_environment",
    "classify",
    "compare",
    "load",
    "read_configuration",
    "render",
    "run_subset",
    "sites",
    "timeout_seconds",
    "validate",
    "write_module",
]
