# Instructions for SurveyorCapture (SurveyorCalibration photo collection program)

> This spec is self-contained. The coding agent may have no prior context — every
> rule here is explicit. Default to the strongest model tier (currently Claude
> Opus 5) unless a task is explicitly routed lower.
>
> Written 2026-11-08 with Derek (Fugro ARAN hardware/field specialist). Repo:
> `DerekFugro/020_Calabration`, usually at
> `F:\Sidewalk\002_App\SidewalkProfilier\075_CalabrationApps\020_Calabration`.
> Read `docs/capture/CONTEXT.md` first.

## ⭐ Project name:
**SurveyorCapture** — the photo collection program of the SurveyorCalibration app
(called 020_Calabration until 2026-11-09; the repo and code folder keep that name).
Code folder `src/capture`, exe `SurveyorCapture.exe`, window title "SurveyorCapture".

## ⭐ Purpose:
Show live video from one van camera and save full-size calibration photos into a
folder, so the SurveyorCalibration app can grade and calibrate them.

## ⭐ Problem it solves:
Today calibration photos are grabbed with a camera vendor tool, then copied and
renamed by hand. Crews get the wrong camera, the wrong size, or lose track of which
photo is which. Capture picks the camera by its van name (ROW, ForwardLeft, …),
always saves at the camera's real full size, never overwrites, and writes a log of
exactly what was grabbed.

## ⭐ MVP definition:
Version 1 (Phases 1–5) has exactly these features:
1. **Camera list** — cameras for this van, by name, with their capture port, serial
   and size. Sources, in this order:
   a. the van's ARAN SQL database (read only, through the existing `src/camera_db.py`);
   b. if the database can't be reached or has no cameras: an ARAN Settings XML file
      the user picks (e.g. `ARAN66_Settings_20260330.xml` from an end-of-day folder),
      read only;
   c. if neither: every video input Windows reports, by port name; the user types
      which camera it is.
   The log records which source named the camera.
2. **Live preview** of the chosen camera.
3. **Grab** a full-size photo three ways: a big Grab button, the Space bar, and a
   3-second countdown (so one person can hold the board).
4. **Save** as high-quality JPEG (quality 95) into a folder the user picks
   (remembered between sessions). File names are date-time stamped
   (`<Camera>_<YYYYMMDD_HHMMSS_mmm>.jpg`). Never overwrite: if a name exists, add
   `_2`, `_3`, ….
5. **Capture log** beside the photos, `CAPTURE_<YYYYMMDD_HHMMSS>.json`, one per
   session, never overwritten, appended after each grab (see Data).
6. **Busy camera**: first connect wins. If the input can't be opened or gives no
   frames, show in plain English: "ROW is busy or has no signal. Close ARAN
   collection or the other program using it, then press Try again." Never retry in
   a loop and never try to take the camera from another program.
7. **Any camera size.** Never assume 4K. The size to grab is, in order: the size in
   the database/Settings XML (`CCDWidth` × `CCDHeight`); otherwise the largest size
   the input reports. After opening, check the frame size actually delivered; if
   it differs from the expected size, show a warning (don't refuse) and log both.

## ⭐ Success criteria:
- On a van (ARAN69-SERVER, or ARAN99 for bench work): pick ROW from the database
  list, grab 30+ board photos, open that folder in the SurveyorCalibration app, and the
  lens grades PASS with every photo at the camera's full native size
  (3840×2160 for a 4K camera, 1920×1080 for an HD camera — whatever the camera is).
- Works the same with a 1920×1080 camera (e.g. RearLeft) as with a 3840×2160 one.
- When ARAN collection holds the camera, Capture shows the busy message and does
  not crash or hang (window stays responsive).
- All tests pass, including the fake-camera tests, on a PC with no capture card.

## ⭐ Explicit non-goals / out of scope:
- **Never change ARAN files**: no writes to ARAN settings, project files, its
  output folders (e.g. `\\<VAN>-SERVER\Removable1`) or logs.
- **Never write to the database.** Read only (`ApplicationIntent=ReadOnly`,
  `readonly=True`, SELECT only) — reuse `src/camera_db.py` as is.
- **Never change camera or capture-card settings** (exposure, gain, EDID, input
  source, firmware, LED). Only open, read frames, close.
- No calibration, grading or solving inside Capture (the calibration app does that).
- Not in v1: live board guidance, auto-grab, extrinsic (Old School) guidance,
  CoaXPress cameras, Magewell SDK signal status. These are later phases — keep the
  design open for them, don't build them early.
- No video recording; single still photos only.

## ⭐ Primary user / persona:
Field crew on the van — non-technical. Big clear buttons, plain English (grade 9),
no settings they can get wrong. Technical options (JPEG quality, countdown length,
grab key) live behind an "Advanced…" button.

## ⭐ Top user stories:
1. *Pick a camera.* As a crew member I pick "ROW" from a list and see its live
   picture. Accept: list shows names from the database (or Settings XML, or ports);
   preview appears within 5 s; size and serial shown under the picture.
2. *Grab.* I press Grab (or Space, or Countdown) and a photo is saved. Accept: file
   appears in the chosen folder at full native size, count goes up by one, a
   thumbnail of the last photo shows, the log has a new entry.
3. *Busy camera.* If ARAN is collecting, I'm told plainly and nothing breaks.
   Accept: busy message; "Try again" works once ARAN releases it.
4. *Hand over to calibration.* I press "Open in calibration app" and the
   SurveyorCalibration app opens with that folder. Accept: the folder path is passed on
   the command line; no other link between the programs.
5. *Find out later what happened.* Months later anyone can read the log and know
   which camera, port, serial, size, PC, app version and time each photo came from.

## ⭐ App type:
GUI desktop (PySide6), Windows. A separate program (own process, own exe) that
ships in the same installer as the SurveyorCalibration app.

## ⭐ Platform standards to follow:
- Read `docs/capture/standards/gui-coding-standards.md` and
  `docs/capture/standards/security-standards.md` before writing code.
- **Exception — colours:** use the app's existing dark palette and constants in
  `src/styles.py` (`build_dark_palette()`, `C_*`, `MARGIN`, `SPACING`, `BUTTON_H`),
  not the hex values in the standards file. Fusion style, like `main.py`.
- Layout approach: pure code (no Qt Designer `.ui` files), like the rest of the app.
- Every new QWidget subclass in `src/capture` uses the 5-method `__init__` pattern.
  (Older widgets in `src/widgets` may not; do not refactor them.)
- Dynamically generated widgets (factory + populate + clear): the camera list
  entries (`_create_camera_item`), and the recent-photo thumbnail strip
  (`_create_thumbnail_widget`).

## ⭐ Key screens / endpoints / commands:
One main window, `CaptureWindow` (`src/capture/window.py`):
- Top bar: Van (filled from the PC name, editable), Camera list, camera source
  label ("from the van database" / "from Settings XML …" / "from Windows ports"),
  "Load Settings XML…", "Try again".
- Centre: live preview, scaled to fit, never stretched (keep aspect ratio). Under it:
  camera, port, serial, expected size, delivered size, frames/s.
- Bottom: save-folder picker, photo count, big **Grab** button, **Countdown**
  button (shows 3-2-1 big over the preview), last-photo thumbnail strip,
  "Open in calibration app", "Advanced…".
- Status line for plain-English messages.
Command line: `SurveyorCapture.exe [--van ARAN69] [--camera ROW] [--folder <path>]`.
From source: `uv run python -m src.capture`.
The calibration app gets one button, "Collect photos…", that starts Capture as a
separate process (`QProcess.startDetached`); nothing else changes in the app.

## ⭐ Roles / permissions:
None. Anyone signed in to the van PC can use it. No admin rights needed to run.

## ⭐ Data to store + key rules:
- Photos: JPEG, quality 95 (Advanced setting), BGR frames saved with
  `cv2.imwrite` (or `cv2.imencode` + write, to handle non-ASCII paths), full native
  size, no resizing, cropping or filtering.
- Capture log `CAPTURE_<date>_<time>.json` (UTF-8, pretty printed), written next to
  the photos, never overwritten; rewritten atomically (write temp + rename) after
  each grab. Fields:
  `app_version` (reuse `src/version.app_version()`), `computer`, `van`,
  `camera`, `camera_source` (`database` / `settings_xml:<file>` / `user`),
  `port` (DirectShow name, e.g. `Video (01-1 Pro Capture Dual SDI 4K+)`),
  `serial` (TEXT — keep leading zeros, e.g. `0103043`), `expected_size`,
  `delivered_size`, `started`, and `photos`: list of
  `{file, time, width, height, countdown: bool}`.
- Settings (last folder, last van, JPEG quality, countdown seconds, grab key):
  `QSettings("SidewalkProfiler", "SurveyorCapture")`. No passwords stored by Capture —
  the database password, if any, stays in `src/camera_db.py`'s Windows-DPAPI store.
- Serials are text everywhere. Never convert to int.

## ⭐ Security & data handling:
- Threat model: protect the van's ARAN system (database, settings, collection) from
  being changed or disrupted, and keep any SQL password private. Trust boundaries:
  the database rows, the Settings XML file, DirectShow device names, folder paths
  typed or picked by the user.
- Database: read only, Windows sign-in by default, reuse `src/camera_db.py`
  unchanged (it already uses parameterless fixed SELECTs, ReadOnly intent, DPAPI
  password store). No new SQL.
- Settings XML: parse with `xml.etree.ElementTree` (no network, no DTD/entity
  expansion — reject the file if it contains `<!DOCTYPE`), cap file size at 10 MB,
  read only `VideoDeviceConfig-*` blocks (`CaptureView`, `CaptureDeviceName`,
  `CameraSerialNumber`, `CCDWidth`, `CCDHeight`), treat all values as text, strip
  and length-limit them (≤ 100 chars).
- File names: build from a camera name cleaned to `[A-Za-z0-9_-]`; never from raw
  input. Write only inside the chosen folder.
- No network access other than the SQL Server connection camera_db already makes.
- No secrets in code or repo. There is no `.env` in this project: the only secret
  (optional SQL password) is stored per user per PC with Windows DPAPI by camera_db.
- Errors shown to the crew in plain English; full details (traceback) go to the
  log file `%LOCALAPPDATA%\SurveyorCalibration\capture_errors.log` (append, rotate at
  5 MB). Never show or log a password or connection string with a password.

## ⭐ Integrations:
- **Capture cards (v1): Magewell Pro Capture Dual SDI 4K+** — appear in Windows as
  DirectShow video inputs named `Video (CC-N Pro Capture Dual SDI 4K+)` (CC = card
  number, N = input, from 0). Grab with OpenCV `cv2.VideoCapture(index,
  cv2.CAP_DSHOW)`. Pick the index by matching the DirectShow *name* (listed with
  comtypes, in DirectShow enumeration order) — never by a hard-coded number. Port
  numbers differ between vans (ROW is `01-1` on ARAN66, `02-1` on ARAN69).
  Request the expected size with `CAP_PROP_FRAME_WIDTH/HEIGHT` *before* the first
  read; then check what came back (OpenCV can silently fall back to 640×480).
  Pixel format: BGR24 if offered, otherwise let OpenCV convert.
- **ARAN collection software** opens the same inputs through DirectShow
  (`FRVideoCapture_x64.dll`, see the sample Video log) and holds them while it
  runs. First connect wins.
- **Van database** (MS SQL `<VAN>` on `<VAN>-SERVER`, table `VideoDeviceConfig`,
  columns `CaptureView, CameraSerialNumber, CCDWidth, CCDHeight, Enabled,
  CaptureDeviceName, VideoModuleName`) via `src/camera_db.py` (`lookup_cached`,
  `DbResult`, `CameraRow`). If `CameraRow` lacks the port, add a read-only
  `port` field to it and to its existing SELECT (the only allowed change to
  camera_db; keep its tests passing). `VideoModuleName` says which PC holds the
  card (e.g. `ARAN69-Server`); show a warning if it isn't this PC.
- **SurveyorCalibration app**: only through the photo folder and one launch button each
  way ("Collect photos…" → Capture; "Open in calibration app" → `SurveyorCalibration.exe
  --folder <path>` or `uv run python main.py --folder <path>`; add that small
  `--folder` option to `main.py` if missing).
- **Allowed shared imports (one way only):** Capture may import ONLY these
  existing modules: `src.camera_db`, `src.van_scan`, `src.version`, `src.styles`,
  `src.paths`, and — from the live-guidance phase on — `src.detector`, `src.board`,
  `src.boards`, `src.coverage`. Nothing in `src/` outside `src/capture` may import
  `src.capture` (except the one launch button, which starts a process and does not
  import it). A test enforces both rules.

## ⭐ Target OS and hardware:
- Windows 10/11 x64, van PCs `<VAN>-SERVER` (capture cards are on -SERVER on most
  vans; ARAN69's database says `ARAN69-Server`). Bench PC: ARAN99 (Magewell and
  BitFlow SDKs installed). Dev PC: DPDEV (no capture card — use the fake camera).
- Camera sizes vary: 3840×2160 and 1920×1080 seen so far; support any size.
- Display: van screens may be small; window must work at 1280×720 and scale up.

## ⭐ Version control and environment:
Git (`DerekFugro/020_Calabration`, branch `main`), uv with `requirements.txt`
(no pyproject). Commit with
`git -c user.email=dpescod@fugro.com commit -F ForClaude\commit_msg.txt`, then
push. Commit trailers as instructed by the session. Preserve existing line endings
(LF) when editing.

## ⭐ Preferred tech stack:
| Tool | Version | Why |
|---|---|---|
| Python | 3.12.10 | same as the app |
| PySide6 | 6.11.1 | same GUI toolkit, dark Fusion style |
| opencv-contrib-python | 5.0.0.93 (already installed) | DirectShow grab, JPEG write |
| numpy | 2.x (already installed) | frames |
| pyodbc | 5.4.0 | via `src/camera_db.py` only |
| comtypes | 1.4.x (NEW; verify latest at setup) | list DirectShow video input names in enumeration order (own ~50-line helper `src/capture/dshow_names.py`; MIT licence) |
| PyInstaller | 6.x | second exe `SurveyorCapture.exe` in the same build |
| Inno Setup | 6.7.3 | same Setup.exe, adds a Start-menu entry "SurveyorCapture" |
| pytest | 9.0.3 | tests with a fake camera |
Rejected: cv2-enumerate-cameras (GPL v3 — not for a company installer),
pygrabber (last release Oct 2023), Qt Multimedia `QCamera` (Media Foundation;
Magewell lists DirectShow only), Magewell MWCapture SDK in v1 (C only; kept for a
later optional phase via ctypes).

## ⭐ Testing approach:
pytest. Hardware is behind one small interface (`src/capture/source.py`):
```python
class FrameSource(Protocol):
    def open(self, port: str, width: int | None, height: int | None) -> OpenResult: ...
    def read(self) -> np.ndarray | None: ...      # BGR frame or None
    def close(self) -> None: ...
```
Implementations: `DShowSource` (OpenCV + DirectShow) and `FakeSource` (makes frames
of any size, can simulate busy / no signal / wrong size). All logic tests use
`FakeSource`. Hardware tests are marked `@pytest.mark.hardware` and skipped unless
`CAPTURE_HW=1`. Required tests: camera-list sources (database rows, Settings XML
sample, ports-only), name→index matching, size fallback and mismatch warning,
never-overwrite names, log contents and append, busy handling, the import-boundary
rule, 1920×1080 and 3840×2160 and an odd size (e.g. 2448×2048). The existing 216
tests must still pass.

## ⭐ Preferences and tradeoffs:
Simple, clear, safe. Plain English, grade 9, metric. Warn, never refuse (except
when the camera truly can't be opened). Keep Capture small and removable: deleting
`src/capture` (and the launch button) must leave the calibration app working.
Grabbing runs in a worker thread (`QThread`); the GUI never blocks on the camera.
Preview may be downscaled for display, but saved photos are always the full frame.

## ⭐ Reference material:
See `docs/capture/CONTEXT.md`. Authoritative: Magewell MWCaptureSDK 3.3.1.1596
Developer's Guide (SDK v3). Samples: ARAN66 Settings XML and Video log (EOD
20260330), ARAN69 camera table. Later phases: BitFlow and JAI manuals.

---

## Rules for the coding agent

- **Read the bundled platform standards file(s) named above before writing any
  code**, and follow them exactly (with the colour exception above).
  - GUI desktop: always dark mode; every QWidget subclass uses the 5-method
    `__init__` pattern (`_create_widgets`, `_create_layouts`, `_connect_signals`,
    `_apply_styles`, `_load_initial_state`); every widget has a named instance
    variable; no business logic in `_create_*` methods; dynamic widgets use
    factory + populate + clear.
  - Security: follow `security-standards.md` for any data, network, or user input.
- Ask if anything is unclear BEFORE starting — never assume silently.
- Never delete or overwrite existing files without explicit confirmation.
- Follow the phased plan in `docs/capture/Capture_Phase.md`.
- List required software and versions per phase.
- Between phases: run the full test suite, report results, and wait for "proceed".
  Do not advance if any test fails. Each phase must leave the codebase runnable.
  The proceed decision is made at the strongest tier (Opus 5), not delegated.
- Never work on two interdependent files simultaneously.
- If a dependency cannot be installed or versions conflict, STOP and report the
  exact error before continuing.
- If unsure whether a library is current or deprecated, web-search to verify
  before using it — version knowledge goes stale.
- No AI-generated placeholder data in production logic.
- Never hard-code secrets. Validate and sanitize all external input.
- Never touch a camera or capture card while ARAN collection is using it beyond a
  single open attempt; never change card or camera settings.
- Hardware tests on a van PC need Derek's OK each time.

## Agent routing hints (capability-based, with named defaults)

Route by capability tier so cost is saved on trivial work. The strongest tier is
the default and the supervisor. Model names change — pair the tier with the
current default model so this still works if a name goes stale.

*Model names verified July 2026 — if this spec is much older than that, confirm
the names below are still current before relying on them.*

| Tier | Default model | Model string | Use for |
|------|---------------|--------------|---------|
| Strongest | Claude Opus 5 | `claude-opus-5` | Architecture, spec review, security review, complex/cross-file debugging, phase-gate decisions |
| Mid | Claude Sonnet 5 | `claude-sonnet-5` | Feature implementation, boilerplate, refactoring, test writing |
| Cheapest | Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | Renames, formatting, trivial one-line edits |

- **When in doubt, use the strongest tier.** Lesser tiers take only genuinely
  trivial, easily-verified work.
- **Escalate on doubt.** If a lesser tier produces anything questionable, or a
  task is harder than it looked, hand it to the strongest tier.
- GUI layout generation and any security-sensitive change (database access,
  Settings XML parsing, file writing, hardware access) get a human review step
  before proceeding.

## First tasks when coding begins

1. Read `docs/capture/CONTEXT.md` to orient — what each folder holds, which
   reference material is authoritative, what to ignore, and what's sample input vs.
   deliverable. Keep it current as reference files are added or versions change.
2. Read `docs/capture/standards/gui-coding-standards.md` and
   `docs/capture/standards/security-standards.md`.
3. Read and list all required software, libraries, and extensions.
4. Web-search to verify current stable versions and mutual compatibility
   (especially comtypes with Python 3.12 and PyInstaller).
5. Confirm `src/capture` does not exist yet; create it.
6. Install dependencies (`uv pip install comtypes`, add `comtypes>=1.4` to
   `requirements.txt`).
7. No `.env` is needed (see Security). Confirm no secrets are added anywhere.
8. Report setup complete with a version summary, then wait for "proceed"
   before writing any application code.
