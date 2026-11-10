<#
.SYNOPSIS
  Python 3.14 compatibility test for the Aries 3D Digital Passport backend (SQL Server). Run on the Windows Server.

.DESCRIPTION
  Stage 1 (always): creates an ISOLATED virtual environment inside this package folder (.venv-py314) from the server's
  Python 3.14 - the system Python is never modified - installs the 63 pinned wheels offline, and runs the dependency
  and component checks (imports, exact versions, ODBC Driver 18, Django checks, Waitress, CAD STEP->GLB, VTK, PDF, Node).
  No database connection is made in stage 1.

  Stage 2 (only with -RunDatabaseTests): runs the backend regression suite (449 tests) against a SEPARATE, explicitly named
  SQL Server TEST database. Refuses DigitalPassport, any name without "test", a sysadmin login, a login that can open
  DigitalPassport, a case-insensitive database, or a database containing anything other than this application's tables.

  Nothing else on the server is changed: no IIS, no Windows services, no other application, no system Python.
  Results are written to .\results\.

.EXAMPLE
  .\Test-Py314Compatibility.ps1
.EXAMPLE
  .\Test-Py314Compatibility.ps1 -RunDatabaseTests -SqlServer "localhost\SQLEXPRESS" -TestDatabase DigitalPassport_Py314Test -TestLogin dp_py314_test -TrustServerCertificate
#>
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [switch]$RunDatabaseTests,
    [string]$SqlServer = "",
    [string]$TestDatabase = "",
    [string]$TestLogin = "",
    [switch]$TrustServerCertificate,
    [switch]$InstallNodePackages,
    [switch]$RecreateEnvironment,
    # dry runs on a machine without Python 3.14 only (uses another interpreter and a matching wheel folder)
    [switch]$AllowOtherPythonVersion,
    [string]$WheelDir = "",
    [string]$DevWheelDir = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Root ".venv-py314"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not $WheelDir) { $WheelDir = Join-Path $Root "wheels" }
if (-not $DevWheelDir) { $DevWheelDir = Join-Path $Root "wheels-dev" }
$Results = Join-Path $Root "results"
New-Item -ItemType Directory -Force -Path $Results | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $Results "compat-$Stamp.log"
Start-Transcript -Path $Log -Append | Out-Null

function Step($text) { Write-Host ""; Write-Host "=== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "STOPPED: $text" -ForegroundColor Red; Stop-Transcript | Out-Null; exit 1 }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "$exe $($arguments -join ' ') exited with $LASTEXITCODE" }
}

try {
    # ---------------------------------------------------------------- Python 3.14 (read-only use of the system Python)
    Step "Locate Python 3.14"
    if (-not $PythonExe) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) { $PythonExe = (& py -3.14 -c "import sys; print(sys.executable)" 2>$null) }
        if (-not $PythonExe) {
            $onPath = Get-Command python -ErrorAction SilentlyContinue
            if ($onPath) { $PythonExe = $onPath.Source }
        }
    }
    if (-not $PythonExe -or -not (Test-Path $PythonExe)) { Fail "Python 3.14 not found. Pass -PythonExe 'C:\Path\To\python.exe'." }
    $ver = (& $PythonExe -c "import sys; print('%d.%d.%d %s' % (sys.version_info[:3] + (64 if sys.maxsize > 2**32 else 32,)))").Trim()
    Write-Host "Using $PythonExe ($ver-bit)"
    if (-not $ver.EndsWith(" 64")) { Fail "a 64-bit Python is required" }
    if (-not $ver.StartsWith("3.14.") -and -not $AllowOtherPythonVersion) { Fail "Python 3.14 required, found $ver" }

    # ---------------------------------------------------------------- isolated environment inside this folder
    Step "Isolated virtual environment: $Venv"
    if ($RecreateEnvironment -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
    if (-not (Test-Path $Py)) { Run $PythonExe @("-m", "venv", $Venv) }
    Run $Py @("-m", "pip", "--version")

    Step "Install the pinned packages offline (no internet, no system changes)"
    $req = Join-Path $Backend "requirements-sqlserver.txt"
    $con = Join-Path $Backend "constraints-sqlserver.txt"
    Run $Py @("-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--find-links", $WheelDir, "-r", $req, "-c", $con)
    # CAD wheels without their optional dependencies, as in requirements-cad.txt (matplotlib is not needed by VTK here)
    Run $Py @("-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--find-links", $WheelDir, "--no-deps", "cadquery-ocp==8.0.1.1.0", "cadquery-ocp-proxy==8.0.1.1.0", "vtk==9.6.2")
    $check = (& $Py -m pip check 2>&1) | Where-Object { $_ -and ($_ -notmatch "^vtk 9\.6\.2 requires matplotlib") -and ($_ -notmatch "^No broken requirements") }
    if ($check) { $check | ForEach-Object { Write-Host $_ }; Fail "pip check found broken requirements" }
    Write-Host "pip check: no broken requirements (vtk's optional matplotlib deliberately not installed)"

    if ($InstallNodePackages) {
        Step "Node packages for PDF reports (into this folder; needs internet)"
        Push-Location $Root
        try { Run "npm.cmd" @("install", "--no-audit", "--no-fund"); Run "npx.cmd" @("playwright", "install", "chromium") } finally { Pop-Location }
    }

    # ---------------------------------------------------------------- stage 1: dependency and component checks
    Step "Stage 1: dependency and component checks (no database)"
    $stage1 = Join-Path $Results "stage1-$Stamp.json"
    & $Py (Join-Path $Root "tools\py314_checks.py") $Root $stage1
    $stage1Ok = ($LASTEXITCODE -eq 0)

    # ---------------------------------------------------------------- stage 2: regression suite on a separate test database
    if ($RunDatabaseTests) {
        Step "Stage 2: regression suite on the separate test database"
        if (-not $SqlServer -or -not $TestDatabase -or -not $TestLogin) { Fail "-SqlServer, -TestDatabase and -TestLogin are all required" }
        if ($TestDatabase -ieq "DigitalPassport") { Fail "refusing the production database name DigitalPassport" }
        if ($TestDatabase -notmatch "(?i)test") { Fail "the test database name must contain 'test' (got '$TestDatabase')" }
        $node = Get-Command node -ErrorAction SilentlyContinue
        if (-not $node -or -not (Test-Path (Join-Path $Root "node_modules\playwright\package.json"))) {
            Fail "PDF/thumbnail tests need Node 22 and this folder's node_modules: run once with -InstallNodePackages"
        }
        Run $Py @("-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--find-links", $DevWheelDir, "--find-links", $WheelDir, "pytest==9.1.1", "pytest-django")
        if ($env:PY314_TEST_DB_PASSWORD) {  # unattended runs only; otherwise prompted (never written to the log)
            $plain = $env:PY314_TEST_DB_PASSWORD
        } else {
            $secure = Read-Host "Password for SQL login $TestLogin" -AsSecureString
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        }
        $env:DB_ENGINE = "mssql"; $env:DB_HOST = $SqlServer; $env:DB_NAME = $TestDatabase; $env:DB_TEST_NAME = $TestDatabase
        $env:DB_USER = $TestLogin; $env:DB_PASSWORD = $plain; $env:DB_DRIVER = "ODBC Driver 18 for SQL Server"
        $env:DB_TRUST_SERVER_CERTIFICATE = $(if ($TrustServerCertificate) { "true" } else { "false" })
        $env:DJANGO_DEBUG = "true"; $env:DJANGO_SECRET_KEY = "py314-compat-tests-" + ("t" * 50)
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        try {
            # safety pre-flight with the test login itself
            & $Py (Join-Path $Root "tools\test_db_preflight.py")
            if ($LASTEXITCODE -ne 0) { Fail "the test database pre-flight refused to continue (see above)" }
            Push-Location $Backend
            try {
                Write-Host "Full Django system check (incl. model checks) against the test database:"
                & $Py manage.py check
                if ($LASTEXITCODE -ne 0) { Fail "Django system check failed against the test database" }
                $junit = Join-Path $Results "stage2-$Stamp.xml"
                & $Py -m pytest --reuse-db -q -p no:cacheprovider "--junitxml=$junit"
                $stage2Ok = ($LASTEXITCODE -eq 0)
            } finally { Pop-Location }
        } finally {
            foreach ($v in "DB_ENGINE", "DB_HOST", "DB_NAME", "DB_TEST_NAME", "DB_USER", "DB_PASSWORD", "DB_DRIVER", "DB_TRUST_SERVER_CERTIFICATE", "DJANGO_DEBUG", "DJANGO_SECRET_KEY") {
                Remove-Item "Env:$v" -ErrorAction SilentlyContinue
            }
            $plain = $null
        }
    }

    Step "Summary"
    Write-Host ("Stage 1 (dependencies and components): " + $(if ($stage1Ok) { "PASS" } else { "FAIL" }))
    if ($RunDatabaseTests) { Write-Host ("Stage 2 (regression suite on $TestDatabase): " + $(if ($stage2Ok) { "PASS" } else { "FAIL" })) }
    Write-Host "Results: $Results"
    Stop-Transcript | Out-Null
    if (-not $stage1Ok -or ($RunDatabaseTests -and -not $stage2Ok)) { exit 1 }
    exit 0
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 1
}
