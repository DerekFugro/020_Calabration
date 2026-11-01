"""export_formats.py — write one intrinsic calibration in every format we know.

All writers take the same `Intrinsics` record.  Pixel units throughout; the
OpenCV Brown-Conrady model (k1 k2 p1 p2 k3) is the source of truth.

Formats
  fleet XML      <VAN>_<Camera>_<Serial>_intrinsic_cal.xml  (what the fleet files today)
  PG RWC         PGInteriorCalibration_<...>.RWC            (old exe / processing import)
  OpenCV YAML    cv::FileStorage YAML (camera_matrix, distortion_coefficients)
  OpenCV XML     cv::FileStorage XML, same content
  ROS            camera_info YAML (plumb_bob), used by ROS / ROS 2 camera drivers
  Kalibr         camchain YAML (pinhole-radtan)
  COLMAP         cameras.txt, FULL_OPENCV model
  Metashape      Agisoft calibration XML (frame camera)
  JSON           every field, plain
  CSV            one summary row

Mappings that are NOT verified against the receiving software are listed in
UNVERIFIED and printed into the README written next to the files.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

PIXEL_SIZE_MM = 0.0036   # what every PGInteriorCalibration RWC on file uses

UNVERIFIED = {
    "PG RWC": "Distortion written as OpenCV k1 k2 k3 / p1 p2 (TangentialDistorsion3 = 0). "
              "Old RWC values look like OpenCV numbers but this has not been proven "
              "by processing one of our files.",
    "Metashape": "Agisoft swaps the tangential terms (Metashape P1 = OpenCV p2, "
                 "P2 = p1) and stores cx/cy as offsets from the image centre.  "
                 "From documentation, not tested in Metashape.",
}


@dataclass
class Intrinsics:
    van: str            # ARAN65
    camera: str         # ForwardRight
    serial: str         # 101324
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    k1: float
    k2: float
    p1: float
    p2: float
    k3: float
    rms_px: float = float("nan")
    passed: bool | None = None
    grade_headline: str = ""
    repeat_10m_mm: float | None = None
    images_used: int = 0
    board: str = ""
    date: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_result(cls, cal, van: str, camera: str, serial: str,
                    board: str = "", date: datetime | None = None) -> "Intrinsics":
        K = cal.camera_matrix
        d = list(cal.dist_coeffs.ravel()) + [0.0] * 5
        g = getattr(cal, "grade", None)
        rp = getattr(g, "repeatability", None) if g else None
        return cls(van=van, camera=camera, serial=str(serial),
                   width=int(cal.image_size[0]), height=int(cal.image_size[1]),
                   fx=float(K[0, 0]), fy=float(K[1, 1]),
                   cx=float(K[0, 2]), cy=float(K[1, 2]),
                   k1=float(d[0]), k2=float(d[1]), p1=float(d[2]),
                   p2=float(d[3]), k3=float(d[4]),
                   rms_px=float(cal.rms),
                   passed=None if g is None else bool(g.passed),
                   grade_headline="" if g is None else g.headline,
                   repeat_10m_mm=None if rp is None else float(rp.at_10m_mm),
                   images_used=int(cal.image_count_used), board=board,
                   date=date or datetime.now())

    @property
    def stem(self) -> str:
        return f"{self.van}_{self.camera}_{self.serial}"


# ── Writers (each returns the text it writes) ───────────────────────────────

def fleet_xml(c: Intrinsics) -> str:
    iso = c.date.astimezone().isoformat()
    return (
        "<IntrinsicCalibration>\n"
        f"  <VehicleName>{escape(c.van)}</VehicleName>\n"
        f"  <CameraName>{escape(c.camera)}</CameraName>\n"
        f"  <SerialNumber>{escape(c.serial)}</SerialNumber>\n"
        f"  <CalibrationDate>{iso}</CalibrationDate>\n"
        f"  <MeanSquareError>{c.rms_px:.4f}</MeanSquareError>\n"
        f"  <NormalizedError>{c.rms_px / max(c.fx, 1e-9):.4f}</NormalizedError>\n"
        f'  <OpenCVCameraModel width="{c.width}" height="{c.height}">\n'
        f'    <Center x="{c.cx!r}" y="{c.cy!r}" />\n'
        f'    <FocalLength x="{c.fx!r}" y="{c.fy!r}" />\n'
        f'    <RadialDistortion k1="{c.k1!r}" k2="{c.k2!r}" k3="{c.k3!r}" />\n'
        f'    <TangentialDistortion p1="{c.p1!r}" p2="{c.p2!r}" />\n'
        "  </OpenCVCameraModel>\n"
        "</IntrinsicCalibration>"
    )


def pg_rwc(c: Intrinsics) -> str:
    hdr = ("IDPGInteriorCalibration,CameraSerialNumber,EffectiveDate,FocalLength,"
           "PixelHeight,PixelWidth,PrincipalPointX,PrincipalPointY,RadialDistorsion1,"
           "RadialDistorsion2,RadialDistorsion3,TangentialDistorsion1,"
           "TangentialDistorsion2,TangentialDistorsion3")
    date = f"{c.date.month}/{c.date.day}/{c.date.year} {c.date.strftime('%I:%M %p').lstrip('0')}"
    f = (c.fx + c.fy) / 2
    row = [1, 1, date, repr(f), PIXEL_SIZE_MM, PIXEL_SIZE_MM, repr(c.cx), repr(c.cy),
           repr(c.k1), repr(c.k2), repr(c.k3), repr(c.p1), repr(c.p2), 0]
    return hdr + "\r\n" + ",".join(str(v) for v in row)


def _fs_matrix(name, rows, cols, data, xml=False):
    vals = ", ".join(repr(float(v)) for v in data)
    if xml:
        return (f"<{name} type_id=\"opencv-matrix\">\n  <rows>{rows}</rows>\n"
                f"  <cols>{cols}</cols>\n  <dt>d</dt>\n  <data>\n    "
                + " ".join(repr(float(v)) for v in data) + f"</data></{name}>\n")
    return (f"{name}: !!opencv-matrix\n   rows: {rows}\n   cols: {cols}\n"
            f"   dt: d\n   data: [ {vals} ]\n")


def _K(c):
    return [c.fx, 0, c.cx, 0, c.fy, c.cy, 0, 0, 1]


def _D(c):
    return [c.k1, c.k2, c.p1, c.p2, c.k3]


def opencv_yaml(c: Intrinsics) -> str:
    return ("%YAML:1.0\n---\n"
            f"calibration_time: \"{c.date:%Y-%m-%d %H:%M:%S}\"\n"
            f"image_width: {c.width}\nimage_height: {c.height}\n"
            f"camera_name: \"{c.stem}\"\n"
            + _fs_matrix("camera_matrix", 3, 3, _K(c))
            + _fs_matrix("distortion_coefficients", 1, 5, _D(c))
            + f"avg_reprojection_error: {c.rms_px!r}\n")


def opencv_xml(c: Intrinsics) -> str:
    return ('<?xml version="1.0"?>\n<opencv_storage>\n'
            f"<calibration_time>\"{c.date:%Y-%m-%d %H:%M:%S}\"</calibration_time>\n"
            f"<image_width>{c.width}</image_width>\n<image_height>{c.height}</image_height>\n"
            f"<camera_name>{escape(c.stem)}</camera_name>\n"
            + _fs_matrix("camera_matrix", 3, 3, _K(c), xml=True)
            + _fs_matrix("distortion_coefficients", 1, 5, _D(c), xml=True)
            + f"<avg_reprojection_error>{c.rms_px!r}</avg_reprojection_error>\n"
            "</opencv_storage>\n")


def ros_yaml(c: Intrinsics) -> str:
    def m(rows, cols, data):
        return (f"  rows: {rows}\n  cols: {cols}\n  data: ["
                + ", ".join(repr(float(v)) for v in data) + "]\n")
    P = [c.fx, 0, c.cx, 0, 0, c.fy, c.cy, 0, 0, 0, 1, 0]
    return (f"image_width: {c.width}\nimage_height: {c.height}\n"
            f"camera_name: {c.stem.lower()}\n"
            "camera_matrix:\n" + m(3, 3, _K(c))
            + "distortion_model: plumb_bob\n"
            "distortion_coefficients:\n" + m(1, 5, _D(c))
            + "rectification_matrix:\n" + m(3, 3, [1, 0, 0, 0, 1, 0, 0, 0, 1])
            + "projection_matrix:\n" + m(3, 4, P))


def kalibr_yaml(c: Intrinsics) -> str:
    return ("cam0:\n  camera_model: pinhole\n"
            f"  intrinsics: [{c.fx!r}, {c.fy!r}, {c.cx!r}, {c.cy!r}]\n"
            "  distortion_model: radtan\n"
            f"  distortion_coeffs: [{c.k1!r}, {c.k2!r}, {c.p1!r}, {c.p2!r}]\n"
            f"  resolution: [{c.width}, {c.height}]\n"
            f"  rostopic: /{c.camera.lower()}/image_raw\n"
            "  # Kalibr radtan has no k3; k3 = " + repr(c.k3) + " is dropped here.\n")


def colmap_txt(c: Intrinsics) -> str:
    p = [c.fx, c.fy, c.cx, c.cy, c.k1, c.k2, c.p1, c.p2, c.k3, 0.0, 0.0, 0.0]
    return ("# Camera list with one line of data per camera:\n"
            "#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n"
            "# FULL_OPENCV: fx, fy, cx, cy, k1, k2, p1, p2, k3, k4, k5, k6\n"
            f"1 FULL_OPENCV {c.width} {c.height} " + " ".join(repr(float(v)) for v in p) + "\n")


def metashape_xml(c: Intrinsics) -> str:
    b1 = c.fx - c.fy   # Metashape affinity: fx = f + b1, fy = f
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<calibration>\n'
            "  <projection>frame</projection>\n"
            f"  <width>{c.width}</width>\n  <height>{c.height}</height>\n"
            f"  <f>{c.fy!r}</f>\n"
            f"  <cx>{c.cx - c.width / 2!r}</cx>\n  <cy>{c.cy - c.height / 2!r}</cy>\n"
            f"  <b1>{b1!r}</b1>\n"
            f"  <k1>{c.k1!r}</k1>\n  <k2>{c.k2!r}</k2>\n  <k3>{c.k3!r}</k3>\n"
            f"  <p1>{c.p2!r}</p1>\n  <p2>{c.p1!r}</p2>\n"
            f"  <date>{c.date:%Y-%m-%dT%H:%M:%SZ}</date>\n"
            "</calibration>\n")


def json_text(c: Intrinsics) -> str:
    d = asdict(c)
    d["date"] = c.date.isoformat()
    d["camera_matrix"] = [_K(c)[0:3], _K(c)[3:6], _K(c)[6:9]]
    d["distortion_opencv"] = _D(c)
    return json.dumps(d, indent=2)


CSV_COLS = ["van", "camera", "serial", "width", "height", "fx", "fy", "cx", "cy",
            "k1", "k2", "p1", "p2", "k3", "rms_px", "repeat_10m_mm", "passed",
            "images_used", "board", "date"]


def csv_text(c: Intrinsics) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLS)
    d = asdict(c); d["date"] = c.date.isoformat()
    w.writerow([d[k] for k in CSV_COLS])
    return buf.getvalue()


# name -> (filename pattern, writer)
FORMATS = {
    "fleet XML":   ("{stem}_intrinsic_cal.xml", fleet_xml),
    "PG RWC":      ("PGInteriorCalibration_{serial}_{dt}.RWC", pg_rwc),
    "OpenCV YAML": ("{stem}_opencv.yml", opencv_yaml),
    "OpenCV XML":  ("{stem}_opencv.xml", opencv_xml),
    "ROS":         ("{stem}_ros_camera_info.yaml", ros_yaml),
    "Kalibr":      ("{stem}_kalibr_camchain.yaml", kalibr_yaml),
    "COLMAP":      ("{stem}_colmap_cameras.txt", colmap_txt),
    "Metashape":   ("{stem}_metashape.xml", metashape_xml),
    "JSON":        ("{stem}_intrinsic.json", json_text),
    "CSV":         ("{stem}_intrinsic.csv", csv_text),
}


def export_all(c: Intrinsics, out_dir: str | Path) -> list[Path]:
    """Write every format into out_dir; returns the paths written.

    A calibration that did not pass is still written (save locally), but every
    file name gets a NOT_PASSED_ prefix so it cannot be mistaken for a good one.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prefix = "" if c.passed else "NOT_PASSED_"
    dt = c.date.strftime("%Y%b%d_%H_%M")
    written = []
    for name, (pattern, fn) in FORMATS.items():
        p = out / (prefix + pattern.format(stem=c.stem, serial=c.serial, dt=dt))
        text = fn(c)
        if name == "PG RWC":
            p.write_bytes(text.encode("ascii"))
        else:
            p.write_text(text, encoding="utf-8", newline="\n")
        written.append(p)
    readme = out / (prefix + f"{c.stem}_README.txt")
    lines = [f"{c.van} {c.camera} serial {c.serial}  —  {c.date:%Y-%m-%d %H:%M}",
             f"Grade: {c.grade_headline or 'not graded'}",
             f"RMS {c.rms_px:.3f} px, {c.images_used} photos, board {c.board}",
             "" if c.repeat_10m_mm is None else
             f"Repeatability: about {c.repeat_10m_mm:.1f} mm at 10 m",
             "", "Files:"]
    lines += [f"  {p.name}" for p in written]
    lines += ["", "Not yet verified in the receiving software:"]
    lines += [f"  {k}: {v}" for k, v in UNVERIFIED.items()]
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(readme)
    return written
