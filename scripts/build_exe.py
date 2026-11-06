"""Reproducible Windows build with explicit source and asset inputs."""

import hashlib
import importlib.metadata
import subprocess
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from collector import APP_VERSION

RELEASE = ROOT / 'dist' / f'v{APP_VERSION}'
RELEASE.mkdir(parents=True, exist_ok=True)
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
    '--name', 'FanScope', '--icon', str(ROOT / 'assets' / 'icon.ico'),
    '--collect-data', 'customtkinter',
    '--add-data', f'{ROOT / "assets" / "icon-48.png"};assets',
    '--distpath', str(RELEASE), '--workpath', str(ROOT / 'work' / 'build'),
    '--specpath', str(ROOT / 'work' / 'build'), str(ROOT / 'src' / 'collector.py'),
], cwd=ROOT, check=True)

notice = []
for name in ('playwright', 'openpyxl', 'greenlet', 'pyee', 'typing_extensions', 'et_xmlfile',
             'customtkinter', 'darkdetect', 'pillow', 'packaging'):
    distribution = importlib.metadata.distribution(name)
    notice.append(f'\n{name} {distribution.version}\n')
    for file in distribution.files or []:
        if '.dist-info/' in str(file).replace('\\', '/') and ('license' in file.name.lower() or file.name.upper() == 'NOTICE'):
            notice.append(distribution.locate_file(file).read_text(encoding='utf-8', errors='replace'))
notice_file = RELEASE / 'THIRD_PARTY_LICENSES.txt'
notice.append('\nRoboto font data bundled with CustomTkinter, copyright Google Inc.\n')
notice.append((ROOT / 'assets' / 'licenses' / 'Roboto-Apache-2.0.txt').read_text(encoding='utf-8'))
notice_file.write_text('\n'.join(notice), encoding='utf-8')
archive = RELEASE / f'FanScope-v{APP_VERSION}-Windows-x64.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
    for path in (RELEASE / 'FanScope.exe', ROOT / 'README.md', ROOT / 'LICENSE', notice_file,
                 ROOT / 'docs' / 'PRIVACY.md', ROOT / 'docs' / 'CHANGELOG.md',
                 ROOT / '.github' / 'CONTRIBUTING.md', ROOT / '.github' / 'SECURITY.md'):
        name = path.relative_to(ROOT).as_posix() if path.parent.name in ('docs', '.github') else path.name
        package.write(path, arcname=name)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(RELEASE / 'SHA256SUMS.txt').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
print(f'Built {archive} ({archive.stat().st_size:,} bytes)')
application = ROOT / 'app'
application.mkdir(exist_ok=True)
for path in (RELEASE / 'FanScope.exe', ROOT / 'LICENSE', ROOT / 'docs' / 'PRIVACY.md', notice_file):
    shutil.copy2(path, application / path.name)
print(f'Runnable application: {application / "FanScope.exe"}')
