"""Build the ordinary-user controls helper as a selectable macOS app."""
from pathlib import Path
import plistlib
import subprocess

APP_NAME = 'Mac Control Media.app'
EXECUTABLE_NAME = 'MacControlControls'


def build(root):
    root = Path(root)
    app = root / '.runtime' / APP_NAME
    binary = app / 'Contents' / 'MacOS' / EXECUTABLE_NAME
    source = root / 'native' / 'controls.m'
    if binary.exists() and (app / 'Contents' / 'Info.plist').exists() and binary.stat().st_mtime >= max(source.stat().st_mtime, Path(__file__).stat().st_mtime):
        signature = subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], capture_output=True)
        if signature.returncode == 0: return app
    binary.parent.mkdir(parents=True, exist_ok=True)
    info = {
        'CFBundleExecutable': EXECUTABLE_NAME,
        'CFBundleIdentifier': 'local.maccontrol.controls',
        'CFBundleName': 'Mac Control Media',
        'CFBundleDisplayName': 'Mac Control Media',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '13.0', 'LSUIElement': True,
    }
    (app / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/clang', '-fobjc-arc', '-O2', '-framework', 'Foundation',
                    '-framework', 'AppKit', '-framework', 'CoreAudio', '-framework', 'ApplicationServices',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                    'local.maccontrol.controls', str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True)
    return app
