# 给 Mac 上 Codex 的交接入口

用户要求从本仓库拉取后自行配置环境、完成离线展示；在用户提供本地 key 并授权小额费用后，可演示各一张开发集图片的真实推理。用中文交流。

这是本次 `DietAI24_original` 实验，原代码基线为 `5946365`，不是旧 multifood 项目。两种配置的正式测试均已完成，每种只跑一次。不要执行历史 `HANDOFF_CODEX.md` 第 5 节，不重跑或改写 `runs/test*`。先读本文件、`MAC_DEMO.md` 和英文 `REPORT.md`。

## 请直接完成

在 clone 根目录运行：

```sh
./setup.sh offline
.venv-demo/bin/python tools/demo.py --check
.venv-demo/bin/python -m unittest discover -s tests -v
.venv-demo/bin/python tools/demo.py --open
```

setup 将校验过的 uv、Python 3.10.13 放在本项目 `.tools/`，冻结依赖放在 `.venv-demo/`。不需要 Homebrew、不写 shell 配置、不调用 API。初次需要联网下载环境；后续离线展示不需要网络。

确认 `http://127.0.0.1:8765` 可打开，检查数据集切换、共同/各自子集切换、例图展开及三版报告链接。端口占用就用 `--port 8766`，不要结束无关程序。离线检查预期 PASS、api_calls=0、Exact=[21,11]、完整菜=[86,118]、共同完整菜=79。这是历史结果展示，不是在 Mac 重跑正式测试。

## 真实推理的准备

```sh
./setup.sh live
.venv-demo/bin/python tools/live_demo.py --dry-run
```

此阶段只下载固定约 59 MiB runtime，验证 SHA256，并用保存的向量建立 Mac 本机索引，不调用 OpenAI。dry-run 预期两数据集各一行、5624 个向量、api_calls=0，不需要 key。

用户已在本 clone 根目录 `.env` 填好 key，而且当前对话已明确允许这次小额付费演示及阈值后，运行：

```sh
.venv-demo/bin/python tools/live_demo.py --allow-paid --max-usd 0.50
```

需要 Sol 时加 `--model gpt-6.1-sol`。不输出 `.env` 内容，不把 key 发到聊天，不复制另一台电脑的 `.env`/`.venv`。缺 key 时告知用户本地填写位置，同时完成离线展示。费用阈值是按返回 usage 和历史单价估算、在请求之间停止，单次在途请求可能超过，并非账单硬上限；承诺当前费用前应核实官方价格。

新推理只处理原开发集首张 ASA24、首道 Nutrition5k，输出新的 `demo-runs/`。不要换图或反复支付以获得漂亮结果。真实失败按失败展示；404/权限问题保留原错误，不自动换模型，不改提示词、解析和评测。

## 汇报要求

给出实际 URL、离线检查与测试结果、实际 Mac 架构。如跑了真实 API，报告新目录、实际完成/失败状态、费用估计。只执行 dry-run 时必须写“在线入口已就绪，尚未真实调用”。
