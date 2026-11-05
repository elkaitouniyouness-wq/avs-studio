@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist docker-compose.yml (
  echo [KHATA2] Hada machi dossier "avs" s7i7. 7ett had fichier jnb docker-compose.yml.
  pause
  exit /b 1
)
if not exist .env (
  echo [KHATA2] Ma kaynch .env f had dossier.
  pause
  exit /b 1
)
echo.
echo Lsq Client ID dyal Google MERRA WA7DA (clic droit = coller) w dghet Entree:
set /p "CID=> "
echo.
echo Lsq Client secret (GOCSPX-...) MERRA WA7DA w dghet Entree:
set /p "CSEC=> "
if "%CID%"=="" (echo Client ID khawi. 3awd. & pause & exit /b 1)
if "%CSEC%"=="" (echo Secret khawi. 3awd. & pause & exit /b 1)
copy /y .env .env.bak >nul
rem 7yyed kol stour l9dima (khawya wla mkarrra) 9bel ma nkteb s7i7in
findstr /v /b "GOOGLE_OAUTH_ FRONTEND_ORIGIN= PUBLIC_BASE_URL=" .env.bak > .env
>> .env echo.
>> .env echo GOOGLE_OAUTH_CLIENT_ID=%CID%
>> .env echo GOOGLE_OAUTH_CLIENT_SECRET=%CSEC%
>> .env echo GOOGLE_OAUTH_REDIRECT_URI=http://localhost:3000/api/youtube/callback
>> .env echo FRONTEND_ORIGIN=http://localhost:3000
>> .env echo PUBLIC_BASE_URL=http://localhost:3000
echo.
echo Kan3awd nlanci api / worker / scheduler...
docker compose up -d --force-recreate api worker scheduler
timeout /t 12 /nobreak >nul
echo.
echo --- Client ID f l'WORKER (khass ykon ID wa7ed) ---
docker compose exec -T worker printenv GOOGLE_OAUTH_CLIENT_ID </nul
echo.
echo --- Client ID f l'API ---
docker compose exec -T api printenv GOOGLE_OAUTH_CLIENT_ID </nul
echo.
echo Daba 3awd Publier f l'app. (Sauvegarde dyal l'ancien .env: .env.bak)
pause
