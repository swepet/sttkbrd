@echo off
rem Builds dist\sttkbrd.exe: one file, no console window, no Python needed to run it.
cd /d "%~dp0"
python -m pip install -r requirements-windows.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name sttkbrd ^
  --icon art\icon.ico --add-data "art;art" sttkbrd_exe.py || exit /b 1
echo.
echo Built: %~dp0dist\sttkbrd.exe
