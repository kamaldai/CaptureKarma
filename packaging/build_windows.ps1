#Requires -Version 7
<#
.SYNOPSIS
    Build the self-contained Windows bundle: dist\CaptureKarma\ and a zip beside it.

.DESCRIPTION
    Produces a folder a non-technical user can unzip and double-click: no Python, no uv, no
    `playwright install`, no ffmpeg. Chromium is installed *into the playwright package*
    (PLAYWRIGHT_BROWSERS_PATH=0) so PyInstaller collects it as package data, and the ffmpeg binary
    comes from imageio-ffmpeg. capturekarma\_frozen.py points both at the bundle at runtime.

.EXAMPLE
    pwsh -File packaging\build_windows.ps1
#>
[CmdletBinding()]
param(
    # Skip `uv sync` and the Chromium download (they are slow and idempotent).
    [switch] $SkipDeps,
    # Build the bundle but stop before zipping.
    [switch] $NoZip
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Repo = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Repo 'dist\CaptureKarma'
#: Refuse to zip above this: something has gone wrong with the collection, not with the app.
$MaxZipBytes = 1.5GB

function Step([string] $Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Invoke-Checked([string] $Exe, [string[]] $Arguments) {
    Write-Host "    $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-ProjectVersion {
    $line = Select-String -Path (Join-Path $Repo 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if (-not $line) { throw 'could not read version from pyproject.toml' }
    return $line.Matches[0].Groups[1].Value
}

function Get-DirectorySize([string] $Path) {
    return (Get-ChildItem -LiteralPath $Path -Recurse -File | Measure-Object -Property Length -Sum).Sum
}

function Format-Size([double] $Bytes) { return '{0:N1} MB' -f ($Bytes / 1MB) }

Push-Location $Repo
try {
    if (-not $SkipDeps) {
        Step 'uv sync --group build'
        Invoke-Checked 'uv' @('sync', '--group', 'build')

        # PLAYWRIGHT_BROWSERS_PATH=0 lands Chromium in
        # .venv\Lib\site-packages\playwright\driver\package\.local-browsers, i.e. inside the package
        # PyInstaller collects. --no-shell skips the headless shell: we drive a headed browser.
        Step 'playwright install chromium (into the package, headed only)'
        $env:PLAYWRIGHT_BROWSERS_PATH = '0'
        Invoke-Checked 'uv' @('run', 'playwright', 'install', 'chromium', '--no-shell')
    }

    Step 'pyinstaller packaging/CaptureKarma.spec'
    $env:PLAYWRIGHT_BROWSERS_PATH = '0'
    Invoke-Checked 'uv' @('run', 'pyinstaller', '--noconfirm', '--clean',
        '--workpath', 'packaging/build', '--distpath', 'dist', 'packaging/CaptureKarma.spec')

    if (-not (Test-Path -LiteralPath (Join-Path $Dist 'CaptureKarma.exe'))) {
        throw "PyInstaller produced no CaptureKarma.exe in $Dist"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Dist 'ck.exe'))) {
        throw "PyInstaller produced no ck.exe in $Dist"
    }

    Step 'examples, README, LICENSE, START-HERE.txt'
    $examples = Join-Path $Dist 'examples'
    New-Item -ItemType Directory -Force -Path $examples | Out-Null
    Copy-Item -Path (Join-Path $Repo 'examples\*.yaml') -Destination $examples -Force
    Copy-Item -Path (Join-Path $Repo 'README.md') -Destination $Dist -Force
    Copy-Item -Path (Join-Path $Repo 'LICENSE') -Destination $Dist -Force

    # The repo's web-demo.yaml points at ..\tests\fixtures\page.html so the test suite keeps working
    # from a clone. The bundle has no tests\ dir, so ship the fixture next to the scene and retarget
    # it. A url without a scheme is resolved relative to the scene file (scene/loader.py).
    Copy-Item -Path (Join-Path $Repo 'tests\fixtures\page.html') -Destination (Join-Path $examples 'page.html') -Force
    $demo = Join-Path $examples 'web-demo.yaml'
    $text = (Get-Content -LiteralPath $demo -Raw) -replace 'url:\s*\.\./tests/fixtures/page\.html', 'url: page.html'
    if ($text -notmatch 'url:\s*page\.html') { throw "could not retarget $demo at the bundled page.html" }
    Set-Content -LiteralPath $demo -Value $text -NoNewline -Encoding utf8

    $startHere = @'
CaptureKarma - record a demo once, replay it perfectly, get an MP4.

1. Double-click CaptureKarma.exe (keep the _internal folder next to it).
2. Record web -> type your URL -> perform the demo in the browser -> press F9 to stop.
3. Select the scene in the list -> Play selected. Press F9 to abort a take.
4. Videos land in your Videos\CaptureKarma folder. examples\web-demo.yaml is a scene to try first.
'@
    Set-Content -LiteralPath (Join-Path $Dist 'START-HERE.txt') -Value $startHere -Encoding utf8

    $distBytes = Get-DirectorySize $Dist
    Step "bundle: $Dist  ($(Format-Size $distBytes))"

    if ($NoZip) { Write-Host 'skipping zip (-NoZip)'; return }
    if ($distBytes -gt $MaxZipBytes) {
        throw ("bundle is $(Format-Size $distBytes), over the {0:N1} MB ceiling - refusing to zip; " -f ($MaxZipBytes / 1MB)) +
              'inspect dist\CaptureKarma for something that should not be collected'
    }

    $version = Get-ProjectVersion
    $zip = Join-Path $Repo "dist\CaptureKarma-$version-win64.zip"
    Step "zipping to $zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Dist, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)

    $zipBytes = (Get-Item -LiteralPath $zip).Length
    Write-Host ''
    Write-Host "bundle : $Dist  ($(Format-Size $distBytes))" -ForegroundColor Green
    Write-Host "zip    : $zip  ($(Format-Size $zipBytes))" -ForegroundColor Green
}
finally {
    Pop-Location
}
