# 贡献指南

使用 Python 3.12 和 `requirements-dev.txt` 建立本地环境。数据目录位于用户目录，可用 `FANSCOPE_HOME` 指向个人测试位置。

提交前执行以下检查。

```powershell
python -m unittest test_fanscope -v
python verify_collector.py
```

浏览器模拟测试需要已安装的 Microsoft Edge，全部网络请求都会被本机测试拦截。只使用虚构账号作为测试数据。

PR 请说明具体问题、行为变化和验证结果。涉及界面时提供脱敏截图，涉及保存格式时考虑已有批次的兼容性。

提交范围应为源码、测试、文档和资源。检查暂存区，确保用户数据、登录状态、HAR、个人路径和构建输出留在本机。`.gitignore` 是辅助措施，发布前仍需检查。
