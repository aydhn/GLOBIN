<#
.SYNOPSIS
    The single verification gate for GLOBIN.

.DESCRIPTION
    Runs the canonical quality command and then reports working-tree state.

    Since Phase 004 this script does not decide what "the checks" are. The
    command table in `tools/quality/commands.py` does, and CI and the
    pre-commit hook read the same table. What remains here is the part that is
    genuinely PowerShell's job: resolving the repository root, and inspecting
    the branch and working tree afterwards.

    That split is the point. When the gate was a list of commands in this file,
    a check added to CI and not here — or the reverse — was invisible until it
    mattered.

    Because GLOBIN uses a master-only workflow with no pull request and no
    reviewer (ADR-0005), this script is the gate. Run it before staging, not
    after committing.

    Fails fast: the first failing check stops the run and sets a non-zero exit
    code, so it is safe to use in a chain.

.PARAMETER Command
    The quality command to run. Defaults to `full`. Use `fast` for a quick
    inner-loop check; run `python -m tools.quality --help` for the full list.

.PARAMETER SkipGit
    Skip the working-tree inspection. Useful when running outside a repository.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/verify.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -Command fast
#>

[CmdletBinding()]
param(
    [string]$Command = 'full',
    [switch]$SkipGit
)

$ErrorActionPreference = 'Stop'

# Resolve the repository root from this script's location so the gate works
# regardless of the caller's working directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host ''
Write-Host '=== GLOBIN verification gate ===' -ForegroundColor White
Write-Host "Repository: $RepoRoot"
Write-Host "Python:     $(python --version 2>&1)"
Write-Host "Command:    $Command"

Write-Host ''
Write-Host "[1] Quality gate (python -m tools.quality $Command)" -ForegroundColor Cyan
Write-Host ('-' * 70) -ForegroundColor DarkGray

python -m tools.quality $Command
$qualityExit = $LASTEXITCODE

if ($qualityExit -ne 0) {
    Write-Host ''
    Write-Host "FAILED: quality gate (exit $qualityExit)" -ForegroundColor Red
    Write-Host 'Verification stopped. Do not commit until this passes.' -ForegroundColor Red
    exit $qualityExit
}

Write-Host ''
Write-Host 'OK: quality gate' -ForegroundColor Green

if (-not $SkipGit) {
    Write-Host ''
    Write-Host '[2] Working tree status' -ForegroundColor Cyan
    Write-Host ('-' * 70) -ForegroundColor DarkGray

    # Windows PowerShell 5.1 turns a native command's stderr into an
    # ErrorRecord, which combined with $ErrorActionPreference='Stop' would
    # abort this script the first time git writes an informational message
    # (for example before the repository has any commits). Relax the
    # preference for the duration of the git calls, and never redirect
    # their stderr.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # `symbolic-ref` reports the branch whether or not any commit
        # exists yet; `rev-parse HEAD` cannot, because HEAD has no target
        # before the first commit.
        $branch = git symbolic-ref --short HEAD
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
            Write-Host 'HEAD is detached or could not be read.' -ForegroundColor Red
            Write-Host 'GLOBIN work must happen on master. See docs/GIT_WORKFLOW.md.' -ForegroundColor Red
            exit 1
        }

        $branch = $branch.Trim()
        Write-Host "Branch: $branch"

        if ($branch -ne 'master') {
            Write-Host "Expected branch 'master' but found '$branch'." -ForegroundColor Red
            Write-Host 'GLOBIN is a master-only project. See docs/GIT_WORKFLOW.md.' -ForegroundColor Red
            exit 1
        }

        $porcelain = @(git status --porcelain)
        if ($porcelain.Count -gt 0) {
            Write-Host "Uncommitted or untracked entries: $($porcelain.Count)" -ForegroundColor Yellow
            $porcelain | Select-Object -First 20 | ForEach-Object {
                Write-Host "  $_" -ForegroundColor Yellow
            }
            if ($porcelain.Count -gt 20) {
                Write-Host "  ... and $($porcelain.Count - 20) more" -ForegroundColor Yellow
            }
            Write-Host ''
            Write-Host 'Expected mid-phase. Must be empty once the phase is committed.'
        }
        else {
            Write-Host 'Working tree is clean.'
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    Write-Host 'OK: working tree status' -ForegroundColor Green
}

Write-Host ''
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host 'ALL CHECKS PASSED' -ForegroundColor Green
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host ''
exit 0
