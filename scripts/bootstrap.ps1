# Bootstrap: clone all Ennam KG sub-repos listed in scripts/repos.txt.
# Idempotent, best-effort. Re-running is safe.
# Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir   = Split-Path -Parent $scriptDir
$manifest  = Join-Path $scriptDir 'repos.txt'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: git not found on PATH.'; exit 1
}
if (-not (Test-Path -LiteralPath $manifest)) {
    Write-Host "ERROR: manifest not found: $manifest"; exit 1
}

$cloned = 0; $skipped = 0; $failed = 0

foreach ($line in Get-Content -LiteralPath $manifest) {
    $trimmed = $line.Trim()
    if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
    $parts  = $trimmed -split '\s+'
    $dir    = $parts[0]
    $url    = if ($parts.Count -ge 2) { $parts[1] } else { '' }
    $branch = if ($parts.Count -ge 3 -and $parts[2]) { $parts[2] } else { 'main' }

    if ($url -eq '') {
        Write-Host "WARN: bad manifest line for '$dir' (missing url), skipping"
        $failed++; continue
    }
    $target = Join-Path $rootDir $dir

    if (Test-Path -LiteralPath (Join-Path $target '.git')) {
        Write-Host "skip   $dir (already a git repo)"; $skipped++; continue
    }
    if (Test-Path -LiteralPath $target) {
        Write-Host "FAIL   $dir (path exists but is not a git repo; not touching it)"
        $failed++; continue
    }

    Write-Host "clone  $dir <- $url ($branch)"
    & git clone -b $branch $url $target
    if ($LASTEXITCODE -eq 0) {
        $cloned++
    } else {
        Write-Host "FAIL   $dir (git clone failed; check SSH access to GitHub En-Nam org)"
        $failed++
    }
}

Write-Host '----'
Write-Host "summary: cloned=$cloned skipped=$skipped failed=$failed"
if ($failed -gt 0) { exit 1 } else { exit 0 }
