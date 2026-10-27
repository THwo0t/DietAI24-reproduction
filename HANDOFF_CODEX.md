# 给 Codex 的交接：DietAI24 复现

2026-10-27。之前由 Claude 协调和实现、Codex 审查；Claude 的额度用完了，下一步由 Codex 接手实现。

## 1. 项目和要求

- **目标**：复现 DietAI24（Communications Medicine 5:458, 2025, doi:10.1038/s43856-025-01159-0）的 MAE。
- **仓库**：`/home/lelouch/Data/Projects/DietAI24_original`。从作者发布的原代码开始，首个提交是 `5946365`。
- **教授的要求**：
  - 从原代码出发，原代码缺的部分按论文补；
  - 维护任务清单，即 CHECKLIST.md；
  - 实现和审查由两个相互独立的 AI 对话完成，见 AGENTS.md；
  - MAE 尽量接近论文。
- **论文**：
  - 全文在 `/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/paper/paper.txt`。CHECKLIST 和 REVIEW 里的论文行号都指这个文件。
  - 补充材料在 `paper/supplementary/`。

## 2. 现状

**第一轮已完成。**
- E2 用 `gpt-4o-2024-08-06` 在测试集上正式跑了一次，测试集是 ASA24 150 张、Nutrition5k 150 道。
- 两个审查节点都已审完、处理完。
- 结果在 `runs/test/`，报告是 REPORT.md。

**主要结果**（括号里是论文值）：
- **ASA24**：
  - 125 张给出编码，其中 Exact 21 张，占 16.8%（22–29%）。
  - 论文协议只对这 21 张算营养：重量 MAE 92.7 g（49.4），热量 93.0 kcal（47.7）。
  - 份量分类准确率 42.9%（74.3%）。
- **Nutrition5k 完整的菜**（n = 86）：
  - 重量 95.0 g（45.1），热量 123 kcal（68.2）。
  - 重量普遍低估：平均低估 71.5 g，预测/真实比的中位数 0.68。可从 `runs/test/nutrition5k_nutrition.csv` 重算。

**报告在审查节点二之后按用户要求又改了一次**（见 git log），这次改动没有经过审查：
- ASA24 端到端（D3）不再展开，报告只写 Exact 数量和论文协议的 MAE；
- 加了 Exact 未命中的离线统计（`runs/test/diagnostics/exact_misses.py`）。

**费用**：付费调用合计 $6.44，其中 E2 $5.28。用户批准的总上限是 $20，剩余约 $13.5。

## 3. 必读

1. **AGENTS.md**：两个 agent 的分工、审查节点和提交方式。
2. **CHECKLIST.md**：开头的原则，A3（模型），C 组（流程），D 组（评测口径），E 组（运行和报告）。
3. **REPORT.md**：结果、偏差清单（第 4 节）和局限（第 5 节）。
4. **REVIEW.md 最后两节**：审查节点一、二的意见和处理结果。

## 4. 规则

- **API key**：
  - 用户自己把 key 放在仓库的 `.env` 里（git 忽略），`code/config.py` 只从这里读。
  - 不要打印、复制 key，也不要在聊天里索要。需要确认时只看有没有，不输出值。
  - 提交前确认 `runs/`、`logs/` 和提交内容里没有 `sk-` 开头的长串。离线测试里有防泄漏检查。
- **费用**：
  - OpenAI API 的付费调用在 $20 总上限内可以直接跑。
  - 先在开发集上量出每张图的费用，估算测试集要花多少。估算超出剩余额度时，先问用户。
- **下载**：数据和图片都在本地，不需要下载。需要新下载时先问用户。
- **测试集**：
  - 每种配置只正式跑一次。
  - 不在测试集上调提示词、解析或参数。
  - 提示词和解析的改动只能根据开发集的结果提出，由用户决定。
- **报告**：不要提操作系统、机器或运行环境。
- **语言**：和用户用中文交流。

## 5. 下一步：换 gpt-6.1-sol，检验 MAE 差距是不是模型能力造成的

### 5.1 目的

- 论文用的 GPT-4 Turbo 已下线，第一轮用 gpt-4o 代替，MAE 约为论文的 2 倍。
- 用户想知道，换一个更强的模型后差距会不会缩小。
- 只换模型、其他都不变，才能把差别归到模型上。

### 5.2 已知情况（CHECKLIST A3，2026-10-27 实测）

**temperature**：
- gpt-6.1-sol 能看图，但拒绝 temperature=0，返回 400 "Only the default (1) value is supported"，只能用默认值 1。
- 这偏离了论文的 temperature 0，要在 CHECKLIST 登记。报告里要写明：回答有随机性，一次运行只是一次抽样。

**推理 token**：它是推理模型，会额外产生推理 token。每张图的 token 数和费用都要在开发集上量。

**未验证，先在开发集上确认，再决定怎么处理并登记**：
- 推理模型可能不接受 `max_tokens`，要求改用 `max_completion_tokens`。
- 原代码有两处 token 上限：描述步骤 200（`code/rag_food_code.py:48`），份量步骤 600（`code/chagApp_openai.py:76`）。推理 token 可能占掉上限，使回答为空。

### 5.3 不变的部分

- **样本**：测试集和开发集都不变（`df_results.csv`、`dish_metadata.csv`，以及对应的 `*_dev.csv`）。
- **向量索引**：复用 `index/chroma`，不重建；embedding 模型仍是 text-embedding-3-large。
- **提示词和解析**：与 E2 相同，包括 REPORT 4.5 的三处适配。
- **评测**：`code/evaluate.py` 不变，口径与 E2 相同。

### 5.4 要改的地方

- **模型配置**（`code/config.py`）：
  - `MODELS` 的 `llm` 和 `llm_vision` 要能换成 gpt-6.1-sol。
  - 对这个模型不发送 temperature，或发送 1。
  - 做成可选配置（例如命令行参数），默认仍是 gpt-4o，这样第一轮还能照原样复跑。
- **单价**（`code/run_experiment.py:38`）：
  - 在 `PRICES` 里加上 gpt-6.1-sol 的单价，查 OpenAI 官方价目表，写明来源和日期。
  - 缺了单价，费用统计会报错停下。
- **token 参数**：如果 5.2 确认有问题，把 `max_tokens` 改成 `max_completion_tokens`，或者调整上限。
- **提交和登记**：
  - 每项改动一个提交（AGENTS.md）。
  - 在 CHECKLIST 新增一组条目，例如 F 组"模型对照"，写明理由和论文出处。
  - 离线测试要覆盖新配置：请求里的模型名、temperature 和 token 参数。
- **运行目录**：
  - `run_experiment.py` 发现配置不同时，会拒绝复用旧的运行目录，所以要用新目录。
  - 例如 `runs/dev-gpt-6.1-sol/` 和 `runs/test-gpt-6.1-sol/`。

### 5.5 步骤

1. **离线改代码、加测试**：
   - 在仓库根目录跑 `.venv/bin/python -m unittest discover -s tests`，现在是 107 项，全部通过，不调用 API。
2. **开发集试跑**：
   - `cd code && ../.venv/bin/python run_experiment.py --split dev --run_dir ../runs/dev-gpt-6.1-sol --workers 4`。
   - 检查拒答、空回答、解析，以及 API 日志里实际提供服务的模型名。
   - 量出每张图的费用，估算测试集费用。
3. **审查节点一**：
   - 另开一个独立的 Codex 对话做审查。它只改 REVIEW.md，只审一遍，提示词是 `agents/review_prompt.md`。
   - 以前在本机是这样调起的：`/usr/lib/chatgpt/resources/codex exec --sandbox workspace-write -c 'approval_policy="never"' -C <仓库> -o <结果文件> - < <提示词文件>`。
   - P1、P2 处理完再继续。
4. **测试集正式运行一次**：
   - `cd code && ../.venv/bin/python run_experiment.py --split test --run_dir ../runs/test-gpt-6.1-sol --workers 4`。
5. **对照、报告和审查**：
   - 按 5.6 对照 gpt-4o（`runs/test/`）和 gpt-6.1-sol 的结果，写进报告。
   - 审查节点二审一遍。

### 5.6 怎么比较

**识别**：
- 编码成功率，Exact 数量和比例（any、first），Close，Far。
- Exact 未命中的原因：用 `runs/test/diagnostics/exact_misses.py` 的方法，脚本里的运行目录写死为 `runs/test`，需要改成参数。

**论文协议 MAE**：
- 两个模型各自的 Exact 子集不同，n 只有二十张左右。
- 除了各自子集上的 MAE，还要在两个模型都 Exact 的共同图片上比较 MAE 和份量分类准确率。
- 共同图片上的营养密度一样，差别只来自份量判断，最能说明模型能力。

**Nutrition5k**：
- 完整的菜的 MAE、克重的平均符号误差、预测/真实比的中位数，看低估有没有改善。
- 也在两个模型都完整的共同菜上比较。

**区间**：
- 参照 `runs/test/diagnostics/bootstrap.py`。
- 最好按编码（ASA24）或按菜（Nutrition5k）配对重抽，算两个模型差值的区间。

**解读**：
- **标签歧义**：Exact 有上限，换模型也消除不了。见 REPORT 2.2：150 行只有 117 张不同的照片，同一组牛奶份量照片中的三张各对应 7 个标签。
- **份量和 MAE 明显接近论文**：差距主要来自模型。
- **仍是 2 倍左右**：差距主要来自样本、协议或数据，不是模型。

## 6. 文件速查

- **`code/`**：
  - `run_experiment.py`：一次跑完选码、份量、营养和指标，记录配置、费用（`cost.json`）和 API 响应日志；
  - `rag_food_code.py`：描述、检索和选码；
  - `rag_portion_size.py`：份量，`--end_to_end` 是 D3；
  - `nutrient_estimate.py`、`nutrient_estimate_mix.py`：营养；
  - `evaluate.py`：全部指标；
  - `report_tables.py`：生成报告里的对照表；
  - `config.py`：模型、temperature 和 key 的读取。
- **`runs/`**：
  - `runs/test/`：E2 的全部记录；
  - `runs/dev*/`：开发集的几次运行。
- **`logs/openai_api.jsonl`**：全局 API 响应日志，不含 key 和消息内容。
- **`tests/`**：离线测试。
