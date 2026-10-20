param(
    [ValidateSet('run', 'setup')]
    [string]$Mode = 'run'
)

$ErrorActionPreference = 'Stop'
$AppDir = $PSScriptRoot
$EnvDir = Join-Path $env:LOCALAPPDATA 'LOUPE\shared-venv'
$EnvPython = Join-Path $EnvDir 'Scripts\python.exe'
$Requirements = Join-Path $AppDir 'requirements.txt'
$Main = Join-Path $AppDir 'main.py'

function Test-PythonCommand([string]$Exe, [string[]]$ExtraArgs = @()) {
    try {
        & $Exe @ExtraArgs '-c' 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 15)' 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    if ($env:LOUPE_BASE_PYTHON) {
        $candidate = $env:LOUPE_BASE_PYTHON.Trim('"')
        if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and (Test-PythonCommand $candidate)) {
            return @{ Exe = $candidate; ExtraArgs = @() }
        }
        Write-Host '[WARNING] LOUPE_BASE_PYTHON is not a usable Python interpreter.'
    }

    foreach ($spec in @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )) {
        if (Get-Command $spec.Exe -ErrorAction SilentlyContinue) {
            if (Test-PythonCommand $spec.Exe $spec.Args) {
                return @{ Exe = $spec.Exe; ExtraArgs = $spec.Args }
            }
        }
    }

    $paths = New-Object 'System.Collections.Generic.List[string]'
    foreach ($version in @('314','313','312','311','310')) {
        if ($env:LOCALAPPDATA) {
            $paths.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"))
        }
        if ($env:ProgramFiles) { $paths.Add((Join-Path $env:ProgramFiles "Python$version\python.exe")) }
        if (${env:ProgramFiles(x86)}) { $paths.Add((Join-Path ${env:ProgramFiles(x86)} "Python$version\python.exe")) }
    }

    # Recover the base interpreter path from earlier LOUPE virtual environments.
    # This checks only sibling folders; it never deletes or modifies prior builds.
    $parent = Split-Path $AppDir -Parent
    if (Test-Path -LiteralPath $parent) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue)) {
            $cfg = Join-Path $dir.FullName '.venv\pyvenv.cfg'
            if (Test-Path -LiteralPath $cfg) {
                foreach ($line in @(Get-Content -LiteralPath $cfg -ErrorAction SilentlyContinue)) {
                    if ($line -match '^home\s*=\s*(.+?)\s*$') {
                        $base = $Matches[1].Trim('"')
                        $paths.Add((Join-Path $base 'python.exe'))
                    }
                    if ($line -match '^executable\s*=\s*(.+?)\s*$') {
                        $paths.Add($Matches[1].Trim('"'))
                    }
                }
            }
        }
    }

    foreach ($path in $paths) {
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Test-PythonCommand $path)) {
            return @{ Exe = $path; ExtraArgs = @() }
        }
    }
    return $null
}

function Test-Packages {
    if (-not (Test-Path -LiteralPath $EnvPython -PathType Leaf)) { return $false }
    try {
        & $EnvPython '-c' 'import PySide6, pyqtgraph, numpy, tifffile' 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA environment variable is missing.' }
    if (-not (Test-Path -LiteralPath $Requirements)) { throw "Cannot find requirements.txt: $Requirements" }
    if (-not (Test-Path -LiteralPath $Main)) { throw "Cannot find main.py: $Main" }

    if (-not (Test-Path -LiteralPath $EnvPython -PathType Leaf)) {
        Write-Host '[LOUPE] Finding a base Python installation...'
        $base = Find-Python
        if ($null -eq $base) {
            Write-Host '[ERROR] Python 3.10-3.14 was not found on this PC.'
            Write-Host 'Install Python 3.11 or 3.12 (64-bit) and rerun run.bat.'
            Write-Host 'Alternatively set LOUPE_BASE_PYTHON to the full path of python.exe.'
            Write-Host 'Older LOUPE .venv folders have NOT been deleted.'
            exit 2
        }
        $root = Split-Path $EnvDir -Parent
        if (-not (Test-Path -LiteralPath $root)) { New-Item -ItemType Directory -Path $root -Force | Out-Null }
        Write-Host "[LOUPE] Creating ONE shared environment: $EnvDir"
        $args = @() + $base.ExtraArgs + @('-m','venv',$EnvDir)
        & $base.Exe @args
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $EnvPython -PathType Leaf)) {
            throw 'Shared environment creation failed. Check your Python installation.'
        }
    }

    # Routine launch does not run pip when required packages already work.
    if (($Mode -eq 'setup') -or -not (Test-Packages)) {
        Write-Host '[LOUPE] Installing/checking packages in the shared environment...'
        & $EnvPython '-m' 'pip' 'install' '-r' $Requirements
        if ($LASTEXITCODE -ne 0) { throw 'pip install failed. Check network and pip output.' }
        if (-not (Test-Packages)) { throw 'Required packages still cannot be imported.' }
    } else {
        Write-Host '[LOUPE] Reusing shared Python environment (no install).'
    }

    Write-Host "[LOUPE] Python: $EnvPython"
    if ($Mode -eq 'run') {
        & $EnvPython $Main
        if ($LASTEXITCODE -ne 0) { throw "LOUPE exited with code $LASTEXITCODE." }
    } else {
        Write-Host '[LOUPE] Shared environment is ready.'
    }
    exit 0
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)"
    exit 1
}
