@echo off
REM =====================================================
REM Cloudflare Tunnel Auto-Start
REM =====================================================
REM Chay tunnels va tu dong cap nhat URL vao config
REM =====================================================

title Cloudflare Tunnels

python "%~dp0cloudflare_tunnels.py"

pause
