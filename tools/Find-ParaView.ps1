<#
Prints the full path of the ParaView to launch (paraview.exe), or exits 1 with a message.

  1. PARAVIEW_EXE   path to paraview.exe
  2. PARAVIEW_HOME  a ParaView install folder (the one holding bin\paraview.exe)
  3. the newest ParaView found in:
       %ProgramFiles%\ParaView *            (installer)
       %LOCALAPPDATA%\Programs\ParaView*    (per-user installer)
       %USERPROFILE%\ParaView-*             (zip from paraview.org, unpacked in the user folder)
       the uninstall entries of ParaView installers (registry)

Only reads; never starts ParaView. Run it on its own to see what the launcher would pick.
#>
$ErrorActionPreference = 'SilentlyContinue'

function Fail($msg) { [Console]::Error.WriteLine($msg); exit 1 }

if ($env:PARAVIEW_EXE) {
	if (Test-Path -LiteralPath $env:PARAVIEW_EXE -PathType Leaf) { (Resolve-Path -LiteralPath $env:PARAVIEW_EXE).Path; exit 0 }
	Fail "PARAVIEW_EXE is set but not found: $env:PARAVIEW_EXE"
}
if ($env:PARAVIEW_HOME) {
	$exe = Join-Path $env:PARAVIEW_HOME "bin\paraview.exe"
	if (Test-Path -LiteralPath $exe -PathType Leaf) { $exe; exit 0 }
	Fail "PARAVIEW_HOME is set but has no bin\paraview.exe: $env:PARAVIEW_HOME"
}

$roots = @()
foreach ($pattern in @(
		(Join-Path $env:ProgramFiles "ParaView *"),
		(Join-Path $env:LOCALAPPDATA "Programs\ParaView*"),
		(Join-Path $env:USERPROFILE "ParaView-*"))) {
	$roots += Get-ChildItem -Path $pattern -Directory | ForEach-Object FullName
}
$uninstall = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
	"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
foreach ($entry in (Get-ItemProperty -Path $uninstall | Where-Object DisplayName -like "ParaView*")) {
	if ($entry.InstallLocation) { $roots += $entry.InstallLocation.Trim('"') }
	elseif ($entry.DisplayIcon) { $roots += Split-Path (Split-Path ($entry.DisplayIcon -replace ',\d+$', '').Trim('"')) }
}

# Newest first: the version in the folder name (ParaView 6.2.0, ParaView-6.2.0-Windows-...),
# else paraview.exe's file version.
$found = foreach ($root in ($roots | Where-Object { $_ } | Select-Object -Unique)) {
	$exe = Join-Path $root "bin\paraview.exe"
	if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { continue }
	$version = [version]"0.0"
	if ((Split-Path $root -Leaf) -match '(\d+)\.(\d+)(?:\.(\d+))?') {
		$version = [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], ($Matches[3] ?? 0))
	} elseif ((Get-Item -LiteralPath $exe).VersionInfo.FileVersion -match '^(\d+)\.(\d+)(?:\.(\d+))?') {
		$version = [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], ($Matches[3] ?? 0))
	}
	[pscustomobject]@{ Exe = $exe; Version = $version }
}
$best = $found | Sort-Object Version -Descending | Select-Object -First 1
if ($best) { $best.Exe; exit 0 }
Fail ("ParaView not found. Install it from https://www.paraview.org/download/ or set PARAVIEW_EXE " +
	"to its paraview.exe (or PARAVIEW_HOME to its install folder).")
