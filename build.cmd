@echo off
rem ---------------------------------------------------------------------------
rem  Build the public report, then refuse to continue if it leaks anything.
rem
rem  Run this before committing. It regenerates docs\index.html -- the only
rem  build output the public repository should ever contain.
rem
rem    build.cmd          full run (rescans every repository, slow)
rem    build.cmd fast     reuse the existing repo scan, rebuild everything else
rem    build.cmd page     rebuild only the public HTML from existing data
rem    build.cmd local    build the INTERNAL copy instead (names every client)
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=full

echo.
echo === development-time :: build (%MODE%)
echo.

if "%MODE%"=="page" goto :page
if "%MODE%"=="local" goto :local

echo [1/6] Parsing session transcripts...
python analyze.py || goto :fail

if "%MODE%"=="fast" (
  echo [2/6] Repository scan ....... skipped ^(reusing repos.json^)
  if not exist repos.json (
     echo        ERROR: repos.json missing -- run "build.cmd" without "fast" first.
     goto :fail
  )
) else (
  echo [2/6] Scanning working trees for size and age...
  python repo_metrics.py >nul || goto :fail
)

echo [3/6] Measuring delivered lines from git...
python git_delta.py >nul || goto :fail

echo [4/6] Running the before/after comparison...
python before_after.py >nul || goto :fail

echo [5/6] Fitting the model...
python model.py || goto :fail

:page
echo [6/6] Rendering the public page...
python build_report.py --out docs\index.html --public --no-fragment || goto :fail

echo.
echo === Leak check
python verify_public.py --page docs\index.html || goto :leak

rem GitHub Pages runs Jekyll by default, which skips files starting with "_".
if not exist docs\.nojekyll type nul > docs\.nojekyll

echo.
echo === Ready to commit
echo     docs\index.html      the published page  ^(safe^)
echo     docs\.nojekyll       tells GitHub Pages to serve the file as-is
echo.
echo     Everything else stays local: data.json, repos.json, git_delta.json,
echo     before_after.json, report_data.json and report.html all contain
echo     absolute paths and client names. .gitignore already excludes them.
echo.
echo     Next:  run-commit.cmd -m "docs: refresh development-time report"
echo.
exit /b 0

:local
rem The internal copy names every project, clients included. It exists for
rem sharing inside the company, is git-ignored, and is never published.
echo Rendering the internal copy ^(all projects named^)...
python build_report.py --out report.html || goto :fail
echo.
echo === Internal copy only -- NOT for the public repository
echo     report.html            every client project named
echo     report.fragment.html   same page, for publishing as an artifact
echo.
echo     Both are git-ignored. Regenerate any time with "build.cmd local".
echo.
exit /b 0

:leak
echo.
echo *** BUILD BLOCKED -- do not commit. See the failures listed above.
echo ***
echo ***   "absolute path" / "client identity" in docs\index.html
echo ***       the redaction missed a field. Fix the sanitize function
echo ***       in build_report.py, then run this script again.
echo ***
echo ***   "git is tracking ..."
echo ***       a private file is under git control despite .gitignore.
echo ***       Untrack it:  git rm --cached ^<file^>
echo.
exit /b 1

:fail
echo.
echo *** BUILD FAILED at the step above. Nothing was published.
echo.
exit /b 1
