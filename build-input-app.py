#!/usr/bin/env python3
"""Build a signed local app bundle selectable in macOS Input Monitoring."""
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parent
APP = ROOT / '.runtime' / 'Mac Control Inputs.app'
EXECUTABLE = APP / 'Contents' / 'MacOS' / 'MacControlInputs'


def build():
    EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    info = {
        'CFBundleExecutable': 'MacControlInputs',
        'CFBundleIdentifier': 'local.maccontrol.inputs',
        'CFBundleName': 'Mac Control Inputs',
        'CFBundleDisplayName': 'Mac Control Inputs',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '2.0',
        'CFBundleVersion': '2',
        'LSMinimumSystemVersion': '13.0',
        'LSUIElement': True,
        'NSInputMonitoringUsageDescription': 'Allows the local dashboard to switch the built-in keyboard and trackpad on or off.',
    }
    (APP / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/clang', '-fobjc-arc', '-O2', '-Wall', '-framework', 'Foundation',
                    '-framework', 'AppKit', '-framework', 'IOKit', str(ROOT / 'native' / 'inputs.m'),
                    '-o', str(EXECUTABLE)], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier', 'local.maccontrol.inputs', str(APP)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(APP)], check=True)
    print(APP)


if __name__ == '__main__': build()
