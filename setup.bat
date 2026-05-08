@echo off
echo === Image Batch Converter/Optimizer - Setup ===
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [OK] Found:
python --version

echo.
echo Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install Pillow pillow-heif pyoxipng

echo.
echo [OK] Setup complete. Run the app with:
echo     python app.py --help
echo     python app.py convert --help
echo     python app.py optimize --help
pause
