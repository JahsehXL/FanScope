# 开发说明

普通用户可直接使用 [Windows EXE 版](https://github.com/JahsehXL/FanScope/releases/latest)。

开发环境使用 Python 3.12，在仓库根目录执行。

```powershell
python -m pip install -r requirements-dev.txt
python src/collector.py
python scripts/build_exe.py
```

源码位于 `src/`，构建后程序位于 `app/FanScope.exe`，版本安装包位于 `dist/`。

日常自动检查仅验证 Python 语法，发版保留一次 EXE 自检。`tests/` 和模拟采集脚本可在改动相关功能时按需手动运行。

提交时请排除用户数据、登录状态、HAR 和构建产物，反馈截图与日志请脱敏。
