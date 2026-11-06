"""Reproducible Windows build with explicit source and asset inputs."""

import hashlib
import importlib.metadata
import subprocess
import sys
import zipfile
from pathlib import Path
from collector import APP_VERSION

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / 'release' / f'v{APP_VERSION}'
RELEASE.mkdir(parents=True, exist_ok=True)
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
    '--name', 'FanScope', '--icon', str(ROOT / 'assets' / 'icon.ico'),
    '--exclude-module', 'PIL',
    '--add-data', f'{ROOT / "assets" / "icon-48.png"};assets',
    '--distpath', str(RELEASE), '--workpath', str(ROOT / '.build'),
    '--specpath', str(ROOT / '.build'), str(ROOT / 'collector.py'),
], cwd=ROOT, check=True)

notice = []
for name in ('playwright', 'openpyxl', 'greenlet', 'pyee', 'typing_extensions', 'et_xmlfile'):
    distribution = importlib.metadata.distribution(name)
    notice.append(f'\n{name} {distribution.version}\n')
    for file in distribution.files or []:
        if '.dist-info/' in str(file).replace('\\', '/') and ('license' in file.name.lower() or file.name.upper() == 'NOTICE'):
            notice.append(distribution.locate_file(file).read_text(encoding='utf-8', errors='replace'))
notice_file = RELEASE / 'THIRD_PARTY_LICENSES.txt'
notice_file.write_text('\n'.join(notice), encoding='utf-8')
archive = RELEASE / f'FanScope-v{APP_VERSION}-Windows-x64.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
    for path in (RELEASE / 'FanScope.exe', ROOT / 'README.md', ROOT / 'LICENSE', notice_file):
        package.write(path, arcname=path.name)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(RELEASE / 'SHA256SUMS.txt').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
print(f'Built {archive} ({archive.stat().st_size:,} bytes)')
