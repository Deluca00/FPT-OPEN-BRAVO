    @echo off
    title FPT Warehouse Scanner
    color 0A

    echo ============================================================
    echo    FPT Warehouse Scanner - Starting...
    echo ============================================================
    echo.

    cd /d "%~dp0"

    echo [1/3] Checking Python...
    python --version
    if errorlevel 1 (
        echo ERROR: Python not found! Please install Python first.
        pause
        exit /b 1
    )

    echo.
    echo [2/3] Checking dependencies...
    pip show flask >nul 2>&1
    if errorlevel 1 (
        echo Installing required packages...
        pip install flask flask-cors psycopg2-binary qrcode Pillow
    )

    echo.
    echo [3/3] Starting server...
    echo.
    echo ============================================================
    echo    Server is running!
    echo    ----------------------------------------------------
    echo    HTTP:  http://localhost:5000
    echo    HTTPS: https://localhost:5443
    echo    ----------------------------------------------------
    echo    Press Ctrl+C to stop the server
    echo ============================================================
    echo.

    python C:\openbravo_installation\openbravo-release-24Q2\barcode_app\app.py

    pause
