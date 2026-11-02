# Mac 演示入口

本目录是 MAE v2 的便携入口。先展示保存的聚合报告；需要当前用户明确授权时，再运行两张历史图的付费演示。开发选择结果和独立验证结果以报告中的状态为准。本包不重跑开发实验或正式验证。

当前交付是供独立审查的候选包，不会自动发布到 GitHub。实际 Mac 尚未执行验证；Linux 清洁目录的离线验证不能代替 Mac 验收。

1. 解压 `mae-v2-complete.zip`，在包含本文件的目录打开终端。若拿到的是源码包，保存配套 `mae-v2-runtime.zip`；离线看报告不需要 runtime。
2. 运行 `bash setup.sh offline`。安装器固定 Python 3.10.13 与 `requirements-demo.txt`，只写本目录，不用 sudo/Homebrew。首次安装 Python/依赖需要联网；安装及自检不调用模型 API，不读取 `.env`。
3. 运行 `.venv-demo/bin/python tools/demo.py --check`，然后 `.venv-demo/bin/python tools/demo.py --serve --open`。浏览器只监听本机 `127.0.0.1:8765`，展示报告和两张历史演示图。按 Ctrl-C 退出。

源码包导入独立 runtime：

```bash
.venv-demo/bin/python tools/package_demo.py --install-runtime /绝对路径/mae-v2-runtime.zip
.venv-demo/bin/python tools/demo.py --check --require-runtime
```

导入先核对随源码包固定的 archive SHA、成员列表、每文件 SHA 和最终 profile；已有不同内容会停止。无需下载原始研究图、重新生成向量或读取研究标签。

付费演示先阅读 [MAC_DEMO.md](MAC_DEMO.md)。`--live` 默认只做无密钥准备检查；只有显式 `--allow-paid` 和本目录内独立配置的 `.env` 才会提交请求。历史会话的运行许可不能替代演示者当前的授权。

完整优化源码、协议、配置、测试均随源码包提供。研究 cohort 准备、开发选择、验证和审计入口依赖未公开的本地私有数据与 v1 归档，不能凭候选包声称重放整项实验。不要执行旧版 HANDOFF 的正式实验命令。

报告重建及文档作者测试另需 `python-docx`、PDF/字体等工具，使用报告作者的 Codex 文档 runtime；它们不属于固定演示依赖。不要用 `unittest discover` 全量运行作者测试来判断 Mac 演示是否可用；本入口的自检是 `tools/demo.py --check`。
