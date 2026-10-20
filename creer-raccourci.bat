@echo off
rem Cree un raccourci "Inventaire" avec son icone sur le Bureau.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = [Environment]::GetFolderPath('Desktop'); $s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Inventaire.lnk')); $s.TargetPath = (Join-Path (Get-Location) 'lancer.bat'); $s.WorkingDirectory = (Get-Location).Path; $s.IconLocation = (Join-Path (Get-Location) 'static\icon.ico'); $s.Save()"
echo Raccourci "Inventaire" cree sur le Bureau.
pause
