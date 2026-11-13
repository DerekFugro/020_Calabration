# Bench results — Phase 1 (SurveyorCapture)

**Where / when:** ARAN99-SERVER (bench PC), 2026-11-13 ~16:55, `tools/capture_bench.py`
(read only: open, read 10 frames, save one JPEG, close; no settings changed).
**Hardware:** Magewell **Pro Capture Dual HDMI 4K+** (HDMI, not the SDI model the spec
names), **nothing plugged into either input**. The bench PC's GOX cameras are on the
BitFlow CoaXPress card (Phase 9), which DirectShow does not see.
**ARAN:** FR Video Service, FR Poslv Service running (FR.Subsystems.Video.Module up);
FR VideoQC Service stopped.

## Raw output
```
3 video inputs (DirectShow order = cv2.CAP_DSHOW index):
  0: Video (00-1 Pro Capture Dual HDMI 4K+)
  1: Video (00-0 Pro Capture Dual HDMI 4K+)
  2: OBS Virtual Camera
no size requested: 00-1 and 00-0 opened in 0.07-0.2 s, 10/10 frames, ~30 fps, delivered 640x480
3840x2160 requested: both delivered 3840x2160, 10/10 frames, ~28 fps
1920x1080 requested (00-0): delivered 1920x1080, ~29.5 fps
OBS Virtual Camera: did not open (OpenCV: "can't be used to capture by index")
FOURCC reported: not a real code (OpenCV hands back converted BGR frames)
```

## The four questions
1. **OpenCV DSHOW index ↔ `video_inputs()` order — NOT ANSWERED yet.** The order
   lists **00-1 before 00-0**, so numbers must never be assumed (as the spec says).
   With no signal both inputs show the same picture, so which index is which input
   can't be seen. Needs a source on one input (e.g. a laptop's HDMI into 00-0).
2. **Full native size — partly.** The card delivers **whatever size is asked**
   (640x480, 1920x1080, 3840x2160 all came back as asked). With **no size asked it
   silently gives 640x480** — so Capture must always ask for the expected size
   (database/XML), exactly as the spec says. A camera's real native size can only be
   checked with a camera on the input (a van, e.g. ARAN69).
3. **Busy (ARAN holds the input) — NOT TESTED here.** With FR Video Service running,
   both inputs still opened at once: on this PC ARAN's video module does not use the
   Magewell inputs (its cameras are on BitFlow). Needs a van where ARAN collects
   through the Magewell card.
4. **Pixel formats offered — NOT ANSWERED.** OpenCV does not list them (the FOURCC it
   reports is not a real code). Needs DirectShow `IAMStreamConfig` (or the Magewell
   SDK, Phase 7). Not needed for v1: OpenCV converts to BGR.

## New finding that changes the plan
**With no signal the card sends a full-size "No Signal" colour-bar picture** (white,
yellow, cyan, green, magenta, red, blue, black bars with a "No Signal" box), at
whatever size was asked, ~30 fps. Capture would happily save it as a lens photo.
→ Phase 2 adds a **no-signal check** on the frame (the 8 bar colours at fixed
positions) and Capture refuses to grab it, telling the crew in plain words:
"ROW: no signal from the camera (the card shows its colour bars). Check the cable
and that the camera is on." The Magewell SDK (Phase 7) could replace this later.
