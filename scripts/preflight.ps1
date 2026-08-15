<#
.SYNOPSIS
    Read-only diagnosis of this host, its CPython and the project environment.

.DESCRIPTION
    Compares the machine against `docs/engineering/runtime-contract.toml` and
    writes the runtime manifest under `.globin/runtime/`.

    This script changes nothing. It creates no directory, installs no package,
    edits no registry key, no PATH, and no execution policy. That is the whole
    point of it being separate from `bootstrap.ps1`: a diagnostic that might also
    repair you is one you cannot safely ask a question of, and a tool that
    reconfigures the machine it is describing has destroyed its own evidence.

    Like `verify.ps1`, this script decides nothing about what is checked. The
    judgement lives in `tools/quality/runtime/plan.py`, where tests can hold it.
    What remains here is genuinely PowerShell's job: finding the repository, and
    choosing which interpreter to ask.

    It prefers the project environment's own interpreter, because that is the one
    the checks actually run under. When there is no environment yet it falls back
    to whatever `python` resolves to and says so — diagnosing a host before it has
    been bootstrapped is exactly when a diagnosis is most useful.

.PARAMETER Interpreter
    The interpreter to run the check with. Defaults to the project environment's
    when it exists, and to `python` when it does not.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/preflight.ps1

.NOTES
    Exit codes, which are the gate's own and are not reinterpreted here:
      0  every check passed
      1  a check failed
      2  the command line was not understood
      3  a check could not be measured, which is never a pass
#>

[CmdletBinding()]
param(
    [string]$Interpreter
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve the repository root from this script's location so the check works
# regardless of the caller's working directory, and on any drive.
$RepoRoot = Split-Path -Parent $PSScriptRoot

# `.venv` is spelled here and declared in `runtime-contract.toml`. That
# duplication is deliberate and is a tripwire rather than a second source:
# `tests/contract/test_runtime_contract.py` compares the two and fails when they
# disagree. PowerShell 5.1 has no TOML reader, and adding one to parse a single
# string would be more machinery than the problem has.
$EnvironmentDirectory = '.venv'
$VenvPython = Join-Path (Join-Path (Join-Path $RepoRoot $EnvironmentDirectory) 'Scripts') 'python.exe'

if ([string]::IsNullOrWhiteSpace($Interpreter)) {
    if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
        $Interpreter = $VenvPython
    }
    else {
        $Interpreter = 'python'
    }
}

Write-Host ''
Write-Host '=== GLOBIN runtime preflight ===' -ForegroundColor White
Write-Host "Repository:  $RepoRoot"
Write-Host "Interpreter: $Interpreter"

if ($Interpreter -eq 'python') {
    Write-Host ''
    Write-Host "No $EnvironmentDirectory interpreter found, so this reports on whichever" -ForegroundColor Yellow
    Write-Host 'Python is on PATH. Run scripts/bootstrap.ps1 to create the environment.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '[1] Runtime contract (python -m tools.quality.runtime check)' -ForegroundColor Cyan
Write-Host ('-' * 70) -ForegroundColor DarkGray

Push-Location $RepoRoot
try {
    & $Interpreter -m tools.quality.runtime check
    $checkExit = $LASTEXITCODE
}
finally {
    Pop-Location
}

Write-Host ''
if ($checkExit -ne 0) {
    Write-Host "FAILED: runtime contract (exit $checkExit)" -ForegroundColor Red
    Write-Host 'See docs/engineering/RUNTIME_BASELINE.md for what each finding means.' -ForegroundColor Red
    exit $checkExit
}

Write-Host 'OK: runtime contract' -ForegroundColor Green
Write-Host ''
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host 'HOST MATCHES THE CONTRACT' -ForegroundColor Green
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host ''
exit 0
