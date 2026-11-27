@echo off
rem Builds a real DesktopPet.exe (no Python needed afterwards).  Needs internet ONCE to download PyInstaller;
rem the app itself never uses the network.
rem NOTE: the exe is unsigned. Windows "Smart App Control" blocks unsigned exes until it is switched off.
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller || goto :fail
py -m PyInstaller --noconfirm --clean --noconsole --onedir --name DesktopPet ^
  --icon "desktop_pet\assets\app.ico" ^
  --add-data "desktop_pet\assets;desktop_pet\assets" ^
  DesktopPet.pyw || goto :fail
echo.
echo Done. Your app: %~dp0dist\DesktopPet\DesktopPet.exe
echo Copy the whole dist\DesktopPet folder anywhere; double-click DesktopPet.exe to run.
pause
exit /b 0
:fail
echo Build failed - read the messages above.
pause
