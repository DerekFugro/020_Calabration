# PyInstaller spec - builds dist\SurveyorCalibration\SurveyorCalibration.exe (one folder, no Python needed).
# Run through installer\build.ps1, which writes VERSION first.
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
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SurveyorCalibration",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="SurveyorCalibration")
