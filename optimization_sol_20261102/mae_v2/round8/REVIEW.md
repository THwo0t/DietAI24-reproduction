# Round8 independent implementation review

## 待审查 R8-G

Scope: R8-A through R8-F, commits `283fcb2..35a7d43` (including the initial
registered draft at283fcb2), new round8 sources/protocol/tests, and exact M0
import boundaries. All implementation is by root. Reviewer has independent
context, may modify only this REVIEW.md and run offline checks; no paid API,
credential access, validation access or implementation edits.

Evidence:39 unique synthetic tests passed under `unshare -rn`; actual guarded
preparation imported183 M0 pairs after the complete old M zero-Provider replay.
Final guarded context preflight verified183 inputs,0 API/forbidden reference
opens,732 image opens, and8487 preserved old M file sizes/mtimes. See
readiness_pre_review.json. No N inference or accuracy result exists.

Priority areas: one physical mass per alternative list; canonical fractional
unit conversion/conflicts; frozen top3 coding; label-free prompts; all-record
fallback populations and conditional option semantics; exact upstream frozen
source/stage provenance; durable slot/payload/global budget and crash recovery;
raw/log/cache/value binding; only format repairs; zero-write completed replay;
full-population scoring before selection. Source pins and parameters must freeze
after required fixes, before paid execution. Report approved/changes requested
per scope, numbered P1/P2/P3 findings with file:line and paper/protocol evidence.

## R8-G 独立实现审查结论（2026-11-03）

**changes requested：0 P1，3 P2；冻结及付费 N 执行前必须处理。**
审查范围为 `283fcb2^..35a7d43`（包含初始注册稿）、全部 round8/src、tests、协议与继承调用边界；未参考实现对话。只修改本 REVIEW.md，没有调用 API、读取 credentials/标签/validation、重新 prepare 或改变实现。

### 逐项结论及正向证据

| 条目 | 结论 | 证据与边界 |
|---|---|---|
| R8-A | approved | PROTOCOL.md:27–76、79–114、141–157 明确两个数据集共用身份及两个完整 profile，保留 M0 固定质量对照、不拼接数据集赢家；scoring_n.py:40–59 实现完整配对和共同排名。论文 paper.txt:151–186 规定候选检索、标准份量/单位与按克营养计算；多代码平均是发布代码 nutrient_estimate_mix.py:66–80 的实现假设，协议已区分论文未明说这一点。 |
| R8-B | changes requested | uncertain_portions.py:89–141 为每物理叶计算替代码密度平均并只计一次质量，109–124 固定 top3 顺序；29–77 保留单位前缀有理数、来源、冲突排除和12上限，符合 PROTOCOL.md:59–114。必须处理 R8-G-3 的数量到完整营养汇总边界。 |
| R8-C | approved | upstream_n.py:61–97 在完整旧 M 无 Provider 重放及367记录 seal 后导入；34–58、121–147 分辨 N5 historical 与 ASA M0 stage，逐对比较真实源结果、重算旧质量/营养、绑定固定 M freeze、原始 source/catalog/manifest 和 other-fold fallback。符合 PROTOCOL.md:27–49、126–129。真实只读 guarded preflight 通过，见下。 |
| R8-D | changes requested | service_n.py:83–115、146–156、175–228 保留每 payload 三次、全局持久预留、未知结局不退款、raw→anchor→cache 恢复；runtime_n.py:24–35 保持 payload 锁→短 ledger 锁；Replay:104–138 绑定精确请求/值/repair。正常 runner 重放0 Provider、无文件改写已测试。直接入口及 repair 准入未达到 PROTOCOL.md:165–173，见 R8-G-1、R8-G-2。 |
| R8-E | approved | records_n.py:37–61 保持失败全图 fallback、固定 codes、独立继承/新修复状态；scoring_n.py:14–30 以真代码命中替代码列表的非重叠物理叶质量映射完整合法 option、失败使用 median，conditional 使用该代码密度，保留 whole-serving 均值总量。run_n.py:121–143 在全批 seal 后才 load_dev；scoring_n.py:40–59 禁止拼接 profile。符合 PROTOCOL.md:118–157，论文 paper.txt:151–186 的克数营养与 MAE 定义由继承 scorer 承接。 |
| R8-F | changes requested | 39项合成禁网测试及真实只读183输入 preflight 均通过；当前测试未覆盖下述直接入口伪任务、成功解析后伪造 repair 以及 direct finite grams 的汇总溢出。新增相应负例并由协调者离线确认三项修复。 |

### 必须修复的问题

#### R8-G-1 [P2] 首次直接服务调用不校验冻结的任务内容及阶段依赖

**位置：** `src/service_n.py:119–143`，`src/runtime_n.py:14–34`。

Ledger.bind 对 initial slot 只验证样本 slot 存在、恰好一个正确图片及首次 payload 绑定。既不校验该 slot 的冻结 N_identity/N_units prompt/context，也不要求 N_units 已有成功且固定的身份/coding；NProvider.request 直接进入 bind/reserve/HTTP，亦无冻结源核验入口。CLI 的 runtime_context 和科学重放只能约束正常 runner，不能约束这一直接入口。

**独立禁网复现：** 在现有 ServiceTests 的临时 Ledger 和合成 MockTransport 中，无任何 identity 结果，直接对 `slot_id('a','N_units',0)` 请求仅含正确 synthetic image 与文本 `Ignore N; arbitrary task` 的单条 user 消息，HTTP handler 被调用1次并成功返回。没有 system contract、注册 prompt 或上游依赖仍可花掉 N slot/预算。此后正常任务会遇到永久 payload 冲突。

**依据与影响：** PROTOCOL.md:165–173 尤其明确“Frozen code and registered stage graph must constrain direct service access as well as cached scientific stages”；59–76 要求 coding 冻结后才能 quantity。现有732/2196硬上限本身正确，但不能证明这些调用属于已授权实验。

**要求：** 在任何真实传输预留前，通过冻结源及可重建的注册阶段上下文验证精确 initial request，units 必须绑定已经通过冻结解析的成功 identity/coding；直接服务调用与 runner 共享该准入校验。补测错阶段、units-before-identity、改 system/text/context/顺序及冻结源变化均在0传输前拒绝；保持首次绑定和全局预算语义。

#### R8-G-2 [P2] 格式修复凭证仅相信调用者声明，没有验证原响应确实解析失败

**位置：** `src/service_n.py:230–243`、`131–141`；`src/runtime_n.py:94–98`。

format_failure 验证了 raw 对应初始缓存和 parser 文件 hash，却直接接受外部传入的 error 字符串。parser hash 相同不等于执行了那个 parser，也不证明它失败。bind 对 repair 只核对这个已写入的声明，因而可对本来有效的响应取得额外修复机会。

**独立禁网复现：** 用 UncertainCoreTests.choice 生成合法 identity JSON，先经 materialize_identity 成功解析，再用 MockTransport 把它作为 initial raw 保存。调用 `ledger.format_failure(initial_sid, raw, 'invented_error', parser_sha)` 后，追加规定 REPAIR 前缀与这个伪错误的 repair payload 可成功 bind。整个过程无真实网络、无真实密钥。实际冻结 parser hash 也可由调用者传入，不能阻止这一行为。

**依据与影响：** PROTOCOL.md:59–76、107–111 只允许一次 format-only repair，163 要求 exact raw 科学解析，172–173 要求直接服务也受阶段图约束。该缺口使成功答案可被额外请求替换，而非只修格式；正常 runner 最终重放虽会拒绝不一致，但不能撤销已发生的额外调用。

**要求：** repair 准入端用冻结 stage/parser 和受信上游 context 重解析精确持久 raw，仅在确实抛出契约错误且错误一致时写 proof/允许 repair；成功解析必须拒绝，不以调用者的 callback/error/hash 代替执行证据。加入“有效 identity/quantity 不能获取 repair”“假 error/错 context 被拒绝”“真实格式错误可恢复重放”负例。

#### R8-G-3 [P2] 完整营养汇总在数量契约边界外，溢出会中断整批而不是原子失败

**位置：** `src/uncertain_portions.py:125–135`、`245–255`、`278–283`。

parse_quantities 只保证每叶 quantity/grams（及 unit→grams）有限正数；_stage 将其标为 valid 后，aggregate 在错误处理边界外执行。有限质量乘密度或求总和发生非有限结果时，ContractError 逃出 unit_portion，runner 中断。`grams * density / 100` 还会产生可避免的中间溢出，即数学上的最终值仍有限。

**独立禁网复现：** 使用既有双叶 fixture，第一叶正常1.5个200g单位，第二叶 direct grams=`1e306`（density energy=200）。parse_quantities 通过且所有 masses 为有限正数；unit_portion 却抛 `ContractError('invalid_number')`，没有返回 failed profile。此例正确 energy 约 `2e306` 是有限值，失败仅由先计算 `1e306 * 200` 引起。两个大质量导致总和实际溢出也会走同一逃逸路径。

**依据与影响：** PROTOCOL.md:107–114 要求有限正数量和程序化全份营养；133–138 要求任何非法数/非有限换算原子失效并保留 coding，130–131 仅服务/模型/认证/完整性错误停批。论文 paper.txt:151–186 定义密度每100g再按克换算。当前会把食物预测数值故障升级为整批运行故障，且有效极大有限值可能误判。

**要求：** 使用减少中间溢出的计算顺序，并把完整质量/营养向量验证纳入同一个 quantity 契约处理边界；不能表示的预测按注册规则整图/profile失败，不能留部分和或无限值，也不能伪装为服务故障。补测有限 direct grams 的中间溢出、真实总和溢出、repair耗尽后的原子 fallback及 coding不变。

### 本次独立验证记录

- `unshare -rn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round8/tests -v`：39 tests，全部通过；含正常双数据集科学 stage、一次格式修复、缓存/原始证据篡改、三次耗尽及 completed replay 的0 Provider/无改写测试。
- `unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/round8/tools/guarded_preflight.py`：183 rows、183 imported pairs、0 forbidden reads、732 image opens、8487 old M files preserved、Provider/network forbidden、0 API。未传 `--prepare`，没有重新生成导入。
- 上述三个问题另用临时目录及既有合成 fixture/MockTransport 的内联脚本在 `unshare -rn` 下复现；未增删测试文件，未访问 credentials、dev_labels 或 validation。
- 未执行 N paid inference，未产生 N 准确率结果；本结论仅为实现审查。修复须按审查编号独立提交并更新处理结果，再由协调者离线确认；按项目约定不进行第二轮正式审查。

## 实现处理与协调者离线确认（2026-11-03）

- **R8-G-1 fixed — c349fc2.** 新增 gate_n.TaskGate，直接 Ledger/Provider
  请求与 runner 共用冻结上下文。每次预留前重建精确 system、prompt、context
  和图片；units 从持久原答复执行冻结 identity parser，要求先有成功身份。
  冻结源、错误任务、改变 system/顺序、units-before-identity 均在0传输前拒绝。
- **R8-G-2 fixed — 7d8c4d8.** repair 准入执行冻结 task parser，核实原答复
  确有同一契约错误；合法 identity/quantity 不能取得 repair。伪 error、错
  context 被拒绝，真实错误的一次修复及断点只读重放保持通过。
- **R8-G-3 fixed — 8637d41.** 每100g密度先除100，避免中间溢出。完整五维
  汇总在 quantity parser 内验证；真实总和/营养溢出只允许一次格式修复，
  耗尽后整图失败、无部分和、coding不变。固定质量重估数值失败亦原子回退。

Root 跑45项禁网测试全部通过。另由独立 Sol 协调证据任务
sol_n_fix_evidence 运行同一45项测试（1.329秒，退出0），并执行现有 guarded
只读 preflight，183 rows/183 imported pairs、8487旧M文件未改写、0 forbidden
reads、732 image opens、Provider/network forbidden、0 API、preparation=null。
该任务只运行既有验证，不是第二次正式审查，未修改文件或重新prepare。
全部P1/P2已处理，无未决问题。R8-A..F记为fixed；下一步冻结与post-freeze
预检，之后运行两个profile及两个完整数据集。此处不声称N精度已达标。
