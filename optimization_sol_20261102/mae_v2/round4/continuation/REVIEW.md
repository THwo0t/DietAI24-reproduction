# J 服务续跑独立离线审查

日期：2026-11-03。范围为本目录的 `SERVICE_CONTINUATION_PROTOCOL.md`、`integrity.py`、`provider.py`、`runner.py`、`evaluate.py` 及三份合成测试。只为这次新增服务续跑作一次审查，不重复旧正式节点。下列行号指实现者首次报告稳定、审查读取时的修复前版本；修复处理和定向确认由协调 agent 另行追加。

**结论：changes requested。共三项必须修复：P1 一项、P2 两项。** 除这三项外，本次指定范围未发现其他需阻断续跑的具体问题。

审查未读取真实 `private_registration*`、旧 stage 快照、实际请求日志、预测、开发或验证标签；未构造真实 Provider、调用 API 或下载数据。仅新增本审查文件，未修改实现、协议或原冻结源。

## 必须处理的发现

### R-SC-1 — changes requested — P2：评分器拒绝规范 service policy

证据：`integrity.py:69–73` 的唯一 policy 工厂明确包含 `max_workers: 2`；`SERVICE_CONTINUATION_PROTOCOL.md:29–32` 同样要求最多两个 worker。但 `evaluate.py:138–146` 用缺少 `max_workers` 的字典作严格相等比较。实际规范注册经 runner 保留到新 binding 后，必然在评分入口抛出 `single_registered_service_policy_required`，完整续跑也无法评分。`tests/test_evaluate.py:78–84` 手写的 fixture 同样漏了该字段，因而现有绿测试没有覆盖真实接口。

要求：评分器复用同一规范 policy 或执行等价的精确字段校验，不得通过删除正式注册字段迁就评分器。增加真实工厂产生的 `max_workers=2` policy 可通过、缺字段和改为 3 均在读标签前拒绝的合成用例。

### R-SC-2 — changes requested — P2：首次新 run 的并发初始化竞争

证据：`runner.py:228–245` 在确认新 run 未完成后，直接把 worker 交给 `old._execute`，没有先顺序调用 `store.initialize()`。两个 worker 首次进入 `ImportRunner` 的 `store.stage_runner`（`runner.py:182`）时，可同时发现新 `intent.json` 不存在，随后竞争原 ArtifactStore 的非阻塞独占初始化锁，一方抛出 `ArtifactBusy`。协调 agent 在 `test_full84_import_then_readonly_complete_verify_without_provider`、workers=2 的独立整套运行中实际捕获了此竞争。本审查的另一次 33 项运行通过，不能排除该时序问题。

要求：只在新的 runner 中、并发 `_execute` 之前，对 `saved is None` 的路径调用 `store.initialize()`；完成后的只读验证路径继续零改写。增加确定性测试，断言进入 `_execute` 时正确的新 intent 已存在，再覆盖 workers=2 和完成后只读重入；不要靠重复执行偶然通过来证明修复。原冻结 ArtifactStore 无需修改。

### R-SC-3 — changes requested — P1：snapshot state 未与原计数文件字节绑定，可低报累计次数

证据：`integrity.py:118–126` 分别校验 snapshot 的 SHA 格式和 `state.attempts` 范围，却没有证明两者描述同一份原 counter；`integrity.py:209–240` 核对当前文件 SHA 后仍把注册中的 `state` 作为预约起点；`provider.py:75–98` 据此推进并覆盖实际计数。

独立纯合成复现使用 `httpx.MockTransport`：一个非例外 payload 的实际原 counter 为 3，保留该文件正确 SHA，仅把注册 `state.attempts` 写成 2。`Registration` 和 Provider 前置校验通过，随后又发送一次 mock HTTP，并把 counter 写回 3；真实累计为 4，违反非例外最多 3 次规则。该复现未读取任何真实注册或 counter；它证明程序不能防止错误编制的注册，并不指称真实草案存在此错误。

要求：把原 counter 的状态与原字节 SHA 不可分割地校验，且在共享 counter 已推进、重启恢复时仍可验证原基线。可以保留不可变原字节快照，或按经核实的原 Provider 确切编码重建等价字节；不能用新编码假定旧 SHA，也不能只在当前文件仍未变化时临时比较。负例必须证明“正确原 SHA + 错误 state”在 HTTP client/请求前拒绝、原计数不变；同时覆盖外层注册 JSON 重新排序、合法第四次后恢复、原 timestamp 或 namespace 不一致。

## 已通过的审查项

下列 P 级表示审查关注级，不表示新增待修复问题。

| 编号 | 结论 | 关注级 | 证据与判断 |
| --- | --- | --- | --- |
| A-SC-1 | approved | P1 | `integrity.py:106–113,130–134,175–191` 将额外 allowance 限定为唯一 chat hash，并要求三条按 1/2/3 排列的 ReadTimeout、原计数三次及无注册成功 cache；`provider.py:124–138` 按累计 cap 停止第四次超时，不沿用旧版的越界 backoff。计数基线一致性问题单列 R-SC-3。 |
| A-SC-2 | approved | P1 | `provider.py:87–99` 在发送前依次 fsync 预约 audit、其父目录、counter 和其父目录；`provider.py:75–84` 将 audit 已记但 counter 未替换的预约视为已消耗。`tests/test_provider.py:185–199` 覆盖该崩溃窗口，恢复不能再发送已消耗的第四次。 |
| A-SC-3 | approved | P1 | `runner.py:111–151` 校验旧 stage exact inputs、旧 binding、外部 receipt、正文 hash，并复用原 raw reparse；已 receipted 的 pending 正文只读导入，不发布或清理旧文件。`runner.py:62–100` 用 Provider 原 fingerprint 逐一关联 raw_outputs/vector、request_refs、注册成功 cache，chat 还核原 counter 与成功日志。ArtifactStore 与 Provider 的 fingerprint 算法没有混用。 |
| A-SC-4 | approved | P1 | `runner.py:153–190` 将所有旧 sealed outcome 导入新 binding，并检查完整导入覆盖；结构失败结果与显式 terminal 不转成新的成功尝试。`tests/test_runner.py:59–72,105–127,150–179` 覆盖失败导入、旧文件字节/mtime 不变及新 stage 缓存后不重发。 |
| A-SC-5 | approved | P1 | `integrity.py:136–172` 验证注册、原/新源码、原日志、原成功 cache 及旧 stage 文件快照；`runner.py:194–208` 要求原 context/intent 完全一致，仅增加独立 service binding。没有修改旧科学配置、源冻结或伪造旧 J completion 的路径。 |
| A-SC-6 | approved | P1 | `evaluate.py:178–197` 先通过完整新 base 验证和外部训练/service 绑定，再校验固定 84/99 人口，最后才读取 pinned 开发标签。`evaluate.py:213–235` 直接复用原 `build_oof`、`_summary`、`select_profile`，不重新实现拟合或拼接目标；全部 fallback 保留在 84 主分母。 |
| A-SC-7 | approved | P2 | `evaluate.py:200–243` 顺序封存 raw score、84 个 OOF 记录及 fit_audit、校准评分/整 profile 选择；各阶段复核 base，最终评分后再核 base。`runner.py:228–266` 完成路径校验新 seal 后纯重放并比对 records，LazyProvider 不构造实际 Provider；完成 provenance 同时绑定续跑 audit/log/counters。 |

## 离线验证记录

- 审查独立运行当时载入的三份测试，共 **33 tests PASS，46.952 秒**。使用 Python 3.10 的 `-B`；同时禁止 `socket.socket.connect` 和 `socket.create_connection`。这些测试仅使用临时合成数据和 MockTransport。
- 独立补充的内存/临时目录负例确认 R-SC-3：`actual_old_attempts=3`、`registered_claimed_attempts=2`、`new_mock_http_calls=1`、`written_counter_attempts=3`、`true_cumulative_attempts=4`。
- R-SC-1 由两个生产模块的严格 policy 比对直接确认；R-SC-2 的实际竞争由协调 agent 捕获并与调用路径核对。测试全绿没有覆盖这两个跨接口/时序条件。
- 修复版的定向测试与协调 agent 的最终离线确认应另行记录。本文件不把实现者报告的修复测试当作第二次审查，也不宣称续跑已经获准执行或已完成评分。

## 实现处理与协调确认（同日，无复审）

- **R-SC-1 fixed**：评估器和合成 fixture 共用 `integrity.policy`，接受登记的 `max_workers=2`；遗漏或变更该字段均在读取标签前拒绝。定向 12 tests PASS。
- **R-SC-2 fixed**：未完成的新 run 在并发 worker 启动前调用 `store.initialize()`，完整验证路径仍只读。测试在 `_execute` 入口确定性检查 intent 已存在且绑定正确。
- **R-SC-3 fixed**：按原 Provider 固定四键顺序及确切 JSON 编码重建旧 counter 字节，严格绑定 state 与原 SHA；原 counter 推进后仍能复核基线。错误 state/正确 SHA、排序、时间戳及恢复负例已覆盖。R-SC-2/3 定向 24 tests PASS。
- 协调 agent 在网络隔离环境独立运行最终 **36 tests PASS，41.418 秒**。随后检查真实注册：35 份原源码与 7 份新源码、792 份旧运行文件、213 份计数快照、212 份成功响应缓存全部匹配。
- 网络隔离真实导入预检查通过：复核全部 **263 个已封存阶段、52 条完整旧预测**，剩余 32 条；未创建新 run、未构造 Provider、未读取开发标签或打开验证集。原运行文件和计数未改写。
- 上述是工程与导入证据，不是 MAE 结果。全部 P1/P2 已处理，按既有用户授权继续付费开发；完整 84 条封存后才运行评估。
