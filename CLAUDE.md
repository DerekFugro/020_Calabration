# CLAUDE.md — working on SurveyorCalibration (repo 020_Calabration)

Read `README.md` for what the apps do. Capture work: read `docs/capture/CONTEXT.md` first.

## The people and the code
- Owner: Derek (Fugro ARAN hardware/field specialist). Repo `DerekFugro/020_Calabration`,
  branch `main`. Local copy on the bench PC: `E:\DP\SurveyorCalibration`
  (ARAN59-Server, Windows user `dvs`).
- Pushes go through Derek's personal GitHub `dapfromcanada` (a collaborator), signed in
  on the PC (`C:\Users\dvs\.gitconfig`). Leave other people's saved credentials alone.
- Python 3.12 + uv + `requirements.txt` (no pyproject). PySide6 GUI, OpenCV 5, pyodbc,
  comtypes. The GOX also needs BitFlow's `BFModule` cp312 wheel (not on PyPI, see README).

## Run and test
```powershell
uv run python main.py            # calibration app (start screen)
uv run python -m src.capture     # SurveyorCapture
uv run pytest -q -p no:cacheprovider
```
Scripts that run the detector use worker processes: any test script must have an
`if __name__ == "__main__":` guard (with `multiprocessing.freeze_support()`), or every
worker re-runs it.

## What "tested" means here (Derek's rule)
Unit tests are not enough. Before saying a change works: run the real thing on real
data, open and look at the output files (PDF, YAML, images), and look at the app's
screens (screenshots). Say plainly what was checked and what was not.

## How Derek wants answers
Short, plain English (grade 9), prose, the answer first. If he asked questions, answer
them first. If a question changes how the code should be written, ask and wait — no code
in the same reply. Mark where facts come from: [from training data], [from provided
context], [inference]. Never claim something is tested or done unless it was.

## Safety rules (hard)
- Van database: **read only**, Windows sign-in only, fixed SELECTs (`src/camera_db.py`).
- Never change ARAN files, settings or output folders.
- Cameras and capture cards: open, read, close. The one exception: the GOX's FrameStart
  trigger is switched off while Capture has it and is always put back
  (`src/capture/bitflow.py`, with a crash-safe restore file). Never open the BitFlow
  card while FR Video Service runs. Never touch a camera another program is using.
- Ask Derek before: starting/stopping services, installing software or Setup.exe,
  opening a camera on a van, anything with an admin prompt.
- Moving files is fine when it is the app's job (Superseded, NotUsed); never delete
  Derek's photos or results.

## Commits
- Commit only when asked; message in a file (`git commit -F <file>`), ending with the
  attribution lines the session gives. Push to `main`.
- Files use LF; Git warns about CRLF on Windows — that is fine.
- `installer\build.ps1` refuses uncommitted code unless `-Test` (version gets "-modified").

## Design rules
- New GUI widgets: dark Fusion palette from `src/styles.py`; the 5-method `__init__`
  pattern (`_create_widgets`, `_create_layouts`, `_connect_signals`, `_apply_styles`,
  `_load_initial_state`); standards in `docs/capture/standards/`.
- Capture stays separate (own process; import boundary enforced by
  `tests/test_capture_boundary.py`).
- Boards can have their own finder (`board.yaml` `finder:`); the 12x8 chessboard uses
  `src/marker_finder.py`. A finder must agree with OpenCV's corners where both work
  (checked: median 0.001 px) before it is trusted.
- Never read old EOP files as input; the app writes EOPs. Metric units.

## Traps already found (don't fall in again)
- **GenICam settings:** a process started without the machine's `GENICAM_*` settings gets
  "Board opened but no camera responded" from the GOX. `bitflow.load_genicam_settings()`
  loads them.
- **BitFlow board numbers:** opening a board that isn't there pops up a modal "Internal
  SDK Error" and hangs. Only open boards Windows lists (PCI vendor 118D).
- **GOX colours:** camera "BayerRG" = OpenCV `COLOR_BayerBG2BGR`.
- **Installer:** with Git for Windows on PATH, PyInstaller took Git's OpenSSL and the built
  app crashed opening the main window; the spec now forces Python's own DLLs.
- **Settings in tests:** `tests/conftest.py` sends QSettings to a temp file; keep it, or
  tests write pytest temp folders into the real app settings.
- **Re-running on a copy:** the calibration app moves unusable photos to `NotUsed\`, so a
  second run on the same copy sees fewer photos. Make a fresh copy each time.
- **"Lens steady" is noisy:** on the same 50 photos it swung 2.4–5.5 mm with which few
  photos were in. Don't judge small detector changes by it; compare corners instead.
- **Remote tool timeouts:** long commands time out the remote shell; run them in the
  background writing to a log file, then read the log. Don't re-run something that
  changes state just because the reply timed out — check first.
- **Claude desktop app hides AppData (ARAN59):** it is a packaged Windows app, so anything
  its tools write under `C:\Users\dvs\AppData` goes to its own private copy. A Python
  that uv installs there works inside Claude but not for launch.bat ("No module named
  PySide6"). Keep Python in the project: `UV_PYTHON_INSTALL_DIR=E:\DP\SurveyorCalibration\.uv\python`
  (git-ignored), then `uv venv --python 3.12` and `uv pip install -r requirements.txt`.
  Test launch.bat through File Explorer (`Start-Process explorer.exe launch.bat`), not
  from Claude's shell. The same is likely for app settings in the registry [inference].
- **New PC setup (ARAN59):** no `.gitconfig` there (identity set for the repo only). The
  first `git push` must run in a real terminal so the GitHub sign-in window can open.
- **Seeing the apps:** computer use can't find the Python windows by name; take window
  pictures with PrintWindow (PowerShell) or `widget.grab()`. A test script that starts
  Capture as a child keeps the output pipe open: write its output to a file.
- **Made-up board photos with no tilt** give a hard stop (focal length not plausible), not
  a plain NOT PASSED; tilt the board views when you need a NOT PASSED to test with.
