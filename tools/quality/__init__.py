"""The single quality entrypoint shared by the developer, pre-commit and CI.

There is one definition of what "the checks passed" means, and it lives in
:mod:`tools.quality.commands`. ``scripts/verify.ps1`` calls this, the pre-commit
hook calls this, and the GitHub Actions workflow calls this, so none of the
three can quietly diverge from the others.

Run it as a module:

```bash
python -m tools.quality full
```
"""

from tools.quality.commands import COMMANDS, Command, Step, command_names, find
from tools.quality.runner import EXIT_TOOL_MISSING, EXIT_USAGE, missing_modules, run

__all__ = [
    "COMMANDS",
    "EXIT_TOOL_MISSING",
    "EXIT_USAGE",
    "Command",
    "Step",
    "command_names",
    "find",
    "missing_modules",
    "run",
]
