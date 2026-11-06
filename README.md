<p align="center"><img src="assets/icon.png" width="96" alt="FanScope"></p>
<h1 align="center">FanScope · 粉丝观测台</h1>
<p align="center">Windows 粉丝列表采集与 Excel 排名工具</p>
<p align="center"><a href="https://github.com/JahsehXL/FanScope/releases/latest"><b>下载 Windows EXE 版</b></a> · <a href="LICENSE">MIT 开源</a></p>

![软件界面](assets/screenshot.png)

## 下载使用

1. [下载最新版 Windows ZIP](https://github.com/JahsehXL/FanScope/releases/latest)。
2. 解压后双击 **FanScope.exe**。需要 Windows 10/11 64 位和 Microsoft Edge。
3. 点击 **打开采集浏览器**，手动登录抖音并打开目标账号的粉丝列表。
4. 点击 **开始 / 继续采集**，完成后导出 Excel 排名表。

EXE 已包含运行环境，解压即可使用。完整本地项目中，也可双击 **打开软件.cmd**，程序位于 `app/FanScope.exe`。

## 主要功能

- 自动滚动粉丝列表，鼠标可以移开。
- 每批自动保存，按 UID 去重，按粉丝量导出排名。
- 支持 **本次采集**、**历史合并** 两种导出范围。
- 支持 HAR 离线导入和 Excel 导出。

历史合并可能包含已取关账号，网页可返回的数量也可能少于主页显示的粉丝总数。

## 本地处理与隐私

**采集结果零自动上传。** 粉丝记录、HAR 解析结果和 Excel 均在本机处理、保存。软件未集成向开发者上传这些数据的接口、遥测或自动更新服务。

HAR 整理和导出可以离线运行。实时采集时，Edge 会联网访问抖音并发送正常登录会话信息。

数据默认保存在 `%LOCALAPPDATA%\FanScope`，点击软件内的 **数据目录** 即可查看。详细说明见 [隐私说明](docs/PRIVACY.md)。

## 模拟滚动与访问限制

软件通过真实 Edge 模拟列表滚动，等待网页加载后读取响应，遇到可识别的验证码、访问受限或请求错误会暂停。

真实采集仍可能触发平台验证或限制，请在获得适当授权的范围内使用，并遵守平台规则。

---

[更新记录](docs/CHANGELOG.md) · [源代码](src) · [开发说明](.github/CONTRIBUTING.md) · [安全反馈](.github/SECURITY.md)
