<#
.SYNOPSIS
    The single verification gate for GLOBIN.

.DESCRIPTION
    Runs every check that must pass before a commit: import, tests, lint,
    formatting and strict type checking, then reports working-tree state.

    Because GLOBIN uses a master-only workflow with no pull request and no
    reviewer (ADR-0005), this script is the gate. Run it before staging, not
    after committing.

    Fails fast: the first failing check stops the run and sets a non-zero exit
    code, so it is safe to use in a chain.

.PARAMETER SkipGit
    Skip the working-tree inspection. Useful when running outside a repository.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipGit
)

$ErrorActionPreference = 'Stop'

# Resolve the repository root from this script's location so the gate works
# regardless of the caller's working directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Tests and the import check read the package straight from src/ — Phase 1
# performs no build and requires no install.
$env:PYTHONPATH = 'src'

$script:StepNumber = 0
$script:Failures = @()

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    $script:StepNumber++
    Write-Host ''
    Write-Host "[$script:StepNumber] $Name" -ForegroundColor Cyan
    Write-Host ('-' * 70) -ForegroundColor DarkGray

    & $Action
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        $script:Failures += $Name
        Write-Host "FAILED: $Name (exit $exitCode)" -ForegroundColor Red
        Write-Host ''
        Write-Host 'Verification stopped. Do not commit until this passes.' -ForegroundColor Red
        exit 1
    }

    Write-Host "OK: $Name" -ForegroundColor Green
}

Write-Host ''
Write-Host '=== GLOBIN verification gate ===' -ForegroundColor White
Write-Host "Repository: $RepoRoot"
Write-Host "Python:     $(python --version 2>&1)"

Invoke-Step 'Package import' {
    python -c "import globin; print(f'globin {globin.__version__} - {globin.PROJECT_NAME} - {globin.EXCHANGE_SCOPE}')"
}

Invoke-Step 'Tests (pytest)' {
    python -m pytest -q --cov=globin --cov-report=term-missing
}

Invoke-Step 'Lint (ruff check)' {
    python -m ruff check .
}

Invoke-Step 'Format verification (ruff format --check)' {
    python -m ruff format --check .
}

Invoke-Step 'Static typing (mypy --strict)' {
    python -m mypy src/globin tests
}

if (-not $SkipGit) {
    Invoke-Step 'Working tree status' {
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
                $global:LASTEXITCODE = 1
                return
            }

            $branch = $branch.Trim()
            Write-Host "Branch: $branch"

            if ($branch -ne 'master') {
                Write-Host "Expected branch 'master' but found '$branch'." -ForegroundColor Red
                Write-Host 'GLOBIN is a master-only project. See docs/GIT_WORKFLOW.md.' -ForegroundColor Red
                $global:LASTEXITCODE = 1
                return
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

            $global:LASTEXITCODE = 0
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
    }
}

Write-Host ''
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host 'ALL CHECKS PASSED' -ForegroundColor Green
Write-Host ('=' * 70) -ForegroundColor Green
Write-Host ''
exit 0
