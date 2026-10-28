@echo off
REM Developer helper for Windows (needs Python 3.11 from python.org on PATH).
REM   packaging\run_dev.bat           setup + test + run
REM   packaging\run_dev.bat package   build dist\Lead Outreach and the installer (needs Inno Setup 6)
setlocal
cd /d "%~dp0.."
if "%OUTREACH_DATA_DIR%"=="" set "OUTREACH_DATA_DIR=%CD%\.devdata"

if not exist ".venv\Scripts\python.exe" (
  echo ^>^> Creating virtualenv in .venv
  py -3.11 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo Could not create a virtualenv. Install Python 3.11 from python.org. & exit /b 1 )
)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pytest
if errorlevel 1 exit /b 1

if exist tests (
  echo ^>^> Running tests
  ".venv\Scripts\python.exe" -m pytest -q tests
  if errorlevel 1 exit /b 1
)

if /i "%~1"=="package" goto package
echo ^>^> Starting Lead Outreach (data in %OUTREACH_DATA_DIR%). Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m app
exit /b %errorlevel%

:package
".venv\Scripts\python.exe" -m pip install --quiet pyinstaller pillow
".venv\Scripts\python.exe" packaging\make_icon.py || exit /b 1
".venv\Scripts\pyinstaller.exe" packaging\lead_outreach.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller || exit /b 1
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" ( echo Inno Setup 6 not found; skipping installer. Get it from jrsoftware.org & exit /b 0 )
"%ISCC%" /DAppVersion=0.0.0-local packaging\installer.iss || exit /b 1
echo ^>^> Installer: dist\installer\LeadOutreachSetup.exe
exit /b 0
