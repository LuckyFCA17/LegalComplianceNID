# PyInstaller spec for the portable build: one folder with LegalCompliance(.exe) and its runtime.
# Build:  pyinstaller packaging/LegalCompliance.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
# pypdfium2 ships the PDFium library as package data; collect it explicitly.
pdfium_datas, pdfium_bins, pdfium_hidden = [], [], []
for pkg in ("pypdfium2", "pypdfium2_raw"):
    d, b, h = collect_all(pkg)
    pdfium_datas += d
    pdfium_bins += b
    pdfium_hidden += h

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "app", "static"), os.path.join("app", "static"))] + pdfium_datas,
    binaries=pdfium_bins,
    hiddenimports=["waitress", "app.auth", "app.routes", "app.analysis", "app.ocr", "app.ocr_jobs", "pypdf",
                   "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"] + pdfium_hidden,
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
