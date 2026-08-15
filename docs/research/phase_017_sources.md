# Phase 017 — Source Ledger

Windows Host and CPython Runtime Baseline; the interpreter contract, the project
virtual environment and its bootstrap.

Every claim Phase 017 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). Where a source was *probed* rather
than read, the request and the response are written out, on the pattern Phases
014, 015 and 016 established: "the host has X" is a claim, and a quoted command
output is evidence.

This phase probes more than it reads, because most of what it needed to know is a
fact about one machine rather than a fact about a specification. Three entries
below record a **documentation gap** — something this phase needed and could not
find written down where it looked. S-05 is the sharpest: it corrects an assumption
the phase brief itself carried.

---

### S-01 — Python 3.14 is a supported release, and 3.15 is not yet one

- **Canonical location:** Python Developer's Guide, *Status of Python versions* —
  `https://devguide.python.org/versions/`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the CPython project's own status table.
- **Supports:** The table lists `3.14` as **bugfix**, first released 2025-10-07,
  end of life 2030-10. `3.13` is also bugfix; `3.12`, `3.11` and `3.10` are
  security-only. `3.15` is listed as **prerelease**, first release 2026-10-01.
- **Implication for GLOBIN:** Targeting the 3.14 line targets a release that still
  receives bug fixes, not only security fixes, for four more years.
  `runtime-contract.toml` therefore names `minor_line = "3.14"` exactly rather
  than as a floor: 3.15 is not a supported release today, and the day it becomes
  one is a day to run the gates and decide rather than to have already accepted
  it silently.

### S-02 — CPython 3.14.7 exists and is the current maintenance release

- **Canonical location:** Python.org, *Python 3.14.7* release page —
  `https://www.python.org/downloads/release/python-3147/`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** Released **Aug. 5, 2026**, described as "the seventh maintenance
  release of 3.14, containing around 499 bugfixes, build improvements and
  documentation changes from 86 contributors since 3.14.6". Windows installers
  are published for 64-bit (recommended), 32-bit, and ARM64 (marked
  experimental), each with SHA-256 checksums and Sigstore signatures.
- **Implication for GLOBIN:** The contract's floor is `3.14.5` rather than
  `3.14.7`, and 3.14.7 passes it. The floor names the oldest patch this tree has
  actually been verified on, which is the patch installed on the development host
  (S-04). Recording that 3.14.7 exists matters because it is what a reader would
  otherwise assume the floor should have been; the reasoning for a floor rather
  than an exact pin is in
  [ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md).
  The ARM64 installer being marked experimental is a second reason
  `architecture = "AMD64"` is stated rather than inferred.

### S-03 — Probe: this host runs CPython 3.14.5, 64-bit, with the GIL enabled

- **Canonical location:** The development host's interpreter, read directly.
  Documentation for the attributes consulted:
  `https://docs.python.org/3/library/sys.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the machine reporting its own state.
- **Supports:** `python -c "import sys; print(sys.version)"` printed
  `3.14.5 (tags/v3.14.5:5607950, May 10 2026, 10:43:50) [MSC v.1944 64 bit (AMD64)]`.
  `sys.version_info` reported `releaselevel='final'`; `struct.calcsize('P')*8`
  reported `64`; `platform.machine()` reported `AMD64`;
  `sysconfig.get_config_var('Py_GIL_DISABLED')` reported `0`;
  `platform.win32_ver()` reported `('11', '10.0.26200', 'SP0', 'Multiprocessor Free')`.
- **Implication for GLOBIN:** This is the interpreter every Phase 001-017 gate has
  actually run under, and it is what `minimum_patch = "3.14.5"` records. It is a
  final release, not a prerelease; a default build, not free-threaded; and 64-bit
  on AMD64 — which is why the contract can require all three without failing on
  the machine that wrote it.

### S-04 — Probe: `pip` on this host belongs to the user, not to the project

- **Canonical location:** The development host's `pip`, read directly.
  Documentation for the user-site directory this revealed:
  `https://docs.python.org/3/library/site.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `python -m pip --version` printed
  `pip 26.1.2 from C:\Users\<account>\AppData\Roaming\Python\Python314\site-packages\pip (python 3.14)`.
  `where python` listed **two** interpreters — `C:\Python314\python.exe` and one
  under `AppData\Local\Programs\Python\Python312` — and `where py` listed **two**
  launchers.
- **Implication for GLOBIN:** This is the defect Phase 017 exists to remove.
  Before this phase, `pip install` run in this repository's directory would have
  written into a directory shared with every other project on the machine, and
  "the tests passed" named neither of the two interpreters on `PATH`. The
  `pip_origin` finding and the `RUNTIME_PIP_FOREIGN` reason code both come from
  this observation, and the first run of the new gate reported exactly it. The
  account name is redacted here and is never written into
  `.globin/runtime/runtime-manifest.json`, which records outside-repository paths
  as fingerprints only.

### S-05 — The Python install manager matches tags by prefix, so an exact patch tag is possible but undocumented in examples

- **Canonical location:** *Python on Windows* — `https://docs.python.org/3/using/windows.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** On matching: "The Tag is matched on either the full string, or a
  prefix, provided the next character is a dot or a hyphen. This allows `-V:3.1`
  to match `3.1-32`, but not `3.10`. Tags are sorted using numerical ordering
  (`3.10` is newer than `3.1`), but are compared using text (`-V:3.01` does not
  match `3.1`)." On installation: "One or more tags may be specified... **Ranges
  are not supported for installation.**" `py list` accepts
  `--format=<FMT>` with `table`, `csv`, `json`, `jsonl`, `exe` and `prefix`.
- **Gap recorded:** Every worked example in the documentation uses a two-component
  tag (`py install 3.14`, `py -V:3.14`, `py -V:3.14t`, `py -V:3.14-64`). None
  shows a three-component one, and the page does not state whether the CPython
  team publishes per-patch tags to the online index.
- **Implication for GLOBIN:** The phase brief proposed `py -V:3.14.7 -m venv .venv`.
  The prefix rule does not forbid that spelling, but nothing in the documentation
  establishes that a `3.14.7` tag exists to be matched, and this host cannot test
  it (S-06). GLOBIN therefore does not build its environment through a version
  tag at all: `bootstrap.ps1` uses the interpreter it was given, and the gate
  verifies that interpreter against the contract *before* creating anything. A
  check of the real interpreter is stronger evidence than a tag that selected it,
  and it works on a host with no manager.

### S-06 — Probe: this host has the legacy launcher, not the Python install manager

- **Canonical location:** The development host's `py.exe`, read directly.
  Documentation for the distinction: `https://docs.python.org/3/using/windows.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `py list` printed
  `WARNING: The 'list' command is unavailable because this is the legacy py.exe command.`
  followed by `If you have already installed the Python install manager, open Installed Apps and remove 'Python Launcher' to enable the new py.exe command.`
  `where pymanager` printed `INFO: Could not find files for the given pattern(s).`
  `py -0p` **did** work, printing:

  ```text
   -V:3.14 *        C:\Python314\python.exe
   -V:3.12          C:\Users\<account>\AppData\Local\Programs\Python\Python312\python.exe
  ```

  `py -V:3.14 -c "import sys; print(sys.version)"` also worked, printing 3.14.5.
- **Implication for GLOBIN:** `py install` is unavailable here, so
  `--install-python` cannot install anything on this host and says so rather than
  failing silently — a recorded state under
  [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md).
  Enabling the manager requires uninstalling "Python Launcher" from *Installed
  apps*, which is a change to the machine that this phase does not make and
  documents instead. The `-0p` output above is the only specification available
  for the legacy listing format, and is what `LEGACY_RUNTIME_RE` in
  `tools/quality/runtime/plan.py` was written against — the documentation covers
  the manager, which prints something else.

### S-07 — A virtual environment is not movable, and `pyvenv.cfg` records what created it

- **Canonical location:** *venv — Creation of virtual environments* —
  `https://docs.python.org/3/library/venv.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "Not considered as movable or copyable – you just recreate the
  same environment in the target location." And: "Because scripts installed in
  environments should not expect the environment to be activated, their shebang
  lines contain the absolute paths to their environment's interpreters. Because of
  this, environments are inherently non-portable, in the general case... If you
  move an environment because you moved a parent directory of it, you should
  recreate the environment in its new location." `pyvenv.cfg` is documented to
  carry `home` and `include-system-site-packages`. On Windows, copies rather than
  symlinks are the default, and the page warns that symlinks "are not recommended"
  there. To detect a virtual environment: "`if sys.prefix != sys.base_prefix`".
- **Implication for GLOBIN:** This is the basis of the stale-and-moved detection.
  Because a moved environment still *runs* and fails only in its console scripts,
  it is exactly the failure that does not announce itself, and the contract treats
  it as a finding rather than trusting the directory. `--copies` is not passed to
  `venv` because copies are already the Windows default. The `sys.prefix !=
  sys.base_prefix` test is what `_interpreter_is_environment` uses.

### S-08 — Probe: CPython 3.14 writes five keys into `pyvenv.cfg`, including the full patch version

- **Canonical location:** `C:\Python314\Lib\venv\__init__.py` on this host, read
  directly. The module's documentation: `https://docs.python.org/3/library/venv.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary — the implementation that writes the file.
- **Supports:** Lines 229-264 write, in order, `home`,
  `include-system-site-packages`, `version = %d.%d.%d` from `sys.version_info[:3]`,
  an optional `prompt`, `executable` from `os.path.realpath(sys.executable)`, and
  `command`. Line 288-299 define `create_git_ignore_file`, which writes a
  `.gitignore` containing `*` into the environment directory unless
  `--without-scm-ignore-files` is passed. Reading the real file after bootstrap
  confirmed `include-system-site-packages = false` and `version = 3.14.5`.
- **Gap recorded:** The published documentation lists only `home` and
  `include-system-site-packages`. `version`, `executable` and `command` are written
  by every supported CPython and documented by none of them.
- **Implication for GLOBIN:** `version` carries the **full three-component patch**
  of the creating interpreter, which makes an exact-patch check on an environment a
  file read rather than a process launch — the single fact that lets
  `python -m tools.quality runtime` stay fast and offline. Because the key is
  undocumented, the gate treats its absence as a finding rather than as a default,
  and a value it cannot parse as a finding rather than as a pass. The self-ignoring
  `.gitignore` is a second layer beneath `.gitignore`'s own `.venv/` entry, not a
  replacement for it.

### S-09 — pip reads three configuration scopes on Windows, and the environment can override all of them

- **Canonical location:** *pip — Configuration* —
  `https://pip.pypa.io/en/stable/topics/configuration/`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** On Windows the locations are global `C:\ProgramData\pip\pip.ini`,
  user `%APPDATA%\pip\pip.ini` with legacy support for `%HOME%\pip\pip.ini`, and
  site `%VIRTUAL_ENV%\pip.ini` or the installation root when no environment is
  active. Environment variables take the form `PIP_<UPPER_LONG_NAME>` with dashes
  replaced by underscores, so `--index-url` becomes `PIP_INDEX_URL`. Precedence:
  "Command line options override environment variables, which override the values
  in a configuration file."
- **Gap recorded:** The page documents `pip config debug` only as a way to
  "identify exact paths"; it does not state what the command prints, and carries no
  warning that its output can contain credentials embedded in an index URL.
- **Implication for GLOBIN:** The gate computes these four candidate locations
  itself and records **only the scope and whether the file exists** — never the
  path, which on a user scope carries the account name, and never a value.
  `pip config debug` is deliberately not run: a gate that captured a credential in
  order to report that a credential exists has already lost. `PIP_*` variables are
  recorded by name alone, because the name establishes that an override is in force
  and the value is the part worth not publishing. On this host all four files were
  absent and no `PIP_*` variable was set.

### S-10 — Long paths are an operating-system setting, and enabling one requires administrator rights

- **Canonical location:** *Python on Windows*, "Removing the MAX_PATH Limitation" —
  `https://docs.python.org/3/using/windows.html`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** "Your administrator will need to activate the 'Enable Win32 long
  paths' group policy, or set `LongPathsEnabled` to `1` in the registry key
  `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`." Once done, no
  further Python configuration is required.
- **Implication for GLOBIN:** The gate reads that value and records `enabled`,
  `disabled` or `unmeasured`. **On this host it is `disabled`**, and Phase 017 does
  not change it: it is a machine-wide change requiring elevation, and nothing in
  GLOBIN needs long paths yet. Recording it now means the phase that first writes a
  deep artefact tree inherits the fact rather than discovering it.

### S-11 — Probe: PowerShell on this host runs local unsigned scripts

- **Canonical location:** The development host's execution policy, read directly.
  Microsoft's documentation for the policies:
  `https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies`
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `Get-ExecutionPolicy -List` reported `CurrentUser: RemoteSigned`
  with `MachinePolicy`, `UserPolicy`, `Process` and `LocalMachine` all `Undefined`.
- **Implication for GLOBIN:** `RemoteSigned` permits a locally authored script to
  run unsigned, so `scripts/*.ps1` execute here without the documented
  `-ExecutionPolicy Bypass` — which the repository passes anyway, and which is why
  it works on a host with a stricter policy. Phase 017 does not change the policy;
  where a policy blocks a script the documentation names the official remedy
  instead. This also confirms nothing in this phase depends on code signing, which
  matters because `MEMORY.md` records that this host holds no signing key of any
  kind.

### S-12 — PyTorch supports Python 3.14 and requires Windows 10 or newer

- **Canonical location:** PyTorch, *Get Started Locally* —
  `https://pytorch.org/get-started/locally/`; version support tracked in
  `https://github.com/pytorch/pytorch/issues/156856`
- **Accessed:** 2026-08-15
- **Authority:** Primary for the install matrix; the linked issue is the project's
  own tracking issue for 3.14 support.
- **Supports:** Builds are stated to be compatible with Windows 10 or newer, and
  the current stable release requires Python 3.10 or later. Python 3.14 support,
  including `torch.compile`, landed in PyTorch 2.10; the free-threaded build
  (`3.14t`) is described as experimentally supported.
- **Implication for GLOBIN:** Two things. The Windows 10 floor in
  `runtime-contract.toml` matches the strictest floor among the planned stack
  rather than being chosen arbitrarily. And the 3.14 line is not a dead end for the
  machine-learning band, which is what would have forced the controlled fallback to
  3.13 the phase brief contemplated — no such fallback was needed.
  **This is not the wheel-availability survey.** PyTorch is one library of several
  (XGBoost, Optuna, Gymnasium, Stable-Baselines3, LightGBM), and checking the
  rest against the pinned interpreter is Phase 018's, per
  [ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md).
