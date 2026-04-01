@echo off
title Remove FPT Warehouse Scanner from Startup
color 0C

echo ============================================================
echo   Removing FPT Warehouse Scanner from Windows Startup
echo ============================================================
echo.

set SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FPT_Warehouse_Scanner.lnk

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [SUCCESS] Da xoa khoi Startup thanh cong!
    echo App se KHONG tu dong chay khi bat may tinh nua.
) else (
    echo [INFO] Khong tim thay shortcut trong Startup folder.
)

echo.
echo ============================================================
pause
