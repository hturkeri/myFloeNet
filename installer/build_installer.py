"""Build the Windows installer of myFlowNet (per-user, no administrator rights).

The installer carries everything the program needs:

* the Windows *embeddable* Python distribution (python.org, 64-bit),
* numpy, PySide6-Essentials (+ shiboken6) and OpenCASCADE (cadquery-ocp-novtk) wheels for win_amd64,
* the myFlowNet package, examples and documentation.

Unused Qt modules, tools and DLLs are removed by following the PE import tables of the modules
myFlowNet actually loads (pefile), so the bundle stays small.  The NSIS script (myflownet.nsi)
installs to %LOCALAPPDATA%\\Programs\\myFlowNet, creates Start-menu / desktop shortcuts and an
uninstaller registered under HKCU - no UAC prompt.

Runs on Windows or Linux (needs Python ≥ 3.10, `pip install pefile pillow PySide6`, and NSIS's
`makensis`).  Example:

    python build_installer.py --embed python-3.12.x-embed-amd64.zip --wheels wheels --out dist

    # wheels for the embedded interpreter (same minor version!):
    python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 \\
        --implementation cp -d wheels numpy PySide6-Essentials cadquery-ocp-novtk
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# wheels to bundle (distribution-name prefixes, normalised to lower case with "_")
WHEELS = ("numpy", "pyside6_essentials", "shiboken6", "cadquery_ocp_novtk")
# Python extension modules myFlowNet imports (roots of the DLL closure)
PYSIDE_MODULES = ("QtCore", "QtGui", "QtWidgets")
QT_PLUGINS = ("platforms/qwindows.dll", "platforms/qoffscreen.dll", "platforms/qminimal.dll",
              "styles/qmodernwindowsstyle.dll", "imageformats/qico.dll", "imageformats/qjpeg.dll",
              "imageformats/qgif.dll")
PYSIDE_DROP_DIRS = ("qml", "translations", "metatypes", "resources", "typesystems", "include", "glue",
                    "scripts", "examples", "doc", "lib")
DROP_PATTERNS = ("*.pyi", "*.lib", "*.exe", "*.pdb", "py.typed")


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ PE imports
def pe_imports(path: str) -> set[str]:
    import pefile
    # large extension modules (OCP: >100 MB, tens of thousands of imported symbols) exceed the default
    # safety limits of pefile, which would silently truncate the list of imported DLLs
    pefile.MAX_IMPORT_SYMBOLS = 10 ** 7
    if hasattr(pefile, "MAX_SYMBOL_EXPORT_COUNT"):
        pefile.MAX_SYMBOL_EXPORT_COUNT = 10 ** 7
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    except Exception as ex:
        log("  ! cannot parse", path, ex)
        return set()
    out = set()
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attr, []) or []:
            out.add(entry.dll.decode("ascii", "replace").lower())
    pe.close()
    return out


def dll_closure(roots: list[str], pool: dict[str, str]) -> tuple[set[str], set[str]]:
    """Files (paths) reachable from roots through import tables; pool maps lower-case DLL name -> path.
    Returns (kept paths, unresolved names)."""
    keep, unresolved, todo = set(), set(), list(roots)
    while todo:
        p = todo.pop()
        if p in keep:
            continue
        keep.add(p)
        for name in pe_imports(p):
            q = pool.get(name)
            if q is None:
                unresolved.add(name)
            elif q not in keep:
                todo.append(q)
    return keep, unresolved


# ------------------------------------------------------------------ steps
def unpack_embed(src: str, dst: str):
    os.makedirs(dst, exist_ok=True)
    if os.path.isdir(src):
        for f in os.listdir(src):
            s = os.path.join(src, f)
            (shutil.copytree if os.path.isdir(s) else shutil.copy2)(s, os.path.join(dst, f))
    else:
        with zipfile.ZipFile(src) as z:
            z.extractall(dst)
    pth = [f for f in os.listdir(dst) if f.endswith("._pth")]
    if not pth or not any(f.startswith("python") and f.endswith(".dll") and f != "python3.dll"
                          for f in os.listdir(dst)):
        sys.exit(f"{src} does not look like a Windows embeddable Python distribution")
    ver = re.match(r"python(\d)(\d+)\._pth", pth[0])
    zipname = f"python{ver.group(1)}{ver.group(2)}.zip"
    with open(os.path.join(dst, pth[0]), "w", encoding="ascii") as f:
        f.write(f"{zipname}\n.\nLib\\site-packages\n..\\app\nimport site\n")
    return f"{ver.group(1)}.{ver.group(2)}"


def unpack_wheels(wheel_dir: str, site: str, pyver: str):
    os.makedirs(site, exist_ok=True)
    tag = "cp" + pyver.replace(".", "")
    used = []
    for f in sorted(os.listdir(wheel_dir)):
        if not f.endswith(".whl"):
            continue
        dist = f.split("-")[0].lower()
        if dist not in WHEELS:
            continue
        if ("-cp3" in f and f"-{tag}-" not in f and "abi3" not in f) or "win_amd64" not in f and "none-any" not in f:
            log("  skip (wrong tag)", f)
            continue
        with zipfile.ZipFile(os.path.join(wheel_dir, f)) as z:
            z.extractall(site)
        used.append(f)
    missing = [w for w in WHEELS if not any(u.lower().startswith(w) for u in used)]
    if missing:
        sys.exit(f"missing wheels for {tag} win_amd64: {missing}")
    return used


def remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def trim(site: str):
    """Keep only what QtCore/QtGui/QtWidgets, shiboken, numpy and OCP load."""
    ps = os.path.join(site, "PySide6")
    for d in PYSIDE_DROP_DIRS:
        remove(os.path.join(ps, d))
    for f in os.listdir(ps):
        if f.endswith(".pyd") and f[:-4] not in PYSIDE_MODULES:
            remove(os.path.join(ps, f))
    plug = os.path.join(ps, "plugins")
    keep_plugins = {os.path.normpath(os.path.join(plug, p)) for p in QT_PLUGINS}
    for dp, dn, fn in os.walk(plug):
        for f in fn:
            p = os.path.normpath(os.path.join(dp, f))
            if p not in keep_plugins:
                os.remove(p)
    for dp, dn, fn in os.walk(site, topdown=False):
        for f in fn:
            if any(fnmatch.fnmatch(f, pat) for pat in DROP_PATTERNS):
                os.remove(os.path.join(dp, f))
        if os.path.basename(dp) == "tests" and "numpy" in dp:
            shutil.rmtree(dp, ignore_errors=True)
        elif not os.listdir(dp):
            os.rmdir(dp)
    # DLL closure
    pool = {}
    roots = []
    for dp, dn, fn in os.walk(site):
        for f in fn:
            p = os.path.join(dp, f)
            fl = f.lower()
            if fl.endswith(".dll") and "plugins" not in dp:
                pool.setdefault(fl, p)
            if fl.endswith(".pyd") or ("plugins" in dp and fl.endswith(".dll")):
                roots.append(p)
    keep, unresolved = dll_closure(roots, pool)
    removed = 0
    for name, p in pool.items():
        if p not in keep:
            removed += os.path.getsize(p)
            os.remove(p)
    system = {n for n in unresolved if n.startswith(("api-ms-win", "ext-ms-win")) or n in SYSTEM_DLLS}
    log(f"  DLL closure: kept {len(keep)} files, removed {removed / 1e6:.0f} MB")
    other = sorted(unresolved - system)
    if other:
        log("  resolved by the Python runtime / Windows:", ", ".join(other))
    return other


SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll",
    "comdlg32.dll", "ws2_32.dll", "winmm.dll", "imm32.dll", "uxtheme.dll", "dwmapi.dll", "version.dll",
    "shlwapi.dll", "netapi32.dll", "userenv.dll", "mpr.dll", "crypt32.dll", "secur32.dll", "bcrypt.dll",
    "ntdll.dll", "dwrite.dll", "d2d1.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll", "d3d9.dll", "opengl32.dll",
    "glu32.dll", "setupapi.dll", "wtsapi32.dll", "authz.dll", "msvcrt.dll", "rpcrt4.dll", "comctl32.dll",
    "dbghelp.dll", "psapi.dll", "iphlpapi.dll", "dnsapi.dll", "wininet.dll", "winhttp.dll", "powrprof.dll",
    "cfgmgr32.dll", "shcore.dll", "dcomp.dll", "dxcore.dll", "msimg32.dll", "winspool.drv", "oleacc.dll",
    "propsys.dll", "hid.dll", "ncrypt.dll", "normaliz.dll", "usp10.dll", "imagehlp.dll", "wldap32.dll",
}


def copy_app(app: str):
    def ign(d, names):
        return [n for n in names if n in ("__pycache__", ".pytest_cache") or n.endswith(".pyc")]
    shutil.copytree(os.path.join(ROOT, "myflownet"), os.path.join(app, "myflownet"), ignore=ign)
    shutil.copytree(os.path.join(ROOT, "examples"), os.path.join(app, "examples"), ignore=ign)
    shutil.copytree(os.path.join(ROOT, "docs"), os.path.join(app, "docs"), ignore=ign)
    shutil.copy2(os.path.join(ROOT, "README.md"), app)


def licenses(stage: str, py_dir: str, site: str, version: str):
    lic = os.path.join(stage, "licenses")
    os.makedirs(lic, exist_ok=True)
    shutil.copy2(os.path.join(py_dir, "LICENSE.txt"), os.path.join(lic, "Python-LICENSE.txt"))
    names = []
    for d in sorted(os.listdir(site)):
        if d.endswith(".dist-info"):
            dist = d.rsplit("-", 1)[0]
            names.append(dist)
            for dp, dn, fn in os.walk(os.path.join(site, d)):
                for f in fn:
                    if re.match(r"(LICEN[CS]E|COPYING|NOTICE)", f, re.I) or "licenses" in dp.lower():
                        os.makedirs(os.path.join(lic, dist), exist_ok=True)
                        shutil.copy2(os.path.join(dp, f), os.path.join(lic, dist, f))
    text = f"""myFlowNet {version} - 1D flow network solver for gas turbine secondary air systems

This installer contains the following third-party components (licence texts in the
"licenses" folder of the installation):

  * Python (Windows embeddable distribution) - Python Software Foundation License
  * numpy - BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause; gfortran runtime: GPL-3.0 with GCC Runtime
    Library Exception)
  * PySide6 / Qt 6 (QtCore, QtGui, QtWidgets) - LGPL-3.0; the Qt libraries are dynamically linked
    and can be replaced by the user
  * shiboken6 - LGPL-3.0
  * Open CASCADE Technology via cadquery-ocp-novtk (OCP) - OCCT: LGPL-2.1 with the Open CASCADE
    exception; OCP bindings: Apache-2.0; bundled FreeImage / OpenEXR / Imath / TBB / freetype
    and other libraries under their own licences (see licenses/)
  * Microsoft Visual C++ runtime DLLs - Microsoft redistributable licence

Bundled distributions: {", ".join(names)}
"""
    with open(os.path.join(stage, "THIRD_PARTY_NOTICES.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def make_icon(path: str):
    """Program icon drawn with Qt (original artwork: a network of three chambers)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QLinearGradient, QBrush
    app = QGuiApplication.instance() or QGuiApplication([])
    imgs = []
    for size in (256, 64, 48, 32, 16):
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 256.0
        p.scale(s, s)
        g = QLinearGradient(0, 0, 0, 256)
        g.setColorAt(0, QColor("#2D5794"))
        g.setColorAt(1, QColor("#132A4D"))
        p.setBrush(QBrush(g))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)
        pen = QPen(QColor("#E4ECF5"), 14)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        a, b, c = QPointF(62, 170), QPointF(128, 86), QPointF(194, 170)
        p.drawLine(a, b)
        p.drawLine(b, c)
        p.drawLine(a, c)
        for pt, col in ((a, "#22C7C2"), (b, "#F5A623"), (c, "#D7301F")):
            p.setPen(QPen(QColor("#FFFFFF"), 10))
            p.setBrush(QColor(col))
            p.drawEllipse(pt, 34, 34)
        p.end()
        imgs.append(img)
    try:
        from PIL import Image
        import io
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        imgs[0].save(buf, "PNG")
        im = Image.open(io.BytesIO(bytes(buf.data())))
        im.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    except ImportError:
        imgs[0].save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--embed", required=True, help="Windows embeddable Python (zip or unpacked folder)")
    ap.add_argument("--wheels", required=True, help="folder with the win_amd64 wheels")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    ap.add_argument("--makensis", default=shutil.which("makensis") or "makensis")
    ap.add_argument("--no-nsis", action="store_true", help="only build the staging folder")
    a = ap.parse_args(argv)
    sys.path.insert(0, ROOT)
    from myflownet import __version__ as version

    stage = os.path.join(a.out, "stage")
    remove(stage)
    os.makedirs(stage)
    py_dir = os.path.join(stage, "python")
    log("1/6 Python runtime")
    pyver = unpack_embed(a.embed, py_dir)
    log("    Python", pyver)
    site = os.path.join(py_dir, "Lib", "site-packages")
    log("2/6 wheels")
    for w in unpack_wheels(a.wheels, site, pyver):
        log("    ", w)
    log("3/6 trimming")
    trim(site)
    log("4/6 application")
    copy_app(os.path.join(stage, "app"))
    licenses(stage, py_dir, site, version)
    make_icon(os.path.join(stage, "myflownet.ico"))
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(stage) for f in fn)
    nfiles = sum(len(fn) for dp, dn, fn in os.walk(stage))
    log(f"    staged {nfiles} files, {total / 1e6:.0f} MB")
    if a.no_nsis:
        return 0
    log("5/6 NSIS")
    out = os.path.join(a.out, f"myFlowNet-{version}-Setup.exe")
    cmd = [a.makensis, "-V2", f"-DVERSION={version}", f"-DSTAGE={stage}", f"-DOUTFILE={out}",
           f"-DSIZE_KB={total // 1024}", os.path.join(HERE, "myflownet.nsi")]
    subprocess.check_call(cmd)
    log(f"6/6 done: {out}  ({os.path.getsize(out) / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
