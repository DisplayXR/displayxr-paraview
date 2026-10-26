@echo off
REM ParaView Glance (the browser viewer shipped with ParaView) in the DisplayXR Browser, in 3D.
REM Builds web\_site from your ParaView install, serves it on 127.0.0.1:8765 and opens it.
REM Usage: Launch-Glance-DisplayXR.cmd [dataset name in web\data, default disk_out_ref.vtp]
REM Optional: set PARAVIEW_HOME to your ParaView install; set DXR_BROWSER to the browser exe.
setlocal
set "HERE=%~dp0"
set "DATA=%~1"
if "%DATA%"=="" set "DATA=disk_out_ref.vtp"
if "%DXR_BROWSER%"=="" set "DXR_BROWSER=C:\Program Files\DisplayXR\Browser\chrome.exe"
set "PVARG="
if not "%PARAVIEW_HOME%"=="" set "PVARG=--paraview "%PARAVIEW_HOME%""
start "Glance server (close to stop)" /min python "%HERE%serve.py" %PVARG%
timeout /t 3 /nobreak >nul
start "" "%DXR_BROWSER%" --new-window "http://127.0.0.1:8765/?name=%DATA%&url=data/%DATA%"
endlocal
