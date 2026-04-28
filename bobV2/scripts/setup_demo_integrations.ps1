param(
    [switch]$InstallToBobHome,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$demoPlugins = Join-Path $repoRoot ".bob\\plugins"
$bobHome = if ($env:BOB_HOME) { $env:BOB_HOME } else { Join-Path $HOME ".bob" }
$userPlugins = Join-Path $bobHome "plugins"

Write-Host "Repo-local demo plugins:" $demoPlugins
Write-Host "Repo-local demo MCP servers auto-load when Bob runs from this checkout."

if ($InstallToBobHome) {
    New-Item -ItemType Directory -Force -Path $userPlugins | Out-Null
    Get-ChildItem -Path $demoPlugins -Directory | ForEach-Object {
        $destination = Join-Path $userPlugins $_.Name
        if (Test-Path $destination) {
            Remove-Item -Recurse -Force $destination
        }
        Copy-Item -Recurse -Force $_.FullName $destination
        Write-Host "Installed plugin to user Bob home:" $_.Name
    }
}

if ($Verify) {
    Write-Host "Running plugin listing..."
    & bob.exe plugin list
    Write-Host "Running MCP/skills unit tests..."
    Push-Location $repoRoot
    try {
        & python -m pytest bobV2/tests/unit/test_mcp_and_skills.py -q
    }
    finally {
        Pop-Location
    }
}
