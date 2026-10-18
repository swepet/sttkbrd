@echo off
rem Builds dist\sttkbrd-v<version>.exe: one file, no console window, no Python needed to run it.
rem The version comes from sttkbrd\__init__.py and is in the file name and in the exe's properties.
cd /d "%~dp0"
python -m pip install -r requirements-windows.txt || exit /b 1
if not exist build mkdir build
for /f %%v in ('python make_version_info.py build\version-info.txt') do set VERSION=%%v
if not defined VERSION exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name sttkbrd-v%VERSION% ^
  --icon art\icon.ico --version-file build\version-info.txt --add-data "art;art" sttkbrd_exe.py || exit /b 1
echo.
echo Built: %~dp0dist\sttkbrd-v%VERSION%.exe
