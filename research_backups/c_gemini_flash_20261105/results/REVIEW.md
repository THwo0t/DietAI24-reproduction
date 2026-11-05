# C 视觉模型替换：独立有限审查

2026-11-05：**approved**。本次范围为新目录 config.py、provider.py、newcommon.py、run.py、pipeline.py、score.py、chroma_index.py、verify_completed.py；不含其他代理仍在编写的 compare_baseline.py。没有发现 P1/P2 必修问题。

- config.py 的 MODELS 和两个 endpoint 实际由 provider.py:20-25 读取；provider.py:125-136 同时检查请求模型及消息中是否包含图片，图片调用和携带历史图片的格式修复调用走 Gemini，纯文字走 Sol，embedding 走原官方模型；按三个角色读取对应凭据，不输出凭据。
- run.py:187-198 在当前实验 Store 内生成并保存新的原 C 布局，不导入旧 Sol 布局；当前目录 freeze 与阶段绑定隔离旧 identity/portion/record。
- pipeline.py、score.py、chroma_index.py 与 c_repro_sol_20261104_formatfix 对应文件字节一致，提示、检索、多码密度均值、份量数学、两种组外修正规则均未修改。run.py 的科学配置及 ASA 身份封存屏障未改。
- 请求 hash 含 endpoint、完整 payload（包括 model）和 namespace；保留文字 exact-request 与 embedding 精确复用，Gemini 不会命中旧 Sol 图片结果。newcommon.py 保留跨进程请求锁、32个全局运输槽及累计最多3次尝试机制；provider.py 保留返回模型严格校验、脱敏和异常停止。
- freeze_value() 加入本地 config/provider/verify 源文件；verify_completed.py 保留完整843记录、ASA封存、营养算术、合法选项、组外修正和原索引检查，增加314新布局及实际日志/缓存模型检查。

独立执行：项目 .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/c_gemini_flash_20261105 -p 'test_*.py'，27 tests passed（含8项 provider 测试）。无 API 调用，未读取 private.env、任何 .env 或 key，未打开独立验收数据。结论仅涵盖源码和离线检查，不代表已验证网关支持 Gemini 参数或实际运行质量；实际模型返回校验失败将按现有机制停止批次。

## Gemini 输出包装兼容：一次有限补充检查

2026-11-05：**approved**，无 P1/P2 必修。本节仅检查 provider.extract_unique_json、chat 调用处的适配审计，以及预格式修复归档和总账范围，不重新审查其他流程。

provider.py:100-131 先保留任何本来合法的完整 JSON 值；否则只解码首个完整对象，拒绝对象外的花括号/方括号及独立合法 JSON 值，返回原始 substring。不会从数组或多个对象中挑选，不重写字段或数值；chat 仅对有图 Gemini 返回启用。provider.py:298-307 在原 _request/cache 之后适配，缓存保持原始返回，另记原文/提取文本/request hash。原字段与数值契约仍由原 pipeline 校验。该变化是模型输出包装兼容，不是重新判断食物或数量。

preformat_snapshot 保留旧源文件、freeze、authorization、prepared 和首图布局/失败记录及请求日志。compare_baseline.py:116-132 的递归 requests.jsonl 总账覆盖归档与新运行日志，因此原预检2次传输不会丢账；新运行 profile usage 仅为新目录当前 run，最终完整费用应以该递归总账为准。仍不宣称已缓存的未使用修复请求会在新解析路径中再次重放；只保证相同 payload 命中原始缓存时不重发成功请求。

独立重跑28项离线测试全通过。未读 private.env、.env、key，未调用 API，未打开独立验收。可继续新 prepare 和首图缓存重放；本结论不代替实际重放是否零重发的运行证据。

## 完成后独立离线复核（协调记录）

审查代理确认：completion/freeze有效，80项MAE/per_unit与summary/comparison一致，共同Exact确为63。N5五项raw/retained均改善；ASA识别及529整体改善，共同63重量退步。核验通过非20指标全达标。预测记录未改、未API、未读凭据或验收。
自动退出问题已登记，不能宣称协调器自然退出0；单独离线评分与核验成功。
