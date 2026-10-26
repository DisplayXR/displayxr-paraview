@echo off
rem Launch ParaView with glasses-free 3D on DisplayXR (tested on Leia SR).
rem
rem   Launch-ParaView-DisplayXR.cmd                  demo: flow around a heated disk
rem   Launch-ParaView-DisplayXR.cmd file.pvsm        your own state file or data file
rem   Launch-ParaView-DisplayXR.cmd --dev [file]     use a dev build of the DisplayXR runtime
rem
rem Press "Start 3D" on the Macros toolbar. The 3D appears in ParaView's render view and
rem follows ParaView's camera: rotate, zoom, pick and use widgets with the mouse as usual.
rem "Exit 3D" returns to 2D. Several 3D apps can each show 3D in their own window at once.
rem
rem Environment overrides:
rem   PARAVIEW_EXE      paraview.exe to run (or PARAVIEW_HOME, its install folder); default:
rem                     the newest ParaView installed (tools\Find-ParaView.ps1)
rem   DXR_RUNTIME       "installed" (default) or "dev" (same as --dev)
rem   DXR_DEV_RUNTIME   the dev runtime's DisplayXR_win64.json; default: a displayxr-runtime
rem                     checkout next to this one, ..\displayxr-runtime\_package\bin

setlocal
rem ARGS: the arguments for ParaView (everything after --dev); FIRST: the first of them.
set "ARGS=%*"
set "FIRST=%~1"
set "DEVARG="
if /i "%~1"=="--dev" set DEVARG=1
if /i "%~1"=="-dev" set DEVARG=1
if defined DEVARG (
	set "DXR_RUNTIME=dev"
	set "FIRST=%~2"
	call set "ARGS=%%ARGS:*dev=%%"
)
if not defined DXR_RUNTIME set "DXR_RUNTIME=installed"

where pwsh >nul 2>nul || (
	echo PowerShell 7 ^(pwsh^) is required: https://aka.ms/powershell
	exit /b 1
)

rem The helper scripts are plain, unsigned .ps1 files in this folder. They run under
rem PowerShell's default policy (RemoteSigned); the launcher never bypasses it.
rem If one can't run (e.g. this folder came from a downloaded zip and is marked as from the
rem internet), say so instead of bypassing the policy.
set "PS_HELP=If PowerShell refused to run a script from %~dp0 (for example because the folder came from a downloaded zip), unblock the folder: in PowerShell run  Get-ChildItem -Recurse -LiteralPath '%~dp0' ^| Unblock-File"

set "PV_EXE="
for /f "delims=" %%P in ('pwsh -NoProfile -File "%~dp0tools\Find-ParaView.ps1"') do set "PV_EXE=%%P"
if not defined PV_EXE goto :no_paraview
echo ParaView: %PV_EXE%

rem Only ParaView uses DisplayXR; the machine's active OpenXR runtime is left alone.
rem Default: the installed DisplayXR runtime. "--dev" (or DXR_RUNTIME=dev) picks a dev build,
rem which 3D inside ParaView's window and mouse pass-through need until they ship in a
rem release (DisplayXR #2332 + DXR_HOSTED_INPUT).
if /i "%DXR_RUNTIME%"=="dev" (
	if not defined DXR_DEV_RUNTIME set "DXR_DEV_RUNTIME=%~dp0..\displayxr-runtime\_package\bin\DisplayXR_win64.json"
	call set "XR_RUNTIME_JSON=%%DXR_DEV_RUNTIME%%"
) else (
	set "XR_RUNTIME_JSON=%ProgramFiles%\DisplayXR\Runtime\DisplayXR_win64.json"
)
if not exist "%XR_RUNTIME_JSON%" (
	if /i "%DXR_RUNTIME%"=="dev" (
		echo Dev runtime not found: "%XR_RUNTIME_JSON%". Set DXR_DEV_RUNTIME to its DisplayXR_win64.json.
	) else (
		echo DisplayXR runtime not installed: "%XR_RUNTIME_JSON%" is missing. Install the
		echo DisplayXR runtime ^(https://github.com/DisplayXR/displayxr-runtime^), or use --dev for a dev build.
	)
	exit /b 1
)
echo DisplayXR runtime ^(%DXR_RUNTIME%^): %XR_RUNTIME_JSON%
set DXR_HOSTED_WINDOW=auto
set DXR_HOSTED_INPUT=app
rem A gamepad drives ParaView's own camera (python\gamepad.py), not the runtime's fly camera
rem or emulated VR hands, which would move the 3D away from ParaView's view.
set DXR_INPUT_GAMEPAD_NAV=0
set DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS=0

rem Camera rig for the 3D view; rewritten at every Start 3D to fit the scene's depth to the display.
if not exist "%LOCALAPPDATA%\DisplayXR-ParaView" mkdir "%LOCALAPPDATA%\DisplayXR-ParaView"
set DXR_LEGACY_CAMERA_RIG=%LOCALAPPDATA%\DisplayXR-ParaView\camera-rig.json
if not exist "%DXR_LEGACY_CAMERA_RIG%" echo {"convergenceMeters":0.6}> "%DXR_LEGACY_CAMERA_RIG%"

set PYTHONPATH=%~dp0python;%PYTHONPATH%
pwsh -NoProfile -File "%~dp0Install-Macros.ps1" || goto :no_macros

if "%FIRST%"=="" (
	start "" /max "%PV_EXE%" --script="%~dp0startup\demo_disk.py"
) else (
	start "" /max "%PV_EXE%" %ARGS%
)

rem Keeps the 3D exactly on ParaView's render view (publishes its rect to the runtime).
start "" /min pwsh -NoProfile -WindowStyle Hidden -File "%~dp0Follow-ParaView.ps1"

rem Live Depth / Focus slider in the empty right end of ParaView's menu bar (the shared DisplayXR
rem depth slider, vendored in tools\; needs the dev runtime's DXR_HostedDepth, DisplayXR #2350).
rem 100 %% = the comfort budget filled; ParaView caps it there.
start "" /min pwsh -NoProfile -WindowStyle Hidden -File "%~dp0tools\DisplayXR-DepthSlider.ps1" -Process paraview -RightGap 40 -Top 2 -Height 58
exit /b 0

rem Messages are printed outside ( ) blocks: the folder path may contain parentheses.
:no_paraview
echo ParaView was not started.
goto :ps_help
:no_macros
echo Could not install the Start 3D / Exit 3D macros.
:ps_help
echo %PS_HELP%
exit /b 1
