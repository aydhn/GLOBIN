"""The committed record of which mutants are known to survive, and why.

A mutation score on its own is a number that drifts. What this file compares is
the **set of survivors**, in both directions:

* a survivor the baseline does not expect is a gap nobody has argued for, and
  fails the gate;
* a recorded survivor this run killed is a stale claim, and also fails — for the
  same reason ``xfail_strict = true`` is set in ``pyproject.toml``. A test that
  unexpectedly passes is news, not a curiosity, and leaving the old note in place
  turns the file into folklore.

The total number of mutants is deliberately **not** pinned. Adding a branch that
the tests already cover produces new mutants that are immediately killed, and
failing the build for that would be friction with nothing behind it. Adding a
branch nothing covers produces a survivor, and that is caught by the rule above.

Nothing writes this file. The standard library reads TOML and does not write it,
so the harness physically cannot refresh a baseline, and does not pretend to: on
disagreement it prints the block it would have written for a person to read,
judge and paste. A baseline a machine can update is a baseline nobody reads.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from tools.quality.mutation.plan import MutationConfigurationError

#: The shortest a reason may be. A survivor without an argument is a test gap
#: nobody has defended, and "equivalent mutant" on its own is not an argument.
MIN_REASON_LENGTH: Final[int] = 40

#: What the suggested block puts where a reason belongs, so that pasting it
#: without reading fails the contract test rather than passing the gate.
REASON_PLACEHOLDER: Final[str] = "REPLACE THIS"


@dataclass(frozen=True, slots=True)
class Expectation:
    """What the baseline says about one module.

    Args:
        module: Repository-relative path.
        survivors: Identity mapped to the argument for keeping it.
    """

    module: str
    survivors: Mapping[str, str]


def load(document: Mapping[str, object]) -> dict[str, Expectation]:
    """Read a parsed baseline.

    Args:
        document: The parsed TOML.

    Returns:
        One :class:`Expectation` per module, keyed by module path.

    Raises:
        MutationConfigurationError: If a target declares no module, or a
            survivor declares no identity or no reason.
    """
    entries = document.get("target", [])
    if not isinstance(entries, list):
        msg = "the baseline's `target` must be a list of tables"
        raise MutationConfigurationError(msg)

    expectations: dict[str, Expectation] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            msg = "every baseline target must be a table"
            raise MutationConfigurationError(msg)
        module = entry.get("module")
        if not isinstance(module, str):
            msg = "a baseline target declares no module"
            raise MutationConfigurationError(msg)
        expectations[module] = Expectation(module=module, survivors=_survivors(entry, module))
    return expectations


def _survivors(entry: Mapping[str, object], module: str) -> dict[str, str]:
    """Read one target's survivor list."""
    raw = entry.get("survivor", [])
    if not isinstance(raw, list):
        msg = f"{module}: `survivor` must be a list of tables"
        raise MutationConfigurationError(msg)

    survivors: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            msg = f"{module}: every survivor must be a table"
            raise MutationConfigurationError(msg)
        identity = item.get("id")
        reason = item.get("reason")
        if not isinstance(identity, str):
            msg = f"{module}: a survivor declares no id"
            raise MutationConfigurationError(msg)
        if not isinstance(reason, str) or not reason.strip():
            msg = f"{module}: survivor {identity!r} declares no reason"
            raise MutationConfigurationError(msg)
        survivors[identity] = reason.strip()
    return survivors


def compare(
    module: str, observed: frozenset[str], expectations: Mapping[str, Expectation]
) -> tuple[str, ...]:
    """Compare one module's survivors against what the baseline expects.

    Args:
        module: Repository-relative path of the mutated module.
        observed: The identities that survived this run.
        expectations: What :func:`load` returned.

    Returns:
        One line per disagreement, empty when the two sets are equal. A module
        absent from the baseline is itself a disagreement: an unrecorded module
        would otherwise be allowed any number of survivors.
    """
    expectation = expectations.get(module)
    if expectation is None:
        if not observed:
            return (f"{module}: not in the baseline. Add a target table for it.",)
        return (
            f"{module}: not in the baseline, and {len(observed)} mutant(s) survived.",
            *(f"    survived, unrecorded: {identity}" for identity in sorted(observed)),
        )

    expected = frozenset(expectation.survivors)
    unrecorded = sorted(observed - expected)
    stale = sorted(expected - observed)

    lines: list[str] = []
    if unrecorded:
        lines.append(
            f"{module}: {len(unrecorded)} mutant(s) survived that the baseline does not expect."
        )
        lines.extend(f"    survived, unrecorded: {identity}" for identity in unrecorded)
        lines.append("    Each is a test to write, or an argument to add to the baseline.")
    if stale:
        lines.append(f"{module}: the baseline expects {len(stale)} survivor(s) this run killed.")
        lines.extend(f"    recorded, now killed: {identity}" for identity in stale)
        lines.append("    The tests improved. Delete these entries in the same commit.")
    return tuple(lines)


def render(module: str, survivors: frozenset[str]) -> str:
    """Render the baseline block this run would describe.

    Args:
        module: Repository-relative path.
        survivors: The identities that survived.

    Returns:
        TOML text, for a person to read and edit. Every reason is
        :data:`REASON_PLACEHOLDER`, which the contract test refuses — so pasting
        this without thinking fails the suite instead of passing the gate.
    """
    lines = ["[[target]]", f'module = "{module}"']
    for identity in sorted(survivors):
        lines.extend(
            [
                "",
                "  [[target.survivor]]",
                f'  id = "{identity}"',
                '  reason = """',
                f"  {REASON_PLACEHOLDER}. Say why this mutant is not a missing test:",
                "  an equivalent mutant, a trivial mutation, or an implementation",
                "  detail nothing should depend on. Name which, and why.",
                '  """',
            ]
        )
    return "\n".join(lines)
