# Field test v1 — SurveyorCapture (Phase 5)

Results are filled in as each step is done. "Checked" means run on the real PC with the
installed program and the screen looked at (screenshots in `E:\SurveyorCalibration\_check`).

## Installed build
| PC | Version | Installed | By |
|----|---------|-----------|----|
| ARAN99-SERVER (bench) | 2026.11.14-1699e79 | 2026-11-14 03:06, Setup.exe, no restart | Claude, Derek OK'd the admin prompt |
| ARAN69-SERVER | — | — | — |

Note: the "SurveyorCapture is not installed" message (commit 5c8b007) is in the source,
not yet in the installed build. Rebuild Setup.exe before the van install.

## Done on ARAN99 (2026-11-14, no cameras plugged in)
| Step | Result |
|------|--------|
| Start screen → Collect lens photos | PASS. Starts `SurveyorCapture.exe --van ARAN99` from Program Files. |
| Capture → Open in calibration app | PASS. Opens `SurveyorCalibration.exe --folder <photos>` on Load Intrinsic. |
| Camera list from the database | PASS. ForwardRight 123456789 (00-0), ROW 88888888 (00-1), Right (BitFlow: "not supported yet", greyed). |
| 5a. Database unticked (`--no-db`) | PASS. List = the Windows inputs: 00-1, 00-0, OBS Virtual Camera. Label asks the crew to say which camera and type the serial. |
| 5b. Database unreachable (van ARAN54, no ARAN54-SERVER) | PASS. Message: could not read the van database (not on network / not allowed), using Windows inputs. Same 3 inputs. **Bug found and fixed:** the long message widened the window to 1664 px; it now wraps (test added). |
| Calibration app with Capture removed (scratch copy) | PASS. 242 tests pass; main window opens; button says Capture is not installed. |
| Built app OpenSSL | Fixed: build took Git's libssl and the app crashed opening the main window. Spec now uses Python's copy and stops if any DLL comes from Git. |

## Still to do (needs cameras / a van)
Plug in before starting: a camera (or any HDMI source) on Magewell **00-0**, and the
POS LV if it is part of the same session.

1. **Which input is which** (Phase 1, question 1). HDMI source on 00-0 only. In
   Capture pick ForwardRight (00-0): the live picture must be the source, not the
   colour bars. Then pick ROW (00-1): colour bars + "no signal" message, Grab refused.
2. **Native size** (Phase 1, question 2). With a real camera: the window info line
   shows the size delivered. Must equal the database size (1920x1080 on ARAN99), no
   "wrong size" warning.
3. **Lens loop** (Phase 5, steps 2–3). Pick the camera, grab 30+ board photos (3x3
   coverage, tilts), Open in calibration app, pick the camera in the bar (serial fills
   in), Run. Must grade PASS. Check the PDF, the .yaml/.txt outputs and `capture_log`.
4. **Busy** (Phase 1 question 3, Phase 5 step 4). On a van where ARAN collects through
   the Magewell card (ARAN69): start a collection, then open the same camera in
   Capture. Expect the busy message, window stays responsive, ARAN keeps collecting.
   **Ask Derek before this one** — it touches a live collection.
5. **Pixel formats** (Phase 1 question 4). Optional; Phase 7 can read them through the
   Magewell SDK.

## Software found on ARAN99 (read only, for later phases)
| What | Version | Where | Use |
|------|---------|-------|-----|
| Magewell Pro Capture driver | 1.3.0.4323 (2022-10-18) | Windows driver | Phase 7 |
| Magewell MWCapture SDK `LibMWCapture.dll` | 3.3.1.1596 | System32 + SysWOW64 (installed with the driver / Capture Express) | Phase 7: load it from System32, so the DLL need not ship with Setup.exe. Licence still to read. |
| Magewell Capture Express | 3.3.1.17419 | Program Files\Magewell | — |
| BitFlow SDK | 6.5 | `C:\BitFlow SDK 6.5` (Bin64, Include, Lib64, Examples, Docs\SDKLicense.txt; no Python wrapper) | Phase 9 |
| eBUS SDK for JAI / JAI GenICam firmware tool | 6.6.1.7475 / 1.0.8 | — | Phase 9 |

Phase 9 note: the camera on ARAN99's BitFlow card is a **GOX** (`0-GOX-16205C-CXP`),
not the JAI Spark the plan names. Phase 9's spec should cover both.

## Sign-off
- [ ] All steps above PASS and recorded.
- [ ] Derek signs off v1. Then build Setup.exe and a GitHub release (ask first).
