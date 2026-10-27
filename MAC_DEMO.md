# Mac 演示操作说明

完整命令见 `START_HERE_MAC.md`。支持 Apple Silicon、Intel Mac 和验证用 Linux x86_64；环境固定 Python 3.10.13 与 `env/pip-freeze.txt`，不改原 `.venv`。不需要 GPU、Torch、ViT 或商业 API。首次安装/下载需要网络；离线页面和检查仅用 Python 标准库。

## 展示顺序

1. 说明离线页面展示已保存的实测结果。GPT-4 Turbo 不可用后，原实验由 GPT-4o 替代并补充 Sol 对照。
2. 说明固定的样本、检索、提示词、评测及必要的 temperature/token 参数变化。
3. Nutrition5k 共同 79 道菜：重量 MAE 96.01→62.24 g，热量 126.86→131.83 kcal。重量改善不等于营养改善。
4. ASA24 共同 Exact 只有 10 行，各自 Exact 是 21/11；不同条件子集的 MAE 不能直接归因为模型能力。
5. 展开成功/失败例图，打开英文 PDF、Word 或 Markdown。
6. 若 key 和小额费用已授权，再运行新推理，查看新 `demo-runs/`。两张开发图不构成正式测试。

## Runtime

`demo/runtime-release.json` 固定 release URL、字节数与 SHA256。压缩包包含 FNDDS 描述/营养表、份量权重、ASA24 映射、开发集表格、20 张开发图及 5624×3072 的原 embedding。没有完整测试图、NHANES 原始文件、key 或 Linux 二进制索引。

导出时检验 float32 向量与原值完全一致，Mac 重新建立原生 Chroma 索引。ANN 重建可能改变近邻边界顺序，不能称为原实验逐位复放。建立索引没有 embedding 请求；真实推理的查询仍调用付费 embedding API。

```sh
.venv-demo/bin/python tools/runtime_bundle.py verify
```

预期 vectors=5624、dimensions=3072、api_calls=0。源码、开发图及参考标签的角色不变；ASA24 只在已登记的 Exact 条件下使用参考编码进行份量评估。

## 恢复与边界

- 下载失败先检查 GitHub/PyPI 可达性，不绕过 SHA256 或随机升级。可另行下载同一 bundle 后使用 `tools/runtime_bundle.py install --archive /path/to/mac-demo-runtime-v1.zip`。
- `.venv-demo` Python 不匹配时保存现场并重命名该目录，再 setup；不要修改系统 Python 或旧 `.venv`。
- runtime/索引损坏时保留错误，重命名本 clone 的 `.demo/assets` 或 `.demo/index` 后重装；不碰历史 `runs/`。
- 端口冲突改 `--port`，不结束无关程序。
- 模型 404 或权限问题显示真实错误，不静默回退。没有 Exact 或菜不完整时按失败解释，不变成成功的零误差。
- 费用阈值按历史价格与返回 token 估算，只在请求之间生效；一笔在途请求可能超过。查看 `demo-usage.json` 和账目。

科学实验审查与演示包装验证分别记录。历史证据见 `REVIEW.md`；交付的实际验证见 `DELIVERY_VALIDATION.md` 和 GitHub Actions。Mac 无 key CI 不能证明真实 OpenAI 调用成功；实际演示仍需观察页面和可选真实输出。
