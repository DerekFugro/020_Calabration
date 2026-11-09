# Implementation Plan for SurveyorCapture (SurveyorCalibration photo collection program)

> Gated phases. After each phase, run the full test suite, report results, and
> wait for "proceed". Do not advance if any test fails. Each phase must leave the
> codebase in a runnable state. The proceed decision is made at the strongest
> model tier (currently Claude Opus 5).
>
> Version 1 = Phases 1–5. Phases 6–9 are later; they are listed so the design
> leaves room for them — do not build them early.

## Phase 1 — Environment Setup + bench test
**Complexity:** Moderate
**Goal:** dependencies installed, and the three hardware unknowns answered on a real
Magewell PC before any GUI is written.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| Python | 3.12.10 | runtime |
| comtypes | 1.4.x (verify latest) | DirectShow device names |
| opencv-contrib-python | 5.0.0.93 | DirectShow grab |
| pytest | 9.0.3 | tests |

### Tasks
1. Read CONTEXT.md and both standards files. Add `comtypes>=1.4` to
   `requirements.txt`; install with `uv pip install -r requirements.txt`.
2. Write `src/capture/__init__.py` (empty) and `src/capture/dshow_names.py`:
   `video_inputs() -> list[str]` — DirectShow video input friendly names in
   enumeration order (ICreateDevEnum, CLSID_VideoInputDeviceCategory).
3. Write a read-only bench script `tools/capture_bench.py` (not part of the app)
   that, for each input: prints its name and index; opens it with `CAP_DSHOW`;
   requests the size given on the command line (or none); reads 10 frames;
   prints delivered size, frames/s, and how long open took; saves one JPEG to an
   output folder given on the command line; closes.
4. **With Derek's OK**, run it on ARAN99 (and later ARAN69-SERVER) while ARAN
   collection is NOT running, then again while ARAN holds the inputs. Record in
   `docs/capture/bench_results.md`:
   - Do OpenCV DSHOW indexes match the `video_inputs()` order? (name ↔ index)
   - Does each camera deliver its full native size (any size, e.g. 3840×2160,
     1920×1080)? What happens with no size requested?
   - Can a second program open an input ARAN already holds? (first connect wins —
     record what the failure looks like: open fails / black frames / timeout).
   - Which pixel formats are offered.
5. If any answer breaks the plan (e.g. index order doesn't match), STOP and report
   before Phase 2.

### Done when:
- [ ] `comtypes` installed; `requirements.txt` updated; existing tests pass.
- [ ] `bench_results.md` answers all four questions with real output from ARAN99.
- [ ] Derek has read the bench results and said "proceed".

---

## Phase 2 — Core logic (no GUI)
**Complexity:** Moderate
**Goal:** everything Capture does, testable without a camera.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| numpy | 2.x | frames |
| opencv-contrib-python | 5.0.0.93 | DShowSource, JPEG write |
| pyodbc | 5.4.0 | through camera_db only |

### Tasks
1. `src/capture/source.py`: `FrameSource` protocol, `OpenResult` (ok, message,
   delivered width/height), `DShowSource`, `FakeSource` (any size; can simulate
   busy, no signal, wrong size).
2. `src/capture/cameras.py`: `CaptureCamera` dataclass (`name, port, serial: str,
   width, height, source, pc`) and the three list sources:
   `from_database(van)` (via `src/camera_db.lookup_cached`; add a read-only
   `port` field to `CameraRow` and its SELECT if missing — only allowed change to
   camera_db), `from_settings_xml(path)` (safe parse rules in the Instructions),
   `from_ports()` (names from `dshow_names.video_inputs()`, user names them later).
   `resolve_index(port) -> int | None` matches by name.
3. `src/capture/sizes.py`: expected size = database/XML size, else largest
   reported; `size_warning(expected, delivered) -> str | None` (plain English).
4. `src/capture/saver.py`: safe file names `<Camera>_<YYYYMMDD_HHMMSS_mmm>.jpg`,
   never overwrite (`_2`, `_3`…), JPEG quality setting, full frame, non-ASCII-path
   safe write.
5. `src/capture/capture_log.py`: `CAPTURE_<date>_<time>.json`, atomic rewrite after
   each grab, fields as in the Instructions; serials kept as text.
6. `src/capture/errors.py`: append to `%LOCALAPPDATA%\SurveyorCalibration\capture_errors.log`,
   rotate at 5 MB, never log passwords.
7. Tests (all with `FakeSource`): list sources incl. the ARAN66 sample XML
   (copy only its four `VideoDeviceConfig-*` blocks into
   `tests/data/aran66_settings_cameras.xml`), name→index, sizes 1920×1080,
   3840×2160 and 2448×2048, mismatch warning, never-overwrite, log append,
   busy/no-signal handling, XML with `<!DOCTYPE` rejected, serial `0103043` kept.
8. `tests/test_capture_boundary.py`: scan imports — `src/capture` imports only the
   allowed `src.*` modules; nothing outside `src/capture` imports `src.capture`.

### Done when:
- [ ] All new tests and the existing 216 pass on DPDEV (no capture card).
- [ ] Boundary test passes.
- [ ] No GUI code yet; nothing in the calibration app changed except the optional
      `port` field in camera_db.

---

## Phase 3 — GUI (CaptureWindow)
**Complexity:** Complex
**Goal:** the crew can pick a camera, see it live, and grab.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| PySide6 | 6.11.1 | GUI |

### Tasks
1. `src/capture/grabber.py`: `GrabWorker(QThread)` — opens the source, emits
   preview frames (downscaled for display, max ~15 frames/s to the GUI), holds the
   latest full frame, saves on request, emits plain-English status. Never blocks
   the GUI. Closes the camera on window close.
2. `src/capture/window.py`: `CaptureWindow` with the layout in the Instructions
   (5-method pattern, named widgets, `src/styles.py` palette and constants).
   Dynamic widgets: `_create_camera_item`, `_create_thumbnail_widget` with
   populate/clear methods.
3. Grab three ways: Grab button, Space bar (configurable in Advanced), Countdown
   (3 s default, big 3-2-1 overlay). Disable Grab while saving; show count and
   last thumbnail.
4. Save folder picker (remembered in QSettings `SidewalkProfiler/SurveyorCapture`).
   If no folder is chosen, Grab asks for one first.
5. Busy/no-signal message + "Try again". Warning if `VideoModuleName` ≠ this PC.
6. "Advanced…" dialog: JPEG quality (80–100, default 95), countdown seconds
   (1–10, default 3), grab key.
7. `src/capture/__main__.py` + command line `--van --camera --folder`.
8. pytest-qt-free GUI smoke test: build the window with `FakeSource` offscreen
   (`QT_QPA_PLATFORM=offscreen`), grab 3 photos, check files and log.

### Done when:
- [ ] `uv run python -m src.capture` opens the window on DPDEV with the fake/no
      camera without errors.
- [ ] Offscreen GUI test passes; all tests pass.
- [ ] Human review of the layout (screenshot at 1280×720 and full screen) — Derek
      says it's clear for field crew.

---

## Phase 4 — Integration + packaging
**Complexity:** Moderate
**Goal:** Capture ships in the same Setup.exe and both programs launch each other.

### Dependencies
| Tool / Library | Version | Purpose |
|----------------|---------|---------|
| PyInstaller | 6.x | second exe |
| Inno Setup | 6.7.3 | installer |

### Tasks
1. Calibration app: one "Collect photos…" button (in the app window's top bar)
   that starts Capture with `QProcess.startDetached` (source run: same Python with
   `-m src.capture`; installed: `SurveyorCapture.exe` next to `SurveyorCalibration.exe`),
   passing `--van`. It must not import `src.capture`.
2. `main.py`: add `--folder <path>` to open the calibration app on a folder (if
   missing). Capture's "Open in calibration app" uses it.
3. `installer/SurveyorCalibration.spec`: add a second Analysis/EXE for
   `src/capture/__main__.py` named `SurveyorCapture`, sharing the same COLLECT folder
   (MERGE or one COLLECT with both EXEs) so libraries aren't duplicated.
4. `installer/SurveyorCalibration.iss`: Start-menu entry "SurveyorCapture"; optional desktop
   icon.
5. Build with `installer\build.ps1 -Test`; install on DPDEV; both exes start;
   buttons launch each other.

### Done when:
- [ ] Setup.exe installs both; both start; launch buttons work both ways.
- [ ] Removing `src/capture` (try on a scratch branch) leaves the calibration app
      starting and its tests passing (only the launch button reports Capture missing).
- [ ] All tests pass.

---

## Phase 5 — Field test (v1 acceptance)
**Complexity:** Moderate
**Goal:** prove the full loop on real vans.

### Tasks
1. With Derek's OK, install on ARAN99, then ARAN69-SERVER.
2. Pick ROW from the database list; grab 30+ board photos; open in the calibration
   app; lens must grade PASS at the camera's native size.
3. Repeat with a 1920×1080 camera (e.g. RearLeft) — 10+ photos at 1920×1080.
4. With ARAN collection running: Capture shows the busy message, stays responsive.
5. Database unreachable test: load an ARAN Settings XML; then ports-only mode.
6. Record results in `docs/capture/field_test_v1.md`.

### Done when:
- [ ] All success criteria in the Instructions met and recorded.
- [ ] Derek signs off v1. Commit, build Setup.exe, GitHub release (ask first).

---

## Phase 6 — Live board guidance (later)
**Complexity:** Complex
**Goal:** while previewing, show board found / 3×3 coverage filled / blur / count.
Uses `src.detector`, `src.board`, `src.boards`, `src.coverage` (allowed one-way
imports). Run detection on a downscaled copy in its own worker, at most ~2/s;
never slow the preview or the grab. Coverage counts grabbed photos only.
**Done when:** coverage shown matches what the calibration app reports for the same
folder; preview stays smooth on the van PC.

## Phase 7 — Magewell signal status (later, optional)
**Complexity:** Moderate
**Goal:** say "no signal on ROW" or show the input format before opening, using
`LibMWCapture.dll` (`MWCaptureInitInstance`, `MWRefreshDevice`,
`MWGetChannelCount`, `MWGetChannelInfoByIndex`, `MWOpenChannelByPath`,
`MWGetVideoSignalStatus`, `MWCloseChannel`, `MWCaptureExitInstance`) through
ctypes, read only. Fall back silently if the DLL isn't installed. Check the SDK
licence before shipping the DLL. Never call firmware, EDID, LED or input-source
setters.

## Phase 8 — Extrinsic (Old School) collection (later)
**Complexity:** Complex — spec separately with Derek (setups, site, GPS, naming).

## Phase 9 — CoaXPress cameras (later)
**Complexity:** Complex — BitFlow frame grabber + JAI Spark SP-45001-CXP2A, via the
BitFlow SDK, as a second `FrameSource`. Spec separately; manuals listed in CONTEXT.md.

---

## Agent routing per phase (capability-based, with named defaults)

Route by tier; the strongest tier is the default and supervisor. Pair the tier
with the current default model so this survives model renames.

*Model names verified July 2026 — confirm they are still current if this spec
is much older than that.*

| Tier | Default model | Model string | Use for |
|------|---------------|--------------|---------|
| Strongest | Claude Opus 5 | `claude-opus-5` | Architecture, spec review, security review, complex/cross-file debugging, phase-gate decisions |
| Mid | Claude Sonnet 5 | `claude-sonnet-5` | Feature implementation, boilerplate, refactors, test writing |
| Cheapest | Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | Renames, formatting, trivial one-line edits |

| Phase | Recommended tier (current default) |
|-------|-----------------------------------|
| 1 — Environment Setup + bench test | strongest (Opus 5 / `claude-opus-5`) — hardware on a van PC |
| 2 — Core logic | mid (Sonnet 5 / `claude-sonnet-5`); strongest for camera_db change and XML parsing (security) |
| 3 — GUI | mid (Sonnet 5) + human review step |
| 4 — Integration + packaging | mid (Sonnet 5) |
| 5 — Field test | strongest (Opus 5) + Derek |
| 6–9 — Later phases | strongest (Opus 5) for design, mid for implementation |
| Trivial mechanical edits (any phase) | cheapest (Haiku 4.5 / `claude-haiku-4-5-20251001`) |
| Phase-gate decisions (every phase) | strongest (Opus 5) — never delegated |

When in doubt, use the strongest tier. Escalate anything questionable.

---

## Total estimate
| Phase | Complexity |
|-------|------------|
| 1 — Environment Setup + bench test | Moderate |
| 2 — Core logic | Moderate |
| 3 — GUI | Complex |
| 4 — Integration + packaging | Moderate |
| 5 — Field test | Moderate |
| 6 — Live board guidance (later) | Complex |
| 7 — Magewell signal status (later) | Moderate |
| 8 — Extrinsic collection (later) | Complex |
| 9 — CoaXPress (later) | Complex |
