"""Writes the Windows version resource for PyInstaller (the Details tab of the exe's properties).

Usage: python make_version_info.py <output file>   - the version comes from sttkbrd/__init__.py."""
import re
import sys

with open("sttkbrd/__init__.py", encoding="utf-8") as f:
    version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
nums = tuple((int(p) for p in version.split(".")[:3])) + (0,) * (4 - len(version.split(".")[:3]))

with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(nums)s, prodvers=%(nums)s, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'sttkbrd - speech to keyboard'),
      StringStruct('FileVersion', '%(v)s'),
      StringStruct('InternalName', 'sttkbrd'),
      StringStruct('OriginalFilename', 'sttkbrd-v%(v)s.exe'),
      StringStruct('ProductName', 'sttkbrd'),
      StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""" % {"nums": nums, "v": version})
print(version)
