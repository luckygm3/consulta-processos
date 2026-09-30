@echo off
rem Cria o ambiente (na primeira vez), instala as dependências e abre o app no navegador.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "VPY=.venv\Scripts\python.exe"

if exist "%VPY%" goto dependencias

echo Procurando Python 3.11 ou mais novo...
call :achar_python
if defined PY goto criar_venv

echo.
echo O Python 3.11+ nao foi encontrado neste computador. Ele e necessario para rodar o app.
where winget >nul 2>nul
if errorlevel 1 goto sem_python
set "RESP="
set /p "RESP=Instalar o Python 3.12 agora (gratuito, do python.org, so para este usuario)? [S/N] "
if /i not "%RESP%"=="S" goto sem_python
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
call :achar_python
if defined PY goto criar_venv

:sem_python
echo.
echo Instale o Python pelo site https://www.python.org/downloads/
echo ^(na instalacao, marque "Add python.exe to PATH"^) e depois abra este run.bat de novo.
echo.
pause
exit /b 1

:criar_venv
echo Criando ambiente virtual com %PY% ...
%PY% -m venv .venv
if errorlevel 1 (
  echo Falha ao criar o ambiente virtual.
  pause
  exit /b 1
)

:dependencias
rem Só reinstala se o requirements.txt mudou
fc /b requirements.txt .venv\requirements.instalado >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencias...
  "%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo Falha ao instalar as dependencias. Verifique a internet e tente de novo.
    pause
    exit /b 1
  )
  copy /y requirements.txt .venv\requirements.instalado >nul
)

"%VPY%" run.py %*
if errorlevel 1 pause
exit /b

rem Procura um Python 3.11+ (launcher py, python no PATH ou instalação do usuário)
:achar_python
set "PY="
for %%P in ("py -3.13" "py -3.12" "py -3.11" "py -3" "python") do (
  if not defined PY (
    %%~P -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=%%~P"
  )
)
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined PY if exist "%%D\python.exe" set PY="%%D\python.exe"
  )
)
exit /b 0
