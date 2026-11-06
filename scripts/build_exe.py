"""Reproducible Windows build with explicit source and asset inputs."""

import importlib.metadata
import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from collector import APP_VERSION

RELEASE = ROOT / 'dist' / f'v{APP_VERSION}'
RELEASE.mkdir(parents=True, exist_ok=True)
notice = [(ROOT / 'LICENSE').read_text(encoding='utf-8')]
for name in ('playwright', 'openpyxl', 'greenlet', 'pyee', 'typing_extensions', 'et_xmlfile',
             'customtkinter', 'darkdetect', 'pillow', 'packaging'):
    distribution = importlib.metadata.distribution(name)
    notice.append(f'\n{name} {distribution.version}\n')
    for file in distribution.files or []:
        if '.dist-info/' in str(file).replace('\\', '/') and ('license' in file.name.lower() or file.name.upper() == 'NOTICE'):
            notice.append(distribution.locate_file(file).read_text(encoding='utf-8', errors='replace'))
license_directory = ROOT / 'work' / 'licenses'
license_directory.mkdir(parents=True, exist_ok=True)
notice_file = license_directory / 'THIRD_PARTY_LICENSES.txt'
notice.append('\nRoboto font data bundled with CustomTkinter, copyright Google Inc.\n')
notice.append((ROOT / 'assets' / 'licenses' / 'Roboto-Apache-2.0.txt').read_text(encoding='utf-8'))
notice_file.write_text('\n'.join(notice), encoding='utf-8')
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
    '--name', 'FanScope', '--icon', str(ROOT / 'assets' / 'icon.ico'),
    '--collect-data', 'customtkinter',
    '--add-data', f'{notice_file};licenses',
    '--add-data', f'{ROOT / "assets" / "icon-48.png"};assets',
    '--distpath', str(RELEASE), '--workpath', str(ROOT / 'work' / 'build'),
    '--specpath', str(ROOT / 'work' / 'build'), str(ROOT / 'src' / 'collector.py'),
], cwd=ROOT, check=True)


application = ROOT / 'app'
application.mkdir(exist_ok=True)
shutil.copy2(RELEASE / 'FanScope.exe', application / 'FanScope.exe')
print(f'Runnable application: {application / "FanScope.exe"}')
