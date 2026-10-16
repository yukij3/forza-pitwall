# PyInstaller spec for the Windows desktop app: one windowed forza-pitwall.exe.
#
#   uv sync --group desktop
#   uv run pyinstaller --noconfirm --clean packaging/windows/pitwall.spec
#   dist\forza-pitwall.exe --smoke
#
# Bundles the pitwall package, the web UI (web/) and the baseline data. At run
# time pitwall.config.resource_root() finds them under sys._MEIPASS.

import re
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).resolve().parents[1]
HERE = Path(SPECPATH).resolve()

with (ROOT / "pyproject.toml").open("rb") as fh:
    project = tomllib.load(fh)["project"]
VERSION = project["version"]
# Windows wants four integers; "1.2.3rc1" -> (1, 2, 3, 0).
numbers = [int(n) for n in re.findall(r"\d+", VERSION.split("+")[0])[:3]]
VERSION_TUPLE = tuple(numbers + [0] * (4 - len(numbers)))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "forza-pitwall contributors"),
                        StringStruct("FileDescription", "Forza Pitwall"),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("InternalName", "forza-pitwall"),
                        StringStruct("LegalCopyright", "MIT License"),
                        StringStruct("OriginalFilename", "forza-pitwall.exe"),
                        StringStruct("ProductName", "Forza Pitwall"),
                        StringStruct("ProductVersion", VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

hiddenimports = (
    # pitwall.analysis and pitwall.baselines are imported by name at run time.
    collect_submodules("pitwall")
    # uvicorn picks its loop, HTTP/WebSocket protocols and lifespan by name.
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
)

datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "pitwall" / "baselines" / "data"), "pitwall/baselines/data"),
]

a = Analysis(
    [str(HERE / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="forza-pitwall",
    icon=str(HERE / "pitwall.ico"),
    version=version_info,
    console=False,
    upx=False,
    debug=False,
    strip=False,
)
