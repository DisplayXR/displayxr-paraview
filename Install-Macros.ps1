<#
Adds "Start 3D" and "Exit 3D" to ParaView's Macros toolbar (per user, %APPDATA%\ParaView\Macros).
Idempotent; Launch-ParaView-DisplayXR.cmd runs it every time. Remove the two .py files to uninstall.
#>
$python = Join-Path $PSScriptRoot "python"
$macros = Join-Path $env:APPDATA "ParaView\Macros"
New-Item -ItemType Directory -Force $macros | Out-Null

$header = @"
# DisplayXR glasses-free 3D (installed by displayxr-paraview\Install-Macros.ps1)
import sys
if r"$python" not in sys.path:
    sys.path.insert(0, r"$python")
import displayxr_paraview
"@

Set-Content -Encoding UTF8 (Join-Path $macros "Start 3D.py") ($header + "`ndisplayxr_paraview.start()`n")
Set-Content -Encoding UTF8 (Join-Path $macros "Exit 3D.py") ($header + "`ndisplayxr_paraview.stop()`n")
# Omniverse: one-shot USD export, and live export (toggle) for USD Composer.
Set-Content -Encoding UTF8 (Join-Path $macros "Send to Omniverse.py") ($header + "`nimport omniverse_link`nomniverse_link.send()`n")
Set-Content -Encoding UTF8 (Join-Path $macros "Omniverse Live.py") ($header + "`nimport omniverse_link`nomniverse_link.toggle_live()`n")
