"""Diagnose PySide6 import / DLL-load failures (mainly Windows).

Run it with the SAME interpreter you use to start the app:

    python diagnose_pyside.py

It prints the Python/OS/PySide6 versions, imports the Qt modules one by one,
then loads the underlying Qt DLLs directly so the FIRST failing entry points
at the real problem (a Windows error 127 = "DLL found, export missing" is
almost always a too-old Visual C++ runtime or a mixed install).
"""
from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys

print("python      :", sys.version.split()[0], "|", sys.executable)
print("architecture:", struct.calcsize("P") * 8, "bit")
print("platform    :", platform.platform())

try:
    import PySide6
except Exception as exc:  # noqa: BLE001 - report anything
    print("PySide6 import FAILED:", type(exc).__name__, exc)
    sys.exit(1)

print("PySide6     :", PySide6.__version__)
pkg = os.path.dirname(PySide6.__file__)
print("PySide6 dir :", pkg)

dupes = [p for p in sys.path if p and "pyside6" in p.lower()]
print("PySide6 dirs on sys.path:", dupes or "(only the installed one)")

print("\n-- Qt module imports (first failure wins) --")
for mod in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
    try:
        __import__(mod)
        print(f"  {mod:22s} OK")
    except Exception as exc:  # noqa: BLE001
        print(f"  {mod:22s} FAILED: {type(exc).__name__}: {exc}")

if os.name == "nt":
    print("\n-- Qt DLLs loaded directly --")
    for dll in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"):
        path = os.path.join(pkg, dll)
        if not os.path.exists(path):
            print(f"  {dll:18s} MISSING FILE: {path}")
            continue
        try:
            ctypes.WinDLL(path)
            print(f"  {dll:18s} OK")
        except OSError as exc:
            print(f"  {dll:18s} FAILED: {exc}")

    print("\n-- Visual C++ runtime Windows actually loads --")
    for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        try:
            ctypes.WinDLL(dll)
            print(f"  {dll:20s} OK")
        except OSError as exc:
            print(f"  {dll:20s} FAILED: {exc}")

print("\nDone. Paste this whole output if it still fails.")
