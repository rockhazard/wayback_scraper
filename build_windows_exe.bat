@echo off
setlocal

REM Build a one-file Windows executable using PyInstaller.
REM Run this on Windows inside your virtual environment.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

pyinstaller --onefile --name wayback_scraper wayback_scraper.py

echo.
echo Build complete. Executable should be in dist\wayback_scraper.exe
endlocal
