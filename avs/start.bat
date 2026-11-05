@echo off
rem Lance (ou met a jour) Video Studio. Double-cliquez sur ce fichier.
cd /d "%~dp0"
if not exist .env (
  echo Creation du fichier .env ...
  copy .env.example .env >nul
  echo.>> .env
  echo COOKIE_SECURE=false>> .env
  echo APP_SECRET_KEY=Zq8xT3mVb7LpR2nYc9HdKs4WjF6uEa1GoIe5Xt0B>> .env
  echo APP_ENCRYPTION_KEY=>> .env
)
docker compose up -d --build
echo.
docker compose ps
echo.
echo Ouvrez http://localhost:3000 dans votre navigateur.
pause
