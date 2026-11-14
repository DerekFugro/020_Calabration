# PyInstaller spec - builds dist\SurveyorCalibration\ with two programs sharing one folder (no Python needed):
#   SurveyorCalibration.exe  (main.py)
#   SurveyorCapture.exe      (src/capture/__main__.py; its own process, docs/capture)
# Run through installer\build.ps1, which writes VERSION first.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "Cal_board"), "Cal_board"),   # shipped boards, copied to ProgramData
    (str(ROOT / "control"), "control"),       # shipped Old School sites, copied to ProgramData
    (str(ROOT / "VERSION"), "."),             # app_version()
]
datas += collect_data_files("fpdf")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["pyodbc"],
    excludes=["pytest", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)

# OpenSSL must be Python's own copy (2026-11-14).  On a PC with Git for Windows on PATH,
# PyInstaller picked C:\Program Files\Git\mingw64\bin\libssl-3-x64.dll; Python's _ssl.pyd
# then failed to load and the built app crashed opening the main window
# ("cannot import name 'HTTPSHandler' from 'urllib.request'").
PY_DLLS = Path(sys.base_prefix) / "DLLs"
SSL_DLLS = {"libssl-3-x64.dll", "libcrypto-3-x64.dll"}


def python_ssl(binaries):
    fixed = []
    for name, src, kind in binaries:
        own = PY_DLLS / Path(name).name
        if Path(name).name.lower() in SSL_DLLS and own.exists():
            src = str(own)
        if "\\git\\" in src.lower():
            raise SystemExit(f"Build stopped: {name} would come from Git ({src}).")
        fixed.append((name, src, kind))
    return fixed


a.binaries = python_ssl(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SurveyorCalibration",
          console=False, upx=False)

cap = Analysis(
    [str(ROOT / "src" / "capture" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "VERSION"), ".")],
    hiddenimports=["pyodbc", "comtypes", "comtypes.client"],
    excludes=["pytest", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
cap.binaries = python_ssl(cap.binaries)
cap_pyz = PYZ(cap.pure)
cap_exe = EXE(cap_pyz, cap.scripts, [], exclude_binaries=True, name="SurveyorCapture",
              console=False, upx=False)

coll = COLLECT(exe, a.binaries, a.datas, cap_exe, cap.binaries, cap.datas,
               upx=False, name="SurveyorCalibration")
