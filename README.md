<p align="center"><img src="assets/icon.png" width="112" alt="FanScope icon"></p>
<h1 align="center">FanScope · 粉丝观测台</h1>
<p align="center">本地粉丝列表采集、HAR 整理与 Excel 排名工具</p>
<p align="center">
  <a href="https://github.com/JahsehXL/FanScope/actions/workflows/check.yml"><img alt="Checks" src="https://github.com/JahsehXL/FanScope/actions/workflows/check.yml/badge.svg"></a>
  <a href="https://github.com/JahsehXL/FanScope/releases"><img alt="Release" src="https://img.shields.io/github/v/release/JahsehXL/FanScope"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue"></a>
</p>

FanScope 使用专用 Edge 会话，保存网页实际收到的抖音粉丝列表响应。也可以离线导入已有 HAR，按 UID 去重，并按每位粉丝自身的粉丝数量导出 Excel。

![FanScope 桌面界面，展示采集数量、导出范围与日志区域](assets/screenshot.png)

**实验性项目。运行前请确认你对目标数据的处理具有适当授权，并遵守适用法律和平台协议。** 平台协议对自动化收集有明确限制，软件许可与数据使用授权需要分别确认。请阅读 [使用边界与数据说明](PRIVACY.md)。

## 下载

在 [Releases](https://github.com/JahsehXL/FanScope/releases/latest) 下载 `FanScope-版本-Windows-x64.zip`，解压后双击 `FanScope.exe`。

- Windows 10/11 64 位，已安装 Microsoft Edge。
- EXE 已包含 Python 与依赖。压缩包约 50 MB，主要体积来自 Playwright 自带的 Node.js 驱动。
- 发布文件附带 SHA-256 校验值。当前版本尚未配置代码签名。

## 功能

- 手动登录，自动识别粉丝列表并滚动，鼠标可移开。
- 每批数据原子写入本机，按目标账号分目录、按 UID 去重。
- 分别显示历史数量、本次读取数量、新增数量和历史合计。
- 导出范围可选 **本次采集** 或 **历史合并**，默认本次采集。
- 接口返回末页后自动导出，也可手动暂停或导出。
- 支持 `.har` 与 `.har.devtools` 离线导入。
- 对可识别的验证码提示、访问受限提示、请求错误及长时间无新响应暂停处理。
- 仅保存指定字段，完整 HTTP 请求头和响应中的其他字段不会写入新批次。

## 使用

1. 打开 FanScope，点击 **打开采集浏览器**。
2. 在新 Edge 窗口手动登录，进入目标主页并打开粉丝列表。
3. 回到工具，点击 **开始 / 继续采集**。
4. 选择导出范围，等待末页自动导出，或点击 **导出 Excel**。
5. 点击 **查看导出** 打开表格，点击 **数据目录** 查看保存位置。

默认滚动间隔为 0.1 秒，范围 0.05～10 秒。间隔是滚动调度时间，实际请求速度受页面与接口响应影响。该数值不代表平台公布的安全阈值。

定位失败时，将鼠标移到列表内部一次后重试。列表已在末尾时，可关闭后重新打开列表。验证和登录由本人处理，处理完成后再手动继续。

## 数量与导出范围

| 指标 | 含义 |
| --- | --- |
| 历史已保存 | 当前目标账号从本机恢复的去重数量 |
| 本次读取 | 本次工具会话中，当前目标账号实际收到的去重数量 |
| 本次新增 | 本次读取中，此前未保存的账号数量 |
| 历史合计 | 历史和本次数据合并后的去重数量 |

**本次采集**只导出本次实际收到的账号。**历史合并**可能保留已取关的账号，不能直接当作当前粉丝名单。切换目标账号后，本次统计重新开始。

字段包含昵称、粉丝数、抖音号、关注数、作品数、获赞数、备注名、UID、主页链接和简介。同粉丝数并列排名，缺失数量排在末尾并留空。

## 本机数据

默认目录为 `%LOCALAPPDATA%\FanScope`。

```text
FanScope/
  browser-profile/       专用 Edge 登录状态
  data/
    <目标账号标识的哈希>/
      batch-000001.json  经过字段筛选的采集批次
      FanScope-*.xlsx    导出表格
```

可以通过环境变量 `FANSCOPE_HOME` 指定其他数据目录。源码版和 EXE 使用同一默认位置。查看、备份和删除数据前，请先退出工具，再在自己的文件管理器中处理对应文件。

HAR 可能包含登录凭据及其他个人信息，请保存在自己的设备上。发布 Issue 时仅提供脱敏错误信息和复现步骤。

## 从源码运行

需要 Python 3.12，命令在项目根目录执行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe collector.py
```

Windows 也可双击 `start.cmd`，首次会在项目内创建虚拟环境并安装依赖。

离线导入示例。

```powershell
.\.venv\Scripts\python.exe collector.py --import-har "example.har" --data-dir ".\local-data"
```

CLI 导入默认导出历史合并范围。GUI 导入使用界面所选范围。一个 HAR 请只包含一个目标账号，多账号文件会报错，已经读取的批次仍保存在本机。

## 验证与打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest test_fanscope -v
.\.venv\Scripts\python.exe verify_collector.py
.\.venv\Scripts\python.exe build_exe.py
```

发布包位于 `release/v版本号/`。`FanScope.exe --diagnose <测试输出目录>` 可以检查打包后的界面、Edge 驱动、模拟网络采集和 Excel 导出。模拟验证会拦截全部浏览器请求，使用虚构账号。

Pillow 仅用于构建图标，发布程序通过 Tk 加载 PNG；构建配置排除了 Pillow 运行库。

## 已知限制

- 适配抖音网页 `follower/list` 响应，页面结构或接口字段改变后可能需要更新。
- 网页接口返回数量可能小于页面显示总数，首批与末页标记不能证明覆盖全部粉丝。
- 验证页面识别依赖可见 DOM 特征，无法覆盖所有风控形式，也无法保证账号安全。
- 保存记录恢复与 UID 合并已实现，重启后的可靠游标续采仍待实现，通常需要重新打开列表滚动。
- 数值来自采集时的接口响应，历史合并包含不同时刻的数据。
- 旧版批次可读取，历史文件中的原始内容保留在原文件内；读取时仅使用允许字段。

## 贡献

欢迎提交页面适配、数据准确性、隐私最小化和界面改进。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)。

## License

[MIT](LICENSE)。第三方依赖保留各自许可证，发布包附带第三方许可文本。图标由 OpenAI 图像生成工具生成，提示词及资源说明见 [assets/ICON_PROMPT.md](assets/ICON_PROMPT.md)。

## English summary

FanScope is an experimental Windows desktop tool for locally collecting visible Douyin follower-list responses, importing HAR files, deduplicating accounts, and exporting follower-count rankings to Excel. It supports current-session and merged-history exports. Login and verification are handled manually in a dedicated Edge profile. Data stays on your machine. Confirm applicable permissions, platform terms and legal requirements before use. See the Chinese documentation above for setup, data scope, limitations and reproducible builds.
