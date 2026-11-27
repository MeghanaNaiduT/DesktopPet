@echo off
rem Starts Desktop Pet without a console window. Needs Python 3.9+ (https://www.python.org/downloads/).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0DesktopPet.pyw" & exit /b)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0DesktopPet.pyw" & exit /b)
echo Python was not found. Install it with:  winget install Python.Python.3.12
echo (or from https://www.python.org/downloads/ - keep "tcl/tk" ticked), then run this file again.
pause
