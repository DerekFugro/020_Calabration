"""html_report.py — one HTML page per camera for the office to check before loading.

Everything is in the one file (photos built in), so it can be emailed or opened from
the share.  A big PASS / FAIL at the top, then plain-words checks with a tick or a
cross, then the numbers, then one small photo per setup (click to enlarge) with the
found targets drawn on it.
"""

from __future__ import annotations

import base64
import html
import os
from pathlib import Path

import cv2
import numpy as np

from src.extrinsic.run import MAX_LOO_MM, MIN_SETUPS, MIN_TARGETS

OK, BAD, WARN = "ok", "bad", "warn"


def _jpeg(img, width: int, q: int) -> str:
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _photo_width(cam) -> int | None:
    for s in cam.setups:
        p = s.setup.photo
        if p and os.path.exists(p):
            im = cv2.imread(p, cv2.IMREAD_REDUCED_GRAYSCALE_8)
            if im is not None:
                return im.shape[1] * 8
    return None


def checks(cam, site, serial: str, intrinsic=None) -> list[tuple[str, str, str]]:
    """(state, what, detail) — the list the office reads."""
    out = []
    gcp = sorted(Path(site.folder).glob("*.gcp"))
    out.append((OK, "Correct GCP file used",
                f"{site.name}: {gcp[0].name if gcp else 'built in'} (built into the app, can't be swapped)"))

    # lens file
    if intrinsic is None:
        out.append((WARN, "Lens file", "Not recorded"))
    else:
        if intrinsic.graded_pass:
            out.append((OK, "Lens file passed the app's lens check", intrinsic.source))
        else:
            out.append((WARN, "Lens file not checked by this app", intrinsic.source))
        if intrinsic.serial and serial and intrinsic.serial.strip() != serial.strip():
            out.append((BAD, "Lens file is for a different camera",
                        f"Lens file serial {intrinsic.serial}, this camera {serial}"))
        w = _photo_width(cam)
        if w and cam.K is not None and abs(cam.K[0, 2] - w / 2) > 0.1 * w:
            out.append((BAD, "Lens file is the wrong size for these photos",
                        f"Photos are {w} px wide; the lens file centre is at {cam.K[0, 2]:.0f} px"))

    # camera name
    name_warn = [x for x in cam.warnings if "points" in x and ("folder says" in x or "not in the folder" in x)]
    out.append((BAD, "Camera name doesn't match where it points", name_warn[0]) if name_warn
               else (OK, "Camera name matches where it points",
                     f"{cam.camera}, points {cam.pan_tilt_roll[0]:.0f} deg" if np.isfinite(cam.pan_tilt_roll[0]) else cam.camera))

    # targets
    solved = [s for s in cam.setups if s.solve is not None]
    out.append((OK if solved else BAD, "Targets found and labelled by the app",
                f"{len(solved)} of {len(cam.setups)} setups"))

    used = [s for s in cam.setups if s.passed]
    out.append((OK if len(used) >= MIN_SETUPS else BAD, "Enough good setups",
                f"{len(used)} used, {len(cam.setups) - len(used)} dropped (need {MIN_SETUPS}; each needs "
                f"{MIN_TARGETS}+ targets within {MAX_LOO_MM:g} mm)"))
    for r in cam.reasons:
        if not r.startswith("Only "):
            out.append((BAD, r, ""))
    return out


CSS = """
:root{--ink:#1d2329;--muted:#5b6670;--line:#d9dee3;--bg:#f4f6f8;--card:#fff;
--ok:#1e7b34;--okbg:#e6f4ea;--bad:#b3261e;--badbg:#fbe9e7;--warn:#9a6700;--warnbg:#fff4d6}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 Segoe UI,Arial,sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
.banner{border-radius:10px;padding:18px 22px;color:#fff;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.banner.ok{background:var(--ok)}.banner.bad{background:var(--bad)}
.banner .big{font-size:40px;font-weight:800;letter-spacing:1px}.banner .who{font-size:18px;text-align:right}
.head{margin:8px 0 0;font-size:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin-top:14px}
h2{font-size:17px;margin:0 0 10px}
.chk{display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--line)}.chk:first-of-type{border-top:0}
.ic{flex:0 0 26px;height:26px;border-radius:50%;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center}
.ok .ic{background:var(--ok)}.bad .ic{background:var(--bad)}.warn .ic{background:var(--warn)}
.chk b{display:block}.chk span{color:var(--muted);font-size:13px;word-break:break-all}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:6px 8px;border-top:1px solid var(--line);font-size:14px}
th{color:var(--muted);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.ph{border:2px solid var(--line);border-radius:8px;overflow:hidden;background:#fff;cursor:zoom-in}
.ph.ok{border-color:var(--ok)}.ph.bad{border-color:var(--bad)}
.ph img{width:100%;display:block}.ph div{padding:6px 8px;font-size:13px}
.tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:12px;font-weight:700}
.tag.ok{background:var(--okbg);color:var(--ok)}.tag.bad{background:var(--badbg);color:var(--bad)}
.why{color:var(--bad)}
#big{position:fixed;inset:0;background:rgba(0,0,0,.88);display:none;overflow:auto;cursor:zoom-out;z-index:9}
#big img{display:block;max-width:none;width:100%;min-width:900px;margin:0 auto}
#big.zoom img{width:250%}
.foot{color:var(--muted);font-size:12px;margin:14px 0 30px}
@media (max-width:600px){.banner .big{font-size:30px}.banner .who{text-align:left}}
"""

JS = """
const big=document.getElementById('big'),bi=big.querySelector('img');
document.querySelectorAll('.ph').forEach(p=>p.onclick=()=>{bi.src=p.dataset.full;big.className='';big.style.display='block'});
big.onclick=e=>{if(big.className==='zoom'){big.style.display='none';big.className=''}else{big.className='zoom'}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){big.style.display='none';big.className=''}});
"""


def write_html(cam, site, data: dict, path: Path, serial: str, intrinsic=None, overlays: dict | None = None) -> None:
    e = html.escape
    cks = checks(cam, site, serial, intrinsic)
    passed = cam.passed and not any(s == BAD for s, _, _ in cks)
    sym = {OK: "&#10003;", BAD: "&#10007;", WARN: "!"}
    ck_html = "".join(f'<div class="chk {s}"><div class="ic">{sym[s]}</div><div><b>{e(w)}</b>'
                      f'<span>{e(d)}</span></div></div>' for s, w, d in cks)

    la = data["lever_arm_m"]; pt = data["pointing_deg"]
    nums = [("Pan (right +)", f'{pt["pan_right"]:.2f} deg'), ("Tilt (up +)", f'{pt["tilt_up"]:.2f} deg'),
            ("Roll", f'{pt["roll_cw"]:.2f} deg'), ("Setups agree within", f'{pt["spread_between_setups_max"]:.2f} deg'),
            ("Height above pavement", f'{la["up_above_pavement"]:.3f} m'),
            ("Height agrees within", f'{la["up_spread"] * 1000:.0f} mm'),
            ("Forward / right of GPS (rough)", f'{la["forward"]} / {la["right"]} m')]
    num_html = "".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in nums)

    rows, cards = [], []
    overlays = overlays or {}
    for s in cam.setups:
        sol = s.solve
        st = OK if s.passed else BAD
        why = "; ".join(p for p in s.problems if not p.startswith("target "))[:200]
        rows.append(f'<tr><td>{e(s.setup.name)}</td><td><span class="tag {st}">{"USED" if s.passed else "DROPPED"}</span></td>'
                    f'<td>{sol.n_points if sol else 0}</td><td>{f"{sol.loo_rms_mm:.1f}" if sol else "-"}</td>'
                    f'<td>{getattr(s, "ground_targets", 0)}{" &#10003;" if getattr(s, "counts_for_height", False) else ""}</td>'
                    f'<td class="why">{e(why)}</td></tr>')
        img = overlays.get(s.setup.name)
        if img is not None:
            cards.append(f'<div class="ph {st}" data-full="{_jpeg(img, 2400, 80)}"><img src="{_jpeg(img, 640, 70)}" alt="">'
                         f'<div><b>{e(s.setup.name)}</b> <span class="tag {st}">{"USED" if s.passed else "DROPPED"}</span> '
                         f'{sol.n_points if sol else 0} targets</div></div>')

    title = f'{data["van"]} {data["camera"]} {serial}'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} camera position check</title>
<style>{CSS}</style></head><body><div class="wrap">
<div class="banner {'ok' if passed else 'bad'}"><div class="big">{'PASS' if passed else 'NOT PASSED'}</div>
<div class="who"><b>{e(data["van"])} &middot; {e(data["camera"])}</b><br>Serial {e(serial)} &middot; {e(data["created"][:16].replace("T", " "))}</div></div>
<p class="head">{e(cam.headline)} {'Safe to load.' if passed else 'Do not load. Fix the items with a red cross first.'}</p>
<div class="card"><h2>Checks</h2>{ck_html}</div>
<div class="card"><h2>Result</h2><table>{num_html}</table></div>
<div class="card"><h2>Setups</h2><table><tr><th>Setup</th><th></th><th>Targets</th><th>Miss mm</th><th>Tennis balls (&#10003; = used for height)</th><th>Why dropped</th></tr>{''.join(rows)}</table></div>
<div class="card"><h2>Photos</h2><p style="margin:0 0 10px;color:var(--muted);font-size:13px">Green = target found and used (number, miss in mm). Red = found but left out. Orange = should be there but not found. Click a photo to enlarge; click again to zoom.</p><div class="grid">{''.join(cards) or 'No photos.'}</div></div>
<div class="foot">Made by 020_Calabration. Folder: {e(str(cam.folder))}</div>
</div><div id="big"><img alt=""></div><script>{JS}</script></body></html>"""
    path.write_text(page, encoding="utf-8")
