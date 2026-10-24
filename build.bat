@echo off
REM ============================================================
REM Build do Rocket League Live Dashboard num .exe (Windows)
REM Corre este script dentro da pasta do projeto (onde estao
REM app.py, tracker_core.py e requirements.txt).
REM ============================================================

echo [1/4] A criar ambiente virtual (venv)...
python -m venv venv
call venv\Scripts\activate.bat

echo [2/4] A instalar dependencias...
pip install --upgrade pip
pip install -r requirements.txt

echo [3/4] A limpar builds anteriores (os teus dados em dist\ ficam)...
rmdir /s /q build 2>nul
REM profiles.json e history.db vivem ao lado do .exe: NAO apagar a pasta dist.
REM (copia de seguranca em dados_backup\ por precaucao)
if not exist dados_backup mkdir dados_backup
if exist dist\profiles.json copy /y dist\profiles.json dados_backup\profiles.json >nul
if exist dist\history.db copy /y dist\history.db dados_backup\history.db >nul
if exist dist\ballchasing.json copy /y dist\ballchasing.json dados_backup\ballchasing.json >nul
if exist dist\replays.db copy /y dist\replays.db dados_backup\replays.db >nul
if exist dist\ai.json copy /y dist\ai.json dados_backup\ai.json >nul
if exist dist\settings.json copy /y dist\settings.json dados_backup\settings.json >nul
del /q dist\RL-Live-Dashboard.exe 2>nul
del /q RL-Live-Dashboard.spec 2>nul

echo [4/4] A gerar o .exe com PyInstaller...
pyinstaller --onefile --windowed --icon "AppRL.ico" --hidden-import i18n_en --hidden-import pystray._win32 --add-data "fonts;fonts" --name "RL-Live-Dashboard" app.py

echo [extra] A copiar config.ini para dist\ (nome do jogador)...
if exist config.ini (
    copy /y config.ini dist\config.ini >nul
) else (
    echo [player] > dist\config.ini
    echo name = >> dist\config.ini
)

echo.
echo ============================================================
echo  Pronto! O executavel esta em: dist\RL-Live-Dashboard.exe
echo  Podes copiar esse ficheiro (e o config.ini ao lado, se quiseres
echo  guardar o teu nome) para onde quiseres -- nao precisa do
echo  Python instalado para correr.
echo ============================================================
pause
