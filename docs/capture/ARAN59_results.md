# ARAN59 results — SurveyorCapture on a van with Magewell SDI cameras

**Where / when:** ARAN59-Server (the van's own PC, Windows user `dvs`), 2026-11-14.
Code run from source at `E:\DP\SurveyorCalibration` (not the installed build).
**Rules kept:** every camera opened read only (open, read, close), one at a time, with
Derek's OK; nothing set on any camera or card except the picture size Capture always asks
for. FR Video Service and FR VideoQC Service are installed here and were **stopped** the
whole time. No BitFlow card on this PC (Derek: focus on the Magewell cameras).

## The hardware
- **Two Magewell Pro Capture Dual SDI 4K+ cards** (4 SDI inputs), driver 1.3.0.4323
  (the version number the Magewell library reports). `LibMWCapture.dll` is in System32.
  | Card serial | Library board no. | Inputs |
  |---|---|---|
  | C127210609016 | 0 | 00-0, 00-1 |
  | C127210728030 | 1 | 01-0, 01-1 |
- **Windows input names** (DirectShow order = OpenCV index): 0 `Video (00-1 Pro Capture
  Dual SDI 4K+)`, 1 `00-0`, 2 `01-0`, 3 `01-1`, 4 `OBS Virtual Camera`. As on ARAN99, 00-1
  comes before 00-0: always find an input by name, never by number.
- **"BB-C" in the input name = the library's board and channel** (`00-1` = board 0,
  channel 1). Checked: the one input with no signal (00-1) is the one the database doesn't
  use. `src/capture/magewell.py` relies on this.

## The cameras (van database, newest configuration)
| Camera | Serial | Input | Database (ACS) size | Camera sends | Card scaling |
|---|---|---|---|---|---|
| ForwardRight | 102365 | 01-1 | 1920 × 1080 | 1920 × 1080 **interlaced**, 29.97 frames/s | none |
| ROW | 103032 | 01-0 | 1920 × 1080 | 1920 × 1080 **interlaced**, 29.97 frames/s | none |
| RearLeft | 101377 | 00-0 | 1920 × 1080 | 1920 × 1080 **interlaced**, 29.97 frames/s | none |
| (unused) | — | 00-1 | — | no signal | — |

All three are on this PC (database `VideoModuleName` = ARAN59-Server). All match ACS, so
Capture asks no scaling question on this van. "Camera sends" comes from the Magewell
library: total frame 2200 × 1125, frame time 333 667 × 100 ns = 29.97 frames/s, aspect
16:9 (i.e. 1080i59.94).

## Frame rate and reading speed
- **Counting frames (ROW, 10 s):** 300 frames = 30.0 frames/s, none missed, none repeated;
  31 ms between frames, never more than 47 ms. A 10 s count can't tell 30.00 from 29.97.
- **OpenCV can't report the frame rate** for these inputs (`CAP_PROP_FPS` = -1). Only
  counting, or the Magewell library, gives it.
- **The frame rate can't be changed:** broadcast cameras send what they are set to (1K or
  4K, 30-60 frames/s depending on the camera, Derek); the card only scales the picture to
  the size asked for.
- **Reading once a second gives a fresh frame:** after a 1 s pause `read()` returns at
  once (~3 ms) with the newest frame, and the next read waits for the camera (8-30 ms).
  One frame is kept, not a queue of old ones. So Capture reads Magewell inputs once a
  second (`source.READ_EVERY_S`); a Grab reads at once.
- **Interlaced:** with the board moving, an interlaced picture can show comb lines
  [inference: not seen yet, no board on the van that day]. Hold the board still.

## Checked with the new code (photos in the session scratchpad only)
| Check | Result |
|---|---|
| Capture, each of ROW, ForwardRight, RearLeft from the van database | Live; info line shows "camera sends 1920 x 1080i at 29.97 frames/s"; 5 reads in 5 s; no scaling question; one 1920 × 1080 photo saved and looked at. |
| ROW with 3840 × 2160 picked by hand (database off) | The card **upscales**: question popped up, answered No; warning shown; photo saved at 3840 × 2160; log has `scaling` with `crew_knew: false`. |
| Take 50 photos (ROW, count lowered to 5) | 5 photos 2 s apart (16:22:09-:17), all different frames. |
| Calibration app on made-up tilted board photos (board only near the middle) + 3 blank | NOT PASSED: "take another 50 photos. Missing: the board in 8 of 9 areas …; a steadier lens …"; **Take 50 more** shown; blanks to NotUsed. |
| Take 50 more → Capture | Real Capture started with `--van ARAN59 --camera ROW --add-to <folder>`; "Adding to:" that folder; ROW live. |
| Adding 5 ROW photos, then grading again | Photos went straight into the folder; graded again they went to NotUsed ("No board found": no board in view); NOT PASSED again with Take 50 more. |
| Made-up photos with no tilt at all | Hard stop (focal length not plausible): "Retake the photos", no Take 50 more button. |

**Not done here:** a real board (Derek was remote); the installed build; ARAN collecting
at the same time (FR Video Service was stopped), so "busy input" is still untested on a
Magewell van.

## Setting up this PC (2026-11-14)
- The folder was linked to GitHub with `git init` + `git reset origin/main` (no clone):
  same result, `main` tracks `origin/main`.
- **Python:** no Python on PATH (only the Microsoft Store alias). `uv venv --python 3.12`
  downloaded 3.12.16 but stopped with "Missing expected target directory for Python minor
  version link". Worked around by pointing uv at the downloaded `python.exe`
  (`C:\Users\dvs\AppData\Roaming\uv\python\cpython-3.12.16-windows-x86_64-none\python.exe`).
  Then `uv pip install -r requirements.txt`: PySide6 6.12.0, OpenCV 5.0.0, numpy 2.5.4.
  All tests pass. BFModule not installed (no BitFlow here).
- **Git:** no `C:\Users\dvs\.gitconfig` on this PC; name and email set for this repo only
  (`dapfromcanada`). The first push needs the GitHub sign-in window (Git Credential
  Manager), so run it in a real terminal, not a background job (that fails with "could
  not read Username"). The sign-in is now saved.
