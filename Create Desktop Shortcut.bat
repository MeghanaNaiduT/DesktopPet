@echo off
rem Puts a "Desktop Pet" icon (the kitten) on your desktop. No exe needed; uses the installed Python.
set "TARGET=%~dp0DesktopPet.pyw"
set "ICON=%~dp0desktop_pet\assets\app.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Desktop Pet.lnk'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%ICON%'; $s.Save()"
echo Shortcut created on your desktop.
pause
