@echo off
rem Rebuilds Mochi's animation frames from the pictures in the tools folder
rem (tools\mochi_open.png, tools\mochi_closed.png, tools\mochi_happy.png).
rem Needs internet once to install three helper libraries; the app itself stays fully offline.
cd /d "%~dp0"
py -m pip install --quiet pillow numpy opencv-python-headless || goto :fail
py tools\build_sprites.py || goto :fail
echo.
echo Done. Restart Desktop Pet (Quit from the tray icon, then start it again).
pause
exit /b 0
:fail
echo Something went wrong - read the messages above.
pause
