@echo off
title Add FPT Warehouse Scanner to Startup
color 0A

echo ============================================================
echo   Adding FPT Warehouse Scanner to Windows Startup
echo ============================================================
echo.
echo Se tu dong chay khi bat may:
echo   [1] Barcode Scanner App (port 5000/5443)
echo   [2] Cloudflare Tunnel cho Barcode App
echo   [3] Cloudflare Tunnel cho Openbravo
echo.

:: Kiem tra cloudflared da cai dat chua
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] cloudflared chua duoc cai dat!
    echo Cloudflare Tunnels se khong hoat dong.
    echo Cai dat: winget install Cloudflare.cloudflared
    echo.
)

:: Tạo shortcut trong Startup folder
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=C:\openbravo_installation\openbravo-release-24Q2\barcode_app\start_hidden.vbs"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\FPT_Warehouse_Scanner.lnk"

:: Tạo file VBS tạm để tạo shortcut (tránh lỗi ký tự đặc biệt)
set "TEMP_VBS=%TEMP%\create_shortcut.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP_VBS%"
echo sLinkFile = "%SHORTCUT_PATH%" >> "%TEMP_VBS%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP_VBS%"
echo oLink.TargetPath = "wscript.exe" >> "%TEMP_VBS%"
echo oLink.Arguments = """%VBS_PATH%""" >> "%TEMP_VBS%"
echo oLink.WorkingDirectory = "C:\openbravo_installation\openbravo-release-24Q2\barcode_app" >> "%TEMP_VBS%"
echo oLink.Description = "FPT Warehouse Scanner + Cloudflare Tunnels" >> "%TEMP_VBS%"
echo oLink.Save >> "%TEMP_VBS%"

:: Chạy VBS để tạo shortcut
cscript //nologo "%TEMP_VBS%"
del "%TEMP_VBS%" 2>nul

if exist "%SHORTCUT_PATH%" (
    echo.
    echo [SUCCESS] Da them vao Startup thanh cong!
    echo.
    echo Shortcut created at:
    echo %SHORTCUT_PATH%
    echo.
    echo Khi bat may, se tu dong chay:
    echo   - Barcode Scanner App
    echo   - Cloudflare Tunnel cho Barcode App (port 5443)
    echo   - Cloudflare Tunnel cho Openbravo (port 8080)
    echo.
    echo LUU Y: URL tunnel se thay doi moi lan khoi dong.
    echo Cap nhat URL moi trong app sau khi khoi dong lai may.
)

echo.
echo ============================================================
pause
