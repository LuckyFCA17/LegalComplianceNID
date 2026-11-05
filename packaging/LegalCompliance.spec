# PyInstaller spec for the portable build: one folder with LegalCompliance(.exe) and its runtime.
# Build:  pyinstaller packaging/LegalCompliance.spec --noconfirm
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "app", "static"), os.path.join("app", "static"))],
    hiddenimports=["waitress", "app.auth", "app.routes", "app.analysis", "pypdf"],
    excludes=["pytest", "gunicorn", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LegalCompliance",
    console=True,  # the window shows the address and closing it stops the app
    upx=False,     # UPX-packed executables trigger more antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="LegalCompliance", upx=False)
