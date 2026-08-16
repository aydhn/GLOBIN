<#
.SYNOPSIS
    Create the project virtual environment and install everything it needs.

.DESCRIPTION
    Builds `.venv` at the repository root from a verified interpreter, installs
    the development toolchain recorded in `pylock.dev.toml`, then the runtime
    dependencies recorded in `pylock.toml`, then GLOBIN itself, and finally
    re-runs the read-only check through the new environment so that the manifest
    it leaves behind describes the environment rather than the interpreter that
    built it.

    The three installs are in that order for a reason. GLOBIN is installed with
    `--no-deps`, so everything `project.dependencies` names must already be
    present at the version the lock records; installing it first would let pip
    resolve those against an index and quietly install something else, which is
    the lock being bypassed by the one command whose job is to honour it. It is
    installed editable, so that `globin` and `python -m globin` read one source
    tree rather than a copy taken at install time.

    Installing GLOBIN is what creates the `globin` command. Before Phase 021 this
    script installed only the toolchain and the package was reachable through
    `pythonpath` alone, which is enough for the test suite and not enough for a
    console entry point.

    Idempotent. Run it twice and the second run creates nothing, because the
    environment already satisfies the contract.

    This script writes only inside the repository. It does not edit the registry,
    the machine or user PATH, the PowerShell execution policy, or any interpreter
    outside `.venv`, and it never installs into a global or user site directory.
    Where a host setting is wrong it is reported, with the official remedy, rather
    than changed — see `docs/engineering/RUNTIME_BASELINE.md`.

    Every decision worth getting wrong lives in `tools/quality/runtime/`, where a
    test can hold it. In particular the safety of `-Recreate` is decided by
    `deletion_problems`, which refuses anything that is not exactly `.venv` at the
    repository root, and refuses a link outright. No recursive delete is ever
    composed from a variable in this file.

.PARAMETER Interpreter
    The interpreter to build the environment from. Defaults to `python`. The
    contract is checked against it before anything is created, so pointing this
    at the wrong Python produces a refusal rather than a wrong environment.

.PARAMETER Recreate
    Remove an existing environment before creating it. Refused unless the target
    is exactly the declared environment directory at the repository root and is
    not a symbolic link or junction.

.PARAMETER InstallPython
    Permit installing a missing runtime through the Python install manager. Opt-in
    because installing a runtime changes the host, and a no-op where no manager is
    present — this host has the legacy launcher, which cannot install.

.PARAMETER FromPins
    Install the exact versions `.github/workflows/` pins instead of `pylock.dev.toml`.
    The documented recovery path for a lock that cannot be installed from: `pip`
    labels `install -r pylock.toml` experimental, and this is the one command a
    person runs before they have a working tree. See ADR-0054.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Recreate

.NOTES
    Exit codes, which are the gate's own and are not reinterpreted here:
      0  the environment exists and matches the contract
      1  a check failed, or the environment could not be built
      2  the command line was not understood
      3  a check could not be measured, which is never a pass
#>

[CmdletBinding()]
param(
    [string]$Interpreter = 'python',
    [switch]$Recreate,
    [switch]$InstallPython,
    [switch]$FromPins
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve the repository root from this script's location so bootstrapping works
# regardless of the caller's working directory, and on any drive.
$RepoRoot = Split-Path -Parent $PSScriptRoot

# `.venv` is spelled here and declared in `runtime-contract.toml`. See the same
# note in `preflight.ps1`: the duplication is a tripwire that
# `tests/contract/test_runtime_contract.py` compares, not a second source.
$EnvironmentDirectory = '.venv'
$VenvPython = Join-Path (Join-Path (Join-Path $RepoRoot $EnvironmentDirectory) 'Scripts') 'python.exe'

$arguments = @('-m', 'tools.quality.runtime', 'bootstrap')
if ($Recreate) { $arguments += '--recreate' }
if ($InstallPython) { $arguments += '--install-python' }
if ($FromPins)      { $arguments += '--from-pins' }

Write-Host ''
Write-Host '=== GLOBIN environment bootstrap ===' -ForegroundColor White
Write-Host "Repository:  $RepoRoot"
Write-Host "Interpreter: $Interpreter"
Write-Host "Environment: $EnvironmentDirectory"
if ($Recreate) {
    Write-Host 'Recreate:    yes (an existing environment will be removed first)' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '[1] Build the environment (python -m tools.quality.runtime bootstrap)' -ForegroundColor Cyan
Write-Host ('-' * 70) -ForegroundColor DarkGray

Push-Location $RepoRoot
try {
    & $Interpreter @arguments
    $bootstrapExit = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($bootstrapExit -ne 0) {
    Write-Host ''
    Write-Host "FAILED: bootstrap (exit $bootstrapExit)" -ForegroundColor Red
    Write-Host 'See docs/engineering/RUNTIME_BASELINE.md for what each finding means.' -ForegroundColor Red
    exit $bootstrapExit
}

Write-Host ''
Write-Host 'OK: environment built' -ForegroundColor Green

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host ''
    Write-Host "FAILED: $EnvironmentDirectory has no Scripts\python.exe after bootstrap." -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '[2] Verify through the new environment' -ForegroundColor Cyan
Write-Host ('-' * 70) -ForegroundColor DarkGray

# The manifest that survives is the one written by the environment's own
# interpreter. The bootstrap run above was necessarily performed by the base
# interpreter, and evidence about the wrong interpreter is worse than none.
Push-Location $RepoRoot
try {
    & $VenvPython -m tools.quality.runtime check
    $checkExit = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($checkExit -ne 0) {
    Write-Host ''
    Write-Host "FAILED: runtime contract (exit $checkExit)" -ForegroundColor Red
    exit $checkExit
}

Write-Host ''
Write-Host 'OK: runtime contract' -ForegroundColor Green
Write-Host ''
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host 'ENVIRONMENT READY' -ForegroundColor Green
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host ''
Write-Host 'Automation uses the environment directly and needs no activation:'
Write-Host "  $EnvironmentDirectory\Scripts\python.exe -m tools.quality full"
Write-Host ''
exit 0
