@echo off
rem Launch ParaView with glasses-free 3D on DisplayXR (tested on Leia SR).
rem
rem   Launch-ParaView-DisplayXR.cmd                  demo: flow around a heated disk
rem   Launch-ParaView-DisplayXR.cmd file.pvsm        your own state file or data file
rem
rem Press "Start 3D" on the Macros toolbar. The 3D appears in ParaView's render view and
rem follows ParaView's camera: rotate, zoom, pick and use widgets with the mouse as usual.
rem "Exit 3D" returns to 2D. Several 3D apps can each show 3D in their own window at once.

setlocal
if not defined PARAVIEW_HOME set PARAVIEW_HOME=%USERPROFILE%\ParaView-6.2.0-Windows-Python3.12-msvc2017-AMD64
if not exist "%PARAVIEW_HOME%\bin\paraview.exe" (
	echo ParaView not found in "%PARAVIEW_HOME%". Set PARAVIEW_HOME to your ParaView folder.
	exit /b 1
)

rem Only ParaView uses DisplayXR; the machine's active OpenXR runtime is left alone.
rem 3D inside ParaView's window and mouse pass-through need the dev runtime
rem (DisplayXR #2332 + DXR_HOSTED_INPUT) until they ship in a release.
set DEV_RUNTIME=%USERPROFILE%\dev\displayxr-runtime\_package\bin\DisplayXR_win64.json
if exist "%DEV_RUNTIME%" (
	set XR_RUNTIME_JSON=%DEV_RUNTIME%
) else (
	set XR_RUNTIME_JSON=C:\Program Files\DisplayXR\Runtime\DisplayXR_win64.json
)
set DXR_HOSTED_WINDOW=auto
set DXR_HOSTED_INPUT=app

rem Camera rig for the 3D view; rewritten at every Start 3D to fit the scene's depth to the display.
if not exist "%LOCALAPPDATA%\DisplayXR-ParaView" mkdir "%LOCALAPPDATA%\DisplayXR-ParaView"
set DXR_LEGACY_CAMERA_RIG=%LOCALAPPDATA%\DisplayXR-ParaView\camera-rig.json
if not exist "%DXR_LEGACY_CAMERA_RIG%" echo {"convergenceMeters":0.6}> "%DXR_LEGACY_CAMERA_RIG%"

set PYTHONPATH=%~dp0python;%PYTHONPATH%
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Macros.ps1"

if "%~1"=="" (
	start "" /max "%PARAVIEW_HOME%\bin\paraview.exe" --script="%~dp0startup\demo_disk.py"
) else (
	start "" /max "%PARAVIEW_HOME%\bin\paraview.exe" %*
)

rem Keeps the 3D exactly on ParaView's render view (publishes its rect to the runtime).
start "" /min pwsh -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0Follow-ParaView.ps1"

rem Live Depth / Focus slider in the empty right end of ParaView's menu bar (shared DisplayXR
rem tool, needs the dev runtime's DXR_HostedDepth, DisplayXR #2350). 100 %% = the comfort budget
rem filled; ParaView caps it there.
set SLIDER=%USERPROFILE%\.claude\skills\displayxr-compat\tools\DisplayXR-DepthSlider.ps1
if exist "%SLIDER%" start "" /min pwsh -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%SLIDER%" -Process paraview -RightGap 40 -Top 2 -Height 58
