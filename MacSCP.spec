# -*- mode: python ; coding: utf-8 -*-
import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_all

hiddenimports = [
    'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.sip',
    'paramiko', 'cryptography',
]
hiddenimports += collect_submodules('PyQt6')
hiddenimports += collect_submodules('paramiko')
hiddenimports += collect_submodules('cryptography')

datas, binaries = [], []
for pkg in ('paramiko', 'cryptography'):
    d, b, h = collect_all(pkg)
    datas    += d
    binaries += b

# Icon: use macOS system generic icon when available; skip on other platforms
_mac_icon = '/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns'
icon_file = _mac_icon if (sys.platform == 'darwin' and os.path.exists(_mac_icon)) else None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MacSCP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,         # UPX can break Qt binaries — keep off
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MacSCP',
)
app = BUNDLE(
    coll,
    name='MacSCP.app',
    icon=icon_file,
    bundle_identifier='com.macscp.app',
    version='1.0.0',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'NSHighResolutionCapable': True,
        'CFBundleDisplayName': 'MacSCP',
        'CFBundleName': 'MacSCP',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '10.13',
    },
)
