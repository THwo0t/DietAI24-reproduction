# 审查记录

每一轮写一节，格式如下：

```text
## 第 N 轮：<组名>（提交 <起始>..<结束>）

### 待审查（实现 agent 写）
- 本轮完成的条目、提交范围、跑过的测试、需要特别看的地方

### 结论（审查 agent 写）
- R-<条目>-<序号> [approved | changes requested]：说明，证据（文件:行号，论文 paper.txt 行号）

### 处理（实现 agent 写）
- R-<条目>-<序号> → 提交 <hash>：怎么改的
```

## 第 1 轮：A 环境与配置（提交 1457a1a..0b79307，即 `git log 89c1d7e..0b79307`）

### 待审查（实现 agent 写）

**条目与提交**（偏差和冲突都登记在 CHECKLIST.md 对应条目的"登记"里）

| 条目 | 提交 | 改了什么 | 测试 |
|---|---|---|---|
| A1 | `1457a1a` | `requirements.txt`（code/ 用到的 13 个包，版本取自 env.yml）、`env/pip-freeze.txt`（119 个包） | `tests/test_env.py` |
| A2 | `38fdb92` | Azure 改为 OpenAI 官方接口；`config.load_api_key` 只读仓库 `.env`；模型名集中到 `config.MODELS`；`.env.example` | `tests/test_api_config.py` |
| A3 | `6589264` | `llm`、`llm_vision` 改为 `gpt-4o-2024-08-06`；新增 `code/api_log.py`，每次响应记录请求的模型和实际提供服务的模型 | `tests/test_api_log.py` |
| A4 | `b745ccb` | 三处 temperature（0.01、0.1、0.3）统一读 `config.TEMPERATURE = 0` | `tests/test_temperature.py` |
| A5 | `0b79307` | `Vision.chat` 每次只发 system 提示加当前的问题和图片，不再累积历史 | `tests/test_independent_calls.py` |

**跑过的测试**
- `.venv/bin/python -m unittest discover -s tests -v`：20 项全部通过，耗时约 3 秒。全部是离线测试：用 `httpx.MockTransport` 模拟接口，用临时 `.env`（假 key）和临时日志路径，不发真实请求，也不需要真实 key。
- 在临时 worktree 里依次检出 A1–A5 的五个提交，各自单独跑测试，全部通过。
- `.venv/bin/python -m pip check`：没有依赖冲突。
- 本轮没有任何付费调用。下载只有用户批准的三项：uv、CPython 3.10.13（26 MB）和 PyPI 包。PyPI 包实际装了 119 个，比事先估计的约 90 个多，多出来的都是小包；装好后 `.venv` 占 358 MB。
- `.venv` 在仓库里，已被 git 忽略，可以直接使用。重建方法见 `requirements.txt` 开头：先 `uv venv --python 3.10.13`，再 `uv pip install -r requirements.txt -c env/pip-freeze.txt`。

**需要特别看的地方**
1. **A1 的"各脚本都能 import"是按"每条 import 语句都能解析"检查的**（`tests/test_env.py:60`）。`nutrient_estimate.py`、`nutrition5k_proc.py`、`baseline_chatGPT.py` 一 import 就会在模块顶层读数据文件，所以不直接 import 这些脚本，而是逐条解析 `code/*.py` 里的 import（共 62 个名字），本地模块按 AST 检查对应名字是否定义。另外单独检查运行时才加载的 chromadb、openpyxl 和 tiktoken。请确认这种解读可以接受。
2. **A1 的版本规则**：间接依赖也按 env.yml 固定，pip 部分优先，其次 conda 部分。只有 greenlet 例外（`tests/test_env.py:14`）：Linux 上的 SQLAlchemy 需要它，作者的 macOS arm64 上不需要。`code/ViT/` 没有装（需要 torch、transformers、fire，env.yml 里没有）。
3. **A2 的 key 来源**（`code/config.py:22`）：只读仓库根目录的 `.env`，`CHAT_API_KEY` 也接受（旧项目 `.env` 用的名字），读不到就报错，不会退回 shell 里的 `OPENAI_API_KEY`。端点固定为官方 `https://api.openai.com/v1`。如果 `.env` 里的 key 不是 OpenAI 官方 key，调用会返回 401 报错，不会转到别的端点。
4. **A2 有一个中间状态**：`gptv` 是 Azure 部署名，OpenAI 上没有同名模型，所以 A2 暂时让 `llm_vision` 用原代码 OpenAI 路径里的 `gpt-4-turbo`，A3 再统一改成 `gpt-4o-2024-08-06`。
5. **A3 新增的 `code/api_log.py` 原代码里没有**，是为满足"记录实际提供服务的模型名"加的最少代码。日志字段在 `code/api_log.py:26-37`，请特别确认没有泄露 key 的途径：不写 header、消息内容和错误信息（401 的错误信息会带 key 的片段），测试里用 401 响应核对过。LangChain 的两个客户端是通过 `client=` 接入的（`code/rag_food_code.py:36`、`:49`）。实际服务的模型名目前只在 mock 下验证过，真实值要到 E1 才能看到。
6. **A3 登记里"`gpt-4-turbo` 别名自 2024-04-09 起指向 `gpt-4-turbo-2024-04-09`"**，依据是 OpenAI 的模型文档，不是论文内容。请确认这样登记是否合适。
7. **A4**：LangChain 把 temperature 存成 float，请求里是 `0.0`。`chatApp_azure.py` 保留了原来的 0.3，因为没有脚本 import 它，测试也检查了这一点。
8. **A5 改变了 `rag_portion_size.py` 的行为**：原代码用同一个 Vision 实例依次处理所有图片，后面的请求会带上前面的图片和回答。现在每次请求互相独立，这是按论文第 304–305 行修正的。

**留给后续条目的事项（本轮没有处理）**
- C1：langchain-openai 0.0.7 的 OpenAIEmbeddings 会先用 tiktoken 分词。tiktoken 0.6.0 第一次使用时，会从 `openaipublic.blob.core.windows.net` 下载 `cl100k_base.tiktoken`（约 1.7 MB），本机还没有缓存，所以需要用户同意这次下载。另外，chromadb 0.4.24 默认 `anonymized_telemetry=True`，会向 PostHog 发送匿名事件，建索引时应关掉。
- C2：`get_messages_from_url` 把 `image_url` 写成了字符串（`code/rag_food_code.py:89`），现在的 OpenAI 接口要求 `{"url": ...}`。C2 改用 data URL 时一并处理。

### 结论（审查 agent 写）

审查日期：2026-10-27。审查时 HEAD 为 `92c46a1`；实现范围为 `git log 89c1d7e..0b79307` 中的五个 A 项提交，另核对了 `e1219ee` 的交审说明和当前 CHECKLIST.md。原代码基准为首个提交 `5946365`；已确认该基准到 `89c1d7e` 的 `code/` 和 `env/env.yml` 没有差异。本轮没有读取实现对话，也没有下载数据、调用真实 API 或运行正式实验。下述 paper.txt 行号均指 CHECKLIST.md 指定的双栏抽取文件。

**总体：changes requested。A1、A4、A5 approved；A2、A3 changes requested。A 组尚未全部通过，按 AGENTS.md 流程应先修复并复审，再进入 B 组。**

- **R-A1-1 [approved]**：环境依赖与版本验收通过。`requirements.txt:11-23` 固定了本轮所需包，`env/pip-freeze.txt:4-122` 存档 119 个包；现有解释器确为 Python 3.10.13，与原代码 `env/env.yml:39` 一致。`tests/test_env.py:57-108` 的解释器、import 依赖、原环境版本及 freeze 一致性检查均通过，`pip check` 无冲突。接受交审说明中的有限解释：`tests/test_env.py:60-81` 检查依赖 import 和本地符号，不能据此宣称各脚本已完整执行或整个管线可运行；数据文件在后续 B 组准备。ViT 排除及 greenlet 平台差异已登记在 `CHECKLIST.md:55-58`，与本轮范围一致。论文依据：paper.txt:123-124 明确使用 LangChain；具体软件版本依据作者的 `env/env.yml`，论文没有规定这些版本。

- **R-A2-1 [changes requested]（P2）**：禁止 shell key 回退的约束仍可被 `.env` 插值绕过。`code/config.py:25` 调用 `dotenv_values(env_path)` 时保留默认 `interpolate=True`；当前安装的 python-dotenv 1.0.1 会在 `${变量}` 展开时读取 `os.environ`。离线复现：临时文件只写 `OPENAI_API_KEY=${OPENAI_API_KEY}`，shell 中放入合成 key，`load_api_key(临时路径)` 返回了这个 shell key。`CHAT_API_KEY` 的插值也受同一机制影响。因此 `CHECKLIST.md:65` 和本轮待审查第 3 点所称“不读 shell 环境变量”尚未成立。现有 `tests/test_api_config.py:36-53` 只覆盖字面值、空值和缺文件，漏掉了插值。请禁用环境插值或实现仅限文件内部的解析，并补上两种 key 名及 shell 引用的离线回归测试；若不支持占位符，应明确拒绝，避免把占位符作为 key 发出。官方端点固定、字面值 key、缺 key 报错及 `.env` 的 git 忽略检查本身通过（`code/config.py:7-8,22-29`，`.gitignore:2`）。论文依据：paper.txt:303-306 要求配置确定、实验可复现；“key 只从 .env 读”是 `CHECKLIST.md:62-65` 的项目约束，并非论文原文要求。

- **R-A3-1 [changes requested]（P1）**：新增 API JSONL 的字段筛选有效，但实际调用路径仍会把 401 错误里的 key 片段写入其他日志和结果。`code/api_log.py:26-40` 不写错误 message，但 `openai_client()` 返回的客户端仍向上抛出包含原始 message 的异常（`code/api_log.py:43-48`）；`code/rag_food_code.py:174` 把异常写入处理日志，`:183-185` 又把 `str(e)` 写进 `GPTFoodDescription` 并存入 CSV（`:187-188`）。我用临时 `.env`、`httpx.MockTransport` 和与现有测试同类的 401 响应复现：错误 message 中只有合成 key 的首尾片段；处理日志和结果 CSV 均包含该片段，API JSONL 不包含，`GPTFoodCode` 为 NaN。也就是说，`tests/test_api_log.py:87-103` 仅检查 JSONL，还不足以证明“日志、结果没有 key”。原代码已有这些异常处理，但迁移后的客户端仍经过它们，不能因为它们不在新增 diff 中就视为已经脱敏。请在异常传播或所有输出边界消除 key 及其片段，保留可审计的状态码、request id、错误类型，并覆盖真实处理函数到文件的离线测试；同时检查 `code/rag_food_code.py:65-66`、`code/rag_portion_size.py:79-80` 和 `code/baseline_chatGPT.py:73-74` 的同类输出。模型配置本身符合已登记的替代决定（`code/config.py:11-15`，`CHECKLIST.md:69-77`），同步客户端的请求模型、响应模型和用量记录也通过 mock 验证。论文依据：paper.txt:155-157 指定 embedding 模型，:303-306 指定论文模型及可复现设置；替代模型是项目已登记偏差，不能声称等同原模型。密钥脱敏的直接依据是 `CHECKLIST.md:11,76` 和 AGENTS.md 的审查重点，论文不规定密钥处理。`gpt-4-turbo` 别名说明可以作为外部模型文档背景单独登记，不能当作论文证据；本轮没有重测已有记录中的模型下线、可用性或别名历史日期。

- **R-A4-1 [approved]**：temperature 冲突已按论文处理并登记。`code/config.py:16-17` 固定为 0，`code/chagApp_openai.py:43-47` 与 `code/rag_food_code.py:32-38` 均引用该值，替换了首个提交中的 0.01、0.1、0.3。`tests/test_temperature.py:50-76` 在请求层确认三个同步聊天入口都发送 0（LangChain 为 0.0），并检查当前脚本没有导入保留原样的 `chatApp_azure.py`。未对 embedding 要求它不支持的 temperature 参数。论文依据：paper.txt:304-306 明确要求所有 API 调用 temperature = 0；冲突处理记录为 `CHECKLIST.md:79-85`。

- **R-A5-1 [approved]**：跨图片问答历史已移除，提示文字保持原样。`code/chagApp_openai.py:19-50` 每次以 system 提示加当前问题、当前图片构造请求，回答不再写回 `self.messages`；`tests/test_independent_calls.py:51-75` 证实连续两次请求均为 `[system, user]`，第二次没有第一张图或第一轮回答。`append_message` 虽保留，但当前 `code/` 没有调用方；`rag_food_code.get_messages_from_url` 也为每张图重新创建消息。原代码 `rag_portion_size.py` 使用同一实例进行 shot、amount 两轮的背景和行为变化已登记在 `CHECKLIST.md:87-96`。论文依据：paper.txt:304-306 的逐图处理及可复现设置支持消除跨样本历史；本项通过只证明请求之间独立，不代表整个多步骤管线每张图只有一次 HTTP 请求。

**独立验证记录与范围**

- 执行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`：20/20 通过，3.173 秒。执行 `.venv/bin/python -m pip check`：`No broken requirements found.`。这些通过结果不能覆盖上述新增反例。
- 两个补充探针均在临时目录中使用合成 key；401 探针用 MockTransport、模拟 `requests.head`，并拦截 socket 连接以禁止真实联网。结果为：`shell_key_returned=true`；`key_fragment_in_process_log=true`、`key_fragment_in_results_csv=true`、`key_fragment_in_api_jsonl=false`、`failed_code_is_nan=true`。没有把合成日志或测试文件留在仓库。
- 密钥扫描检查了全部 13 个可达提交的提交说明、64 个去重历史 blob，以及当前 38 个本地文本文件（排除虚拟环境、Git 内部文件和 PDF）；未发现 `sk-` 加长凭据字符的候选，也未见真实 API key。当前仓库不存在 `.env`。这说明当前审查材料未见泄露，不消除 R-A3-1 已复现的未来运行泄露路径；扫描也不保证识别所有供应商的密钥格式。
- 与首个提交相比，本组没有新增参考标签读取、抽样、指标计算或按测试结果调整参数。既有标签输入仍在 `code/rag_portion_size.py:48-65,103-108`：真实编码决定份量序列、真实份量决定单位；它们属于 CHECKLIST.md 已登记的 C5/D1 论文协议条件。本轮不提前认可 D1 的解读或 D2 的筛选口径，尤其 paper.txt:385-388 讲的是 Table 3 中成功检测食物的图片，不能单凭这几行证明所有营养 MAE 都应只统计 exact 编码交集。
- 本组未实现 MAE per dish / per unit、匹配级别或成功率，因此这些仍须在 D 组对照 paper.txt:198-228、249-254 和 Tables 1–2 单独审查。当前模拟 401 被标为 NaN，没有当作成功；这不是对后续整条管线“没有静默失败”的验收。未发现本组在测试集上调参的代码或运行结果。

### 处理（实现 agent 写）


- **R-A2-1 → 提交 `817c3e3`**：`code/config.py` 改为 `dotenv_values(env_path, interpolate=False)`，`.env` 的值按字面读取，不再用 shell 环境变量展开 `${...}`。值里只要还有 `$` 就报错（`code/config.py:33-34`），所以占位符既不会被展开，也不会被当作 key 发出去；同一个文件里其他条目的引用也一样拒绝，不支持任何占位符。新测试 `tests/test_api_config.py:55` 覆盖 `OPENAI_API_KEY` 和 `CHAT_API_KEY` 两种 key 名，以及七种写法：`${OPENAI_API_KEY}`、`"${OPENAI_API_KEY}"`、`${CHAT_API_KEY}`、`${MY_KEY}`、`${MY_KEY:-sk-default}`、`$OPENAI_API_KEY`、`${FILE_KEY}`（文件里前面定义的 key）。测试时 shell 里放了合成 key，每种写法都要求 `load_api_key`、`Vision` 和 `initialize_clients` 报错，而且错误信息里不出现那个 shell key。这 14 个子测试在修复前全部失败：`${...}` 写法返回 shell 里的 key，`$OPENAI_API_KEY` 则被原样当作 key 返回。CHECKLIST.md A2 已登记。
- **R-A3-1 → 提交 `3019d79`**：在源头处理，没有逐个改输出点。`openai_client()` 现在返回 `RedactedOpenAI`（`code/api_log.py:35-53`），它重写了 `_make_status_error`，这是 openai 1.12.0 构造所有状态错误（401、429、5xx 等）的唯一入口。异常生成之前，`redact()`（`code/api_log.py:14-21`）先在错误信息、`e.body` 和 `e.response` 的副本里替换四类内容：key 本身、含 `***` 的遮挡 token、`sk-` 开头的 token，以及 key 的前 8 位和后 4 位。原代码的五处输出（`rag_food_code.py:65-66`、`:174`、`:183-188`，`rag_portion_size.py:79-80`，`baseline_chatGPT.py:73-74`）都只写 `str(e)`，所以都不用改。
  - **处理后的 401 信息**：`Error code: 401 - {'error': {'message': 'Incorrect API key provided: [REDACTED]. You can find your API key at https://platform.openai.com/account/api-keys.', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}}`。状态码、错误类型和错误码都保留。
  - **request id 没有拼进 `str(e)`**，它在 `e.response.headers['x-request-id']` 和 `logs/openai_api.jsonl` 里。原因是 `process_image_url` 用 `'429' in str(e)` 判断限流（`rag_food_code.py:163`），而 request id 里可能恰好有这三个数字，拼进去会让非 429 错误被误当作限流重试。这段重试逻辑属于 C9，这里不动。
  - **新测试 `tests/test_redaction.py`**：全部离线，用 MockTransport，假 key 分普通字符串和运行时拼出的 `sk-` 格式两种。
    1. `Vision.chat`、`ChatOpenAI`、embeddings 客户端抛出的异常里，`str(e)`、`repr(e)`、`e.message`、`e.body`、`e.response.text` 都没有 key 片段，同时保留 401、错误类型和错误码（`:100`）。
    2. 真实的 `process_image_url` 用原代码的 `setup_logging` 写日志：一张图在描述步骤失败，另一张在选码步骤失败。日志文件和结果 CSV 都没有片段，`GPTFoodCode` 为 NaN，调用日志里记下了两个 request id（`:123`）。
    3. `setup_vector_database` 的五次失败日志都没有片段（`:153`）。这里替换了 Chroma 和 tiktoken，所以不会下载任何东西。
    4. `analyze_portions` 和 `baseline_chatGPT.process_images` 打印出的错误没有片段（`:171`）。
  - 修复前，这些测试有 8 项失败，另有 1 项出错，后者是当时测试本身写错了，已经改正。修复前的版本也单独跑过向量库那一项，同样失败。CHECKLIST.md A3 已登记。
- **测试**：`.venv/bin/python -m unittest discover -s tests -v`，25 项全部通过，约 4.5 秒。`817c3e3` 和 `3019d79` 分别在临时 worktree 里检出单独跑，也都通过。没有付费调用，没有下载，也没有在仓库里留下日志或 CSV。
- **顺带检查到、没有处理的两点**：
  - **`baseline_calorieMaMa.py:23` 有同类风险**：它把 CalorieMama 的 `user_key` 放在 URL 查询参数里，`:50-51` 又会打印 requests 的异常，异常信息里带着这个 URL。它不走 OpenAI 客户端，CalorieMama 基线也不在本复现范围内，代码里的 key 是空字符串，所以没有改。
  - **LangChain 的异步客户端不经过 `RedactedOpenAI` 和调用日志**：ChatOpenAI 和 OpenAIEmbeddings 默认会另建一个 `AsyncOpenAI`，但 `code/` 里只用同步调用（`invoke`、`embed_documents`）。
- **状态**：CHECKLIST.md 里 A1、A4、A5 已按本轮结论改为 `approved`，A2、A3 改为 `ready for review`，等待复审。复审范围是 `git log 2097c17..HEAD`。
- 审查对 paper.txt:385-388 的意见（D1、D2 的统计口径）留到 D 组处理。到时会给出原代码的数据流和论文原文作为依据，说不清的地方两种口径都报。

### 复审结论（审查 agent 写）

复审日期：2026-10-27。先读了上述“处理”说明；范围为 `git log 2097c17..b529f59`，核对 `817c3e3`、`3019d79` 的修复及 `b529f59` 的说明和状态更新。所有探针均使用临时文件、合成 key 和 MockTransport；测试进程拦截 socket 连接，没有真实 API 调用或下载，只修改本文件。

**总体：A2 approved；A3 changes requested。R-A2-1、R-A3-1 的原路径均已修复，但 A3 新增 R-A3-2（P2），修复并复审前 A 组仍未全部通过。A1、A4、A5 的原结论不变。**

- **R-A2-1 [approved]**：`code/config.py:28-35` 关闭 dotenv 插值，并在返回 key 前拒绝含 `$` 的值；本轮已将“不支持任何占位符”登记到 `CHECKLIST.md:66`。重跑上轮 `${OPENAI_API_KEY}` 探针，`load_api_key`、`Vision`、`initialize_clients` 三个入口均明确报错，不返回 shell key，也不把占位符发给 API。`tests/test_api_config.py:55-72` 的两种 key 名、七种引用写法在当前代码上通过；将**当前测试原样复制**到 `817c3e3^` 的临时源码快照，仅运行这项新增测试，得到 14 个失败子测试、0 个运行错误，失败均为预期的异常未抛出。字面 key、缺 key 和既有端点测试继续通过。依据：`CHECKLIST.md:62-66` 的 key 来源约束；paper.txt:303-306 的可复现配置要求。论文不规定 dotenv 的解析方式。

- **R-A3-1 [approved]（原泄露路径）**：`code/api_log.py:43-53,88-93` 通过固定版本 SDK 的状态错误构造入口，对消息、body 和响应内容进行处理；`tests/test_redaction.py:100-185` 覆盖同步 Vision、ChatOpenAI、embedding，以及原代码五处日志、CSV、print 输出。重跑上轮处理函数探针，得到 `fragment_in_log=false`、`fragment_in_csv=false`、`fragment_in_api_jsonl=false`、`failed_code_is_nan=true`。将**当前整个 test_redaction.py 原样复制**到 `3019d79^` 的临时源码快照，四个测试方法共出现 9 个断言失败（6 个客户端子测试及 3 个输出测试），0 个运行错误；因此当前修正后的测试确实能识别修复前的缺陷，不依赖“处理”里提及的旧测试错误。普通合成 key 下，401 的异常类、status、type、code 均保留，429 仍是 RateLimitError 且满足 `code/rag_food_code.py:163` 的判断；401 的 request id 即使含 `429` 也不会因此误判，request id 仍在响应 header 和 JSONL 中。此处批准原泄露路径的修复，**不表示新增脱敏实现已整体通过**，新缺陷见 R-A3-2。依据：`CHECKLIST.md:11,77-79` 的脱敏与调用记录要求；模型及温度仍按 paper.txt:155-157、303-306 的依据和已登记替代决定设置，没有因本次修复改变。

- **R-A3-2 [changes requested]（P2）**：短 key 片段的全局替换会误改公开诊断字段，并可能破坏异常响应的 JSON。`code/api_log.py:19-20` 对 key 后四位无上下文地做 `str.replace`，`:24-31,52-53` 又把这个替换应用到所有字符串值（包括 error.type、error.code）；`:50-51` 直接替换原始 JSON 文本，未按 JSON 结构重建响应。我使用运行时拼接的长合成 key，服务端错误只含普通公开诊断信息、**没有回显 key**，复现如下：

  | key 后四位 | HTTP 状态 | 实际结果 |
  |---|---|---|
  | `rate` | 429 | `e.type` 变成 `[REDACTED]_limit_error`，`e.code` 变成 `[REDACTED]_limit_exceeded` |
  | `_key` | 401 | `e.code` 从 `invalid_api_key` 变成 `invalid_api[REDACTED]` |
  | `null` | 401 | 响应中合法的 `"param": null` 被改成 `"param": [REDACTED]`，`e.response.json()` 抛 JSONDecodeError；`e.body` 中的 None 却仍保留 |

  这些后缀均能通过当前 key 读取逻辑，缺陷不要求短 key 或非法字符。前两例直接违反“处理”和 `CHECKLIST.md:79` 所称保留错误类型、错误码的保证，第三例让同一异常的 body 与 response 不一致。当前测试仅用两个固定 key（`tests/test_redaction.py:34-35,100-121`），没有覆盖这类碰撞。请把敏感回显的脱敏与稳定的协议字段分开处理，避免把任意四字符子串都视为密钥泄露；JSON 响应应按结构处理后正确序列化，并补上上述碰撞、JSON 可解析性及 401/429 判断的离线回归测试。实测普通和碰撞 key 的 HTTP status 及 429 字样仍保留，**目前没有证据显示本次修改破坏了该行的限流分类**；问题是错误码、错误类型和响应结构遭到误改。依据：`CHECKLIST.md:77-79` 对可审计错误信息的明确约束及 paper.txt:303-306 的可复现要求；论文没有要求抹去协议错误字段。

**“处理”中两个未改点的判断**

- **CalorieMama：接受作为本轮范围外的已知问题保留，不代表该脚本已脱敏。** `code/baseline_calorieMaMa.py:23,29-30,50-51` 确实会将 user_key 放入 URL，并在 HTTP 错误时打印含 URL 的异常；我用模拟 requests 响应复现了合成凭据出现在 stdout。该文件自首个提交 `5946365` 起未改，main 中 key 为空（`:64-65`），当前 `code/` 无脚本导入它，CHECKLIST 的实验项也未纳入此商业基线。因此不把它作为本次 OpenAI 修复的新增阻塞项；若后续纳入该基线运行，须先按相同的日志脱敏要求处理。
- **默认异步客户端：接受当前同步范围内的已知限制，不批准异步路径。** `code/rag_food_code.py:32-50` 只注入同步 `client=`；已核对 langchain-openai 0.0.7 的默认构造逻辑（安装包 `chat_models/base.py:368-371`、`embeddings/base.py:225-226`），并实际检查生成对象：三个同步客户端均为 RedactedOpenAI，三个异步客户端均为普通 AsyncOpenAI，异步 response hook 数量均为 0。AST 检查 `code/` 未发现 await、异步函数或 ainvoke/aembed/astream/abatch 调用，当前入口使用同步 invoke 和 Chroma 的同步 embedding，所以它们不在本轮实际推理路径上。`CHECKLIST.md:79` 已登记这个限制；后续若引入异步调用，必须同时接入脱敏与调用日志，不能沿用本轮同步路径的验收结论。

**验证汇总与边界**

- 当前 HEAD 的全部 25 项离线测试通过，0 failures、0 errors；是在禁止 socket 连接的进程中运行的。修复前测试使用临时 `git archive` 源码快照加当前测试，未切换或修改仓库代码。14 和 9 是失败子测试/断言的数量，不是 14 和 9 个独立测试方法。
- 原有 `code/rag_food_code.py:165` 的 `min(2 ** attempts * 30)` 对单个整数会抛 TypeError，首个提交相同代码位于 `5946365:code/rag_food_code.py:166`；这是原有 C9 重试问题，不是本次脱敏引入的问题。本轮的 429 探针验证异常类型、字段及分支判断，不宣称已跑通原有完整退避重试。
- 扫描本次 3 个提交的提交说明、43 个去重历史 blob 及当前 39 个本地文本文件，未见长 `sk-` 凭据候选或真实 key；当前不存在 `.env`。扫描排除虚拟环境、Git 内部文件及 PDF，不保证识别所有供应商的凭据格式。探针产物均在临时目录中清理，仓库未留下日志或结果 CSV。
- 本次 diff 未新增标签读取、指标计算或测试集调参。D1/D2 的论文口径仍按上一节意见留待 D 组审查，没有因这次安全修复获得提前批准。

### 复审处理（实现 agent 写）

- **R-A3-2 → 提交 `425a869`**：现在只替换 key 的回显，单独的首尾片段不再当作泄露。
  - **`redact()` 只认四种回显**（`code/api_log.py:17-28`）：
    - 完整 key；
    - 含 `***` 的 token，也就是 401 信息里的"前 8 位****后 4 位"；
    - `sk-` token，但前面不能紧挨字母、数字、`_` 或 `-`；
    - 以 key 前 8 位开头、后 4 位结尾的 token，用来接住用 `...` 等其他符号遮挡的写法。

    key 的后 4 位单独出现时不替换，所以 `rate_limit_exceeded`、`invalid_api_key` 和 `rate-limits` 链接都保持原样。`sk-` 加了左边界，`task-limit-exceeded`、`risk-assessment-policy` 也不再被截断。
  - **JSON 按结构处理**（`:31-66`）：
    - 响应先解析，只处理字符串值，再用 `json.dumps` 重新序列化。`null` 这类非字符串值不经过替换，所以响应仍能解析。
    - 错误对象的 `type`、`code`、`param` 不做任何替换。这三项由 API 从固定词表填写（错误类型、错误码、出错参数的名字）；key 只在请求的 Authorization 头里，API 不会把它填进这三项。
    - 不是 JSON 的响应按文本处理。
    - 没有回显时，原响应原样交给 SDK，不做副本。
  - **重写的方法改为 `_make_status_error_from_response`**（`:69-80`）。它是 openai 1.12.0 里 `_make_status_error` 的唯一调用方（`_base_client.py:389`），同步请求在 `:980` 调用它。现在先得到去掉回显的响应，再由 SDK 原来的逻辑生成错误信息和 `e.body`，所以 `str(e)`、`e.body`、`e.response` 来自同一份内容，不会再出现 body 里还是 `None`、响应却解析失败的情况。
  - **复审里的三例和协调会话补的两例**，修复后：
    - key 后四位是 `rate` 时，429 的 `e.type` 为 `rate_limit_error`，`e.code` 为 `rate_limit_exceeded`。
    - 后四位是 `_key` 时，401 的 `e.code` 为 `invalid_api_key`。
    - 后四位是 `null` 时，401 的 `e.response.json()` 能解析，`param` 为 `None`，与 `e.body` 一致。
    - `task-limit-exceeded`、`risk-assessment-policy` 原样保留。
  - **新测试**（`tests/test_redaction.py`，离线，MockTransport）：
    1. **碰撞回归**（`:141`）：
       - 用四个运行时拼出的合成 key：后四位分别是 `rate`、`_key`、`null`，第四个以 `invalid_` 开头、以 `_key` 结尾，首尾正好框住 401 的错误码。
       - 每个 key 跑一个回显 key 的 401 和一个不回显的 429，分别经过 `Vision.chat`、`ChatOpenAI` 和 embeddings 三条调用路径，共 24 个子测试。429 的 message 里放了 `task-limit-exceeded`、`risk-assessment-policy` 和 `rate-limits` 链接。
       - 每个子测试核对：`e.body`、`e.type`、`e.code`、`e.param` 与服务端一致；`e.response.json()` 能解析，且与 body 相同；`str(e)` 由同一个 body 生成；异常类分别是 `AuthenticationError` 和 `RateLimitError`；`rag_food_code.py:163` 的判断只对 429 成立；文本里没有 key，也没有 `***`。
    2. **`redact()` 单元测试**（`:174`）：上面这些普通文字保持不变；完整 key、`***` 遮挡、`...` 遮挡和 `=` 后面的 `sk-` token 都被替换。不是 JSON 的响应按文本处理，没有回显的响应原样返回。
  - **修复前后对比**：
    - 在修复前的 `api_log.py` 上，24 个碰撞子测试有 21 个不通过：18 个断言失败，`null` 的 3 个 401 在 `e.response.json()` 处抛 JSONDecodeError。唯一通过的是后四位为 `rate` 的 401，因为它的 type 和 code 里没有 `rate`。`redact()` 单元测试也失败。
    - R-A3-1 的四项测试在修复后照常通过：普通 key 下，key 的首尾片段仍不出现在任何输出里。
    - 已在 CHECKLIST.md A3 登记。
- **端到端探针**：用临时脚本做，不提交；合成 key，并禁止 socket 连接。四个 key 都走了真实的 `process_image_url`。
  - 401 时，结果 CSV 写的是 `Error code: 401 - {...'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}}`，没有 key，也没有 `***`。日志文件同样干净。调用日志里的错误码为 `invalid_api_key` 和 `rate_limit_exceeded`。
  - 429 时，原代码确实进了限流重试分支，但随即在 `rag_food_code.py:165` 的 `min(2 ** attempts * 30)` 处抛 TypeError。结果 CSV 里写成 `'int' object is not iterable`，没有重试，原来的限流错误也丢了。这是复审指出的原代码问题，已按要求登记到 CHECKLIST.md C9，现在不改。
- **已知边界**：key 极短时（例如只有几个字符），替换完整 key 会把自由文本里相同的字符串一起换掉。这只影响 message 这类文字，不影响 `type`、`code`、`param` 和 JSON 结构。正常的 OpenAI key 有几十到一百多个字符，不会碰撞。
- **测试**：27 项离线测试全部通过，约 6.5 秒。`425a869` 在临时 worktree 里单独检出也能通过。没有付费调用，没有下载，仓库里没有留下日志或 CSV。新提交的说明和 diff 里没有长 `sk-` 串。
- **状态**：按 `823d2b3` 的新流程不再复审。CHECKLIST.md 里 A2 记为 `approved`，A3 记为 `fixed`，R-A3-2 的修复（`425a869`）归入审查节点一。

## 审查节点一：R-A3-2 修复、B–D、E1（`425a869`，`git log acd1bf5..HEAD`）

### 待审查（实现 agent 写）

**范围**：R-A3-2 的修复 `425a869`；B1–D8 和 E1 的全部提交（`git log acd1bf5..HEAD`，其中 `9efea0d` 是登记批准和样本量的流程提交）；E1 的输出 `runs/dev/`。偏差和冲突都登记在 CHECKLIST.md 对应条目的"登记"里，这里不重复。

**条目与提交**

| 条目 | 提交 | 改了什么 | 测试 |
|---|---|---|---|
| B1 | `11c5686` | FNDDS 描述表 5,624 行 | `tests/test_data.py` TestB1 |
| B2 | `9217490` | FoodWeights.csv（详细库，22,710 行） | TestB2 |
| B3 | `0b50dd6` | `asa_proc.py` 两处修复，前 1000 个编码占 81.36% | TestB3 |
| B4 | `0922851` | 新 `asa24_proc.py`：份量序列、50×3 测试集、10 张开发集 | TestB4 |
| B5 | `f019225` | `nutrition5k_proc.py` 四处修复，抽样 150+10，下载 160 张 | TestB5 |
| B6 | `c0c54f5` | 256×256 PNG data URL | `tests/test_images.py` |
| C1 | `b80cd1a`、`30f820b` | 索引持久化、分批；修好被 C1 弄坏的脱敏测试 | `tests/test_pipeline.py` TestC1 |
| C2 | `6b2bcb8` | 描述步骤用 data URL | TestC2 |
| C3 | `6bcf489` | 检索器只收描述，记录候选 | TestC3 |
| C4 | `75c6d96` | 选码用视觉模型、带图 | TestC4、TestPublishedPrompts |
| C5 | `7607252` | 份量两问照原代码；带分数；路径参数 | TestC5 |
| C6 | `60fde37` | 份量 → 编码 → 克重（× Multiplier）；amount 口径 | TestC6 |
| C7 | `76b9c06` | 营养表和公式核对 | TestC7 |
| C8 | `8a20fba` | Nutrition5k 选码格式、克重提示词（重建）、mix 修复 | TestC8 |
| C9 | `6a77081` | 退避 TypeError、尝试次数、并发、SDK 重试 6 次 | TestC9 |
| D1 | `7092ec4` | FoodCodeCommon | `tests/test_evaluation.py` TestD1 |
| D2–D7 | `b7fc478`、`4fff760`、`37858c1`、`32503e7`、`4aefff1`、`ef5c6cf` | 新 `evaluate.py` | TestD2–TestD7 |
| D8 | `8f81d2e` | 离线全流程防泄漏 | `tests/test_leakage.py` |
| E1 | `b685cbe` 和本节所在的提交 | `run_experiment.py`；开发集运行结果 `runs/dev/` | 见下 |

**E1 结果：管线跑通，但 gpt-4o 用发布的提示词大量拒答，E2 之前需要用户决定**（详细数字见 CHECKLIST.md E1 的"结果""诊断"）
- 开发集 10 张 ASA24、10 道 Nutrition5k，代码 `8f81d2e`，173 次请求、$0.144，全部 200，实际服务的模型是 gpt-4o-2024-08-06 和 text-embedding-3-large。
- ASA24 编码成功率 1/10，9 张的描述步骤 5 轮都回答 "I can't help to analyze this image."（"too small""can't identify"）；没有 FoodCodeCommon，所以论文协议的份量步骤没有请求，唯一一张的端到端份量也被拒。Nutrition5k 编码成功率 6/10，克重请求 6/6 被拒。没有一张图得到营养估计，所有 MAE 的 n = 0。
- 诊断（开发集 3 张图，17 次请求、$0.020，`runs/dev/diagnostics/`）：换原尺寸、白底、512、`detail: high` 都仍然拒答；只去掉提示词最后一句"If you can't provide assistance with this image, simply respond with 'I can't help to analyze this image.' and provide the reason on a new line."，三张都描述正确。所以是 gpt-4o 对这条"拒答出路"的反应，与图片传输、缩放无关。论文的 GPT-4 Turbo 用同样的提示词在 ASA24 上成功率 84–93%。描述、shot、amount 和重建的克重提示词都有这句。
- 我没有改提示词：这不在已有批准范围内。三个选择：(a) 保持原样跑 E2，如实报告极低的成功率；(b) 登记为模型替换造成的偏差，只删掉这一句，在开发集上重跑 E1 确认后再跑 E2；(c) 换模型（A3 记录其他可用模型不接受 temperature 0）。另外 Nutrition5k 选码回答里的免责声明会被当成食物名，若选 (b)，建议同时只保留带 8 位编码的条目（解析规则，不改提示词）。
- 费用：实际每张 ASA24 $0.0061、每道 Nutrition5k $0.0083（拒答后后续步骤不发请求，偏低）。按此估计 E2（150 + 150）约 $2.2；若选 (b)，每张图会走完全部步骤，按 E1 的 token 量估约 $0.011–0.012/张，E2 约 $3.5，另加重跑 E1 约 $0.3。目前已花 $0.281（建索引 $0.117、E1 $0.144、诊断 $0.020），上限 $20。

**跑过的测试**
- `.venv/bin/python -m unittest discover -s tests`：87 项全部通过，约 12 秒。全部离线：接口用 mock，`.env` 用临时文件，不发真实请求（但没有像第 1 轮审查那样拦截 socket）。数据测试（TestB1–B5）在相应的表缺失时跳过，本机上全部实际运行。
- `tests/test_leakage.py`（D8）在离线小世界里用 `run_experiment.run` 跑完整条管线并检查每个请求，也是 E1 之前对整条管线的冒烟测试。
- 密钥检查：用 `config.load_api_key()` 读出 key，只输出真假，确认 `runs/`、`logs/`、`samples/`、`code/`、`tests/` 和文档里没有 key 或其首 12 位、末 8 位片段，`acd1bf5..HEAD` 的提交说明和 diff 里也没有。
- 下载：Nutrition5k 俯拍图 160 张、64 MB，tiktoken cl100k_base 1.7 MB，都在批准范围内。HEAD 请求约 2,400 次（不下载内容）。

**需要特别看的地方**
1. **B4 的抽样框**（不推断份量编码）：ASA24 元数据的 PortionCode 只有约 40% 能在 FNDDS 2019–2020 里精确找到。找不到的图不进入该编码的份量序列，合格编码 284 个（前 1000 个中有 ASA24 图的 650 个、在 FNDDS 2019–2020 里的 543 个）。这样做的代价是份量序列比 ASA24 原有的短（选项更少），换来的是不用任何推断规则、参考克重全部可查；更严的规则（整条序列都要能查到）会把饮料比例推到 30%，所以没有采用。测试集 150 行只有 117 张不同的图（一张通用的液体图可以关联多个编码）。
2. **B5 偏离原代码的地方**：原代码 `on_bad_lines='skip'` 静默丢掉 423 道菜，`filter_unavailable_images` 的索引错位和缺失的 URL 前缀会让它取错菜或报错，模块顶层读一个不存在且不用的文件。缺失标签按"四项营养全为 0、重量大于 0"排除 129 道。协调会话说从 `dish_ids_splits_rgb_*.txt` 抽，我按原代码用两个餐厅的元数据：这两个文件正好是 Cafe 1 的全部编号，而 Cafe 2 有图的 128 道菜全部缺标签，所以两种做法的抽样框相同（Cafe 1 的 1,906 道）。
3. **D1/D2/D3 的口径**（第 1 轮审查要求给依据）：D1 登记了原代码的数据流和论文原文。条件口径（D2）下营养密度和份量序列都来自真实编码，只测份量；端到端口径（D3）完全不用参考标签，是我们补充的。两种都报。
4. **C6 的两种克重口径**：option（选中的份量 × Multiplier × 单位克重，原代码数据流，主口径）和 amount（数量 × 单位克重，对应论文第 252–253 行的另一种读法）。原代码 `nutrient_estimate.py` 没有乘 Multiplier，也没有份量描述到编码的映射。Supplementary Fig. 3 的"不合适时调整"在原代码里没有判断，所以 amount 没有当作替补。
5. **提示词的改动只有三处**（E1 之后没有再改）：C4 把 `{url_str}` 文本换成随消息发送的图片；C8 给 Nutrition5k 选码换了一句输出格式；C8 的克重提示词按 Supplementary Fig. 5 的模板重建。`TestPublishedPrompts` 与首个提交逐字对照其余提示词。没有在测试集上试过任何提示词。
6. **C9 改了 A3 的客户端**：`api_log.MAX_RETRIES = 6`（SDK 默认 2），为并发时把 429 重发而不是记成失败。重发不改请求，每个响应都记日志。
7. **B6 的缩放**：直接拉伸到 256×256（不保持长宽比），双三次；ASA24 保留透明背景，颜色和 alpha 分开缩放，避免透明处变黑。论文没写缩放方式。
8. **C1 的额外花费**：第一次建索引一次加入 5,624 条被 Chroma 拒绝（上限 5,461），原代码的重试每次都重新 embedding，三次失败多用约 676K tokens（约 $0.09）。同一提交还弄坏了 `test_redaction` 的索引日志测试（我当时只跑了 test_pipeline），在 `30f820b` 修好；那次测试运行在仓库外建了一个空的 Chroma 目录，已删除。
9. **还没做的**：E2–E4。E2 要等审查意见处理完和上面的用户决定；E5 按用户决定不做。

审查范围：`425a869` 加 `git log acd1bf5..HEAD`。各条目状态已改为 ready for review（B1–D8、E1），A3 为 fixed。

### 结论（审查 agent 写）

审查日期：2026-10-27。实际审查 HEAD 为 `d4c1bf2`，范围为 `425a869`、`acd1bf5..d4c1bf2` 的提交说明与 diff，以及 `runs/dev/`。原代码基准是首个提交 `5946365`；论文依据均指 CHECKLIST.md 指定的 `paper.txt`，补充材料另注明图号。未阅读实现对话，未调用真实 API，未下载数据，只修改本文件，没有提交。

**总体：changes requested。共 5 项 P1、3 项 P2，均应在 E2 前处理；本节点按流程只审一次，处理后由协调会话离线确认，不要求复审。** 优先级用于标记待修改问题；下表 approved 条目没有待改优先级。批准某条的定义或局部实现，不代表依赖它的上游缺陷已经解除。

**核验通过的部分**

| 编号 | 结论 | 证据与论文依据 |
|---|---|---|
| R-A3-3 | approved | `425a869` 对 R-A3-2 的修复成立：`code/api_log.py:21-84` 按结构处理错误响应，保留 type/code/param 和 JSON；`tests/test_redaction.py:141-191` 的碰撞与遮挡回显测试通过，原输出路径测试也通过。模型与温度未因修复改变，符合已登记的模型替代及 paper.txt:155-157、303-306。脱敏本身的直接要求来自 CHECKLIST.md 原则 5，论文没有规定密钥处理；本轮材料扫描也未见凭据，范围见下文。 |
| R-B1-1 | approved | `code/place_inputs.py:15-22,54-71` 核验本地输入哈希，`code/fndds_proc.py:8-47` 与首个提交相同；实际描述表 5,624 行、编码唯一，TestB1 通过。对应 paper.txt:130-134、153-160。 |
| R-B2-1 | approved | `code/fndds_weights_proc.py:11-27` 从详细库恢复份量编码，TestB2 逐行核对 At A Glance 的 22,710 行、描述、重量及唯一性并通过。论文“over 23,000”（paper.txt:132-134）与该版本实数不一致，CHECKLIST.md:113-118 已登记；Subcode=0 适用于此表的唯一键，没有擅自推断旧编码。 |
| R-B3-1 | approved | `code/asa_proc.py:15-38,59-66` 的两处修复只解除输入/输出路径和列名错误，频率统计沿用原代码。TestB3 从四期 XPT 重算通过，前 1000 个编码覆盖约 81.36%，对应 paper.txt:227-232。 |
| R-B4-1 | approved | `code/asa24_proc.py:27-110` 明确限定可查克重的抽样框、固定种子、按不同克重取大中小；当前 150 行/50 编码、117 个文件名，开发集 10 行，与测试集编码、文件名均不重叠，另查解码后的 RGBA 像素也无跨集重复。TestB4 通过。相对 paper.txt:230-232 的完整 1000 编码抽样，284 编码筛选框、缩短序列、共享图片和中位数规则均已在 CHECKLIST.md:141-150 登记，不能把小样本称为论文原样本。98 号份量的下游问题归 R-C6-1。 |
| R-B5-1 | approved | `code/nutrition5k_proc.py:27-33,70-106,131-156` 保留原代码按食材列表去重且取最大质量的逻辑，读全 CSV、修复索引和 URL、排除全零营养标签后固定抽样。TestB5 核对全部行、抽样和 160 张图的哈希通过。符合 paper.txt:235-237 的去重后随机抽样；使用两个餐厅、缺失标签筛选和 150+10 的范围已登记于 CHECKLIST.md:162-172。没有因为开发集推理表现再换样本。 |
| R-B6-1 | approved | `code/chagApp_openai.py:20-42`、`code/rag_food_code.py:98-115,159-163` 和图片测试核对本轮管线实际发送本地图片的 256×256 PNG data URL。拉伸、双三次和透明背景处理是已登记的未指定实现细节，对应 paper.txt:237-240。URL 直接透传的辅助分支不保证缩放，但本轮和已准备的 E2 输入均为本地文件。 |
| R-C1-1 | approved | `code/rag_food_code.py:67-95` 持久化、按缺失 id 补齐并分批；三项 TestC1 通过。本轮另用 SQLite 只读连接核查实际索引：openai_embed、3072 维、5,624 条，按行 id 保存的文档文本与当前 CSV 全部一致。符合 paper.txt:155-160 的一次建索引；首次失败的额外 embedding 已进入总账并登记，没有隐去费用。 |
| R-C2-1 | approved | `code/rag_food_code.py:98-115,201-234` 使用正确的图片消息结构及本地文件检查，描述提示文字与首个提交一致；TestC2、TestPublishedPrompts 通过。对应 paper.txt:162-164 和 Supplementary Fig. 4。 |
| R-C3-1 | approved | `code/rag_food_code.py:117-138,165-175,250-252` 只把描述交给 MultiQueryRetriever，各查询检索后合并去重，候选编码留档。TestC3 使用真实检索器和假模型核对通过；修复把输入 dict/base64 当查询的问题符合 paper.txt:162-171、Supplementary Fig. 2。 |
| R-C4-1 | approved | `code/rag_food_code.py:148-182` 选码请求含图、全部检索上下文并使用视觉模型；TestC4 验证 temperature=0 和无描述步骤的 200-token 上限。把原代码的 URL 文本/文字模型改为视觉输入，已按 paper.txt:173-178 和 Supplementary Fig. 5 登记冲突，未偷偷加入标签。 |
| R-C5-1 | approved | `code/rag_portion_size.py:36-51,78-123,155-190` 的两种 ASA24 提问与首个提交文字相同，带分数处理正确，份量选项与真实单位仅在 FoodCodeCommon 非空时进入条件流程。TestC5、D8 通过；对应 paper.txt:179-186、415-425 和 Supplementary Fig. 5。这里批准的是已明确登记的标签条件实现，不据此断言论文本身证明了该筛选口径。 |
| R-C7-1 | approved | `code/nutrient_estimate.py:16-38` 的表头、65 项营养和每 100 g × 克重 / 100 公式正确，核心计算沿用原代码；TestC7 用真实表手算牛奶通过。对应 paper.txt:151-171 右栏及 187-189。 |
| R-D1-1 | approved | `code/rag_portion_size.py:27-51` 实现预测编码与真实编码的交集，并仅由共同编码补描述。首个提交的 process_dataframe/nutrient_estimate 确实依赖 FoodCodeCommon；但 paper.txt:385-388 只直接限定 Table 3，:415-425 说明份量评测，均不能单独证明 Table 1 只测识别完全正确者。CHECKLIST.md:304-307 已明确这一证据边界，并另报 D3，因此接受为原代码数据流下的条件口径，不能把它当作无标签端到端复现。 |
| R-D2-1 | approved | `code/evaluate.py:30-67` 的条件 MAE、同一有效子集参考均值作 per-unit 分母、按档与合计计算正确，TestD2 手算通过；对应 paper.txt:249-255、Table 1 注释 :324-325。option/amount 的差异已登记，两者必须保留各自 n，不能合并解释。上游克重和解析缺陷见 R-C6-1、R-C6-2。 |
| R-D3-1 | approved | `code/rag_portion_size.py:195-233` 从预测编码的 FNDDS 表构造选项与单位，`code/nutrient_estimate.py:106-115` 和 `code/evaluate.py:177-189` 使用预测编码算克重、营养及覆盖率。TestD3、D8 核对请求不带参考标签通过；这是项目补充的端到端口径，符合 paper.txt:173-186 的预测数据流，已与 D2 分开登记。数字解析仍须按 R-C6-2 修复。 |
| R-D4-1 | approved | `code/evaluate.py:70-103` 实现 Exact/前两位/首位，分别报告 any 与 first；TestD4 通过。累计 Close、Far 的解释与 paper.txt:200-211、Table 3 的数值结构相容，多码歧义已登记，不把最优匹配悄悄说成唯一预测。 |
| R-D5-1 | approved | `code/evaluate.py:106-124` 报份量分类、单位误差及两种克数误差和各自 n，TestD5 手算通过。Methods 写 grams（paper.txt:218-220），Table 5 文本写 units（:423-425、443-448）的冲突已登记于 CHECKLIST.md:339-340，没有擅自把两种单位混为一个指标。 |
| R-D6-1 | approved | `code/evaluate.py:131-164` 的分母、option 可换算率、amount 数值响应率和 Nutrition5k 按菜/食物项计算均有明确字段，TestD6 通过；对应 paper.txt:224-228 右栏、546-550、506-515 和 Supplementary Table 2。这里的份量率以已识别/被提问者为分母，不能解释为全部输入的端到端成功率；Nutrition5k 的“完整”只针对模型识别的食物列表，不保证覆盖真实全部食材。解析丢项会破坏这一前提，须处理 R-C8-1、R-C6-2。 |
| R-D8-1 | approved | `tests/test_leakage.py:150-243` 的完整离线请求检查通过，结合 `code/rag_food_code.py:207-262`、`code/rag_portion_size.py:195-251` 的数据流检查，未发现已登记 C5/D1 条件之外的参考标签进入推理。两套输入虽保存标签列，模型请求并未直接格式化整行。当前没有正式测试集推理结果；诊断文件名均属于开发集。依据 CHECKLIST.md 原则 3、4；论文预测数据流见 paper.txt:162-189。该结论限于可见代码、mock 请求和留存材料，不把它说成真实 API 请求内容的逐条留存审计。 |

**必须修改的问题**

- **R-C6-1 [changes requested]（P1）：98 号克重份量在数据准备与预测换算之间不一致，正确答案会丢失。** `code/asa24_proc.py:24,50-54` 明确把 ASA24 PortionCode=98 解释为 1 克，允许该类图片进入序列；但 `code/nutrient_estimate.py:22-28,89-96` 映射出 98 后再次查 FoodWeights，而该表没有任何 Portion Code=98，结果恒为 NaN。只读核对：当前份量序列有 52 行/9 个编码使用 98；正式抽样有 2 个编码的候选序列涉及它，4 行参考标签也使用它。例如食物 `24123120` 的 `6 pieces`，参考为 270 g，模型选完全相同文字时 map_portion 返回 `(98, 0, 270)`，现有换算却得到 NaN。会降低 D6 成功率，并从 D2/D5 的 MAE 子集中删掉本来成功的图片。请在预测换算中统一应用 B4 已登记的 98 语义，或使用经验证的选中选项克重；不得退回读取当前图片的真实 PortionCode/Multiplier。补上正确选择该选项得到 270 g、营养和评测 n 的离线回归。依据：paper.txt:179-186、249-255 要求所选份量正确映射为克重，CHECKLIST.md:144、247-249 要求参考与预测的编码语义一致。

- **R-C8-1 [changes requested]（P1）：食物列表被不同解析规则拆坏，丢项后仍可能被当成“完整的菜”。** `code/rag_portion_size.py:235-240` 对所有带冒号的片段取名称，不要求该片段有编码；`code/nutrient_estimate_mix.py:37-69` 却要求严格的 `': '`、`'; '`，解析失败只 print，不留下该食物的错误计数。真实 E1 已出现：`runs/dev/nutrition5k_food_codes.csv:2-3` 的免责声明变成 GPTFoodNames，食物描述自身的分号又把完整鸡肉菜名切成“no sauce”等片段（`runs/dev/nutrition5k_portion.csv:2-3`，`runs/dev/console.out:6-11`）。更小的离线反例：编码回答 `rice: 11111111; chicken:22222222`，重量回答 `rice: 100\nchicken: 100`，两个编码均在合成营养表中；当前结果却是 IngredientNum=1、WeightError=0、FoodCodeError=0、GPTWeight=100，D6 两种份量率均为 1，D7 complete 的 n=1。请让提问、计数和营养使用同一份经验证的食物/编码结构，保留食物名中的分号等标点，排除无编码免责声明，并对无法解析的真实条目保留失败状态，不能缩小食物项分母后判完整。只保留含编码的分号片段还不足以恢复被切断的完整名称。补上这两个真实 E1 答案及缺冒号空格的回归，不需付费验证。依据：paper.txt:161-171 右栏、173-189 要求对识别的全部食物求和；:512-514 的成功率针对所有检测项；CHECKLIST.md:275-281、350-357 禁止漏项被算作完整。此问题与用户是否删提示词无关，三个选择下都必须处理。

- **R-C6-2 [changes requested]（P1，同时影响 C8、D3、D5–D7）：数字解析会把无效数值或拒答文字变成有效估计。** `code/nutrient_estimate.py:52-60` 和 `code/nutrient_estimate_mix.py:23-29` 只搜索第一个无符号数字。离线直接得到：ASA24 `parse_portion_amount('-2') == 2`、`parse_portion_amount('1,000') == 1`，`I cannot determine whether there are 2 cups from this image.` 也得到 2；Nutrition5k 的 `rice: -20` 变成 20 g，`rice: 1,000` 变成 1 g，且均可进入 complete，成功率为 1。原代码克重解析的缺陷虽部分沿用，但 C8 已修改此解析，C6 是新增解析，不能继续把这些结果称为有效数值。请按约定的数值/单位格式验证答案，负值和无法明确解释的拒答记失败，千分位应正确解析或明确拒绝，不能截断成另一个值；允许的小数、分数和带分数仍应正确。为上述样例及无穷/非数等无效量补回归，检查失败传播到成功率和 MAE。依据：paper.txt:179-186、249-255 的实际份量换算，:224-228 的有效响应口径，以及 CHECKLIST.md:351 的失败不能算成功要求。

- **R-C9-1 [changes requested]（P1）：ASA24 的续轮跳过条件与评测对“有编码”的定义不一致。** `code/rag_food_code.py:192-199,307-310` 仍按字符串第 3–10 个字符能否转整数决定跳过；`code/rag_portion_size.py:30-34`、`code/evaluate.py:92-96,138` 则抽取完整 8 位码。离线反例：`['Food code: 63101000']` 被 D1/D4/D6 接受，却不会被 C9 跳过，会重复提问并可能被后来的失败覆盖；`['631010001']` 没有合法 8 位码，反而被跳过，不再使用剩余重试机会。前一种格式还是 `tests/test_evaluation.py:37` 明确支持的格式。另用真实 process_image_urls 加假视觉模型/选码链复现：第一次回答该有效前缀格式，后四次抛合成异常，最终 GPTAttempts=5、GPTFoodCode 为空，原成功确已被覆盖。请统一两处完整 8 位码的解析定义，保留已批准的最多五轮重试、原有请求与提示词；补测有效带前缀回答不重问、9 位数字仍失败并继续重试、已有成功不被后续失败覆盖。该判断继承自原代码，但与 CHECKLIST.md:287,291 的“每轮跳过已有编码、失败最多五轮”相冲突，修正应登记为解析错误修复。论文只规定每张图独立处理及模型设置（paper.txt:303-306），不规定此字符串切片；评价编码的依据是 :200-211。

- **R-D7-1 [changes requested]（P1）：全部食物克重失败仍会得到 0 克，并进入“有估计的菜”的 MAE。** `code/nutrient_estimate_mix.py:75-88,102,129-142` 把 weight_total 初始化为 0，即使没有一个食物成功提供克重，也照样写入 GPTWeight；`code/evaluate.py:171-174` 用非空判断纳入 any_estimate。离线反例：`GPTFoodCode='rice: 11111111'`、`GPTAmount='rice: none'`，得到 IngredientNum=1、WeightError=1、GPTWeight=0；参考 200 g 时 any_estimate 报 n=1、MAE=200 g、per_unit=1，而该菜根本没有重量估计。格式完全无法解析的编码也能产生同类 0。请只有至少一个有效重量贡献时才写部分重量；全部失败保持 NaN，显式预测的数值 0 与“没有预测”的初始 0 分开。补测全部 none、空/畸形回答、部分有效三种情况，防止失败进入任一 MAE 子集。原代码的零初始化不能覆盖本项目新增 D7 对估计是否存在的要求。依据：paper.txt:249-255、Table 2 注释 :348-349，CHECKLIST.md:351、357 的失败与部分估计区分。

- **R-E1-1 [changes requested]（P2）：续跑覆盖此前费用和模型来源，中断时也没有完整的运行归属记录。** `code/run_experiment.py:74-85` 每次调用重新取 first_line，`:111-128` 仅汇总本次调用新增的记录，却覆盖同一目录的 cost.json/config.json，运行 JSONL 另用追加。用 D8 的小世界及 MockTransport 连续执行两次同目录运行，首次费用 $0.01085975；第二次无新请求后 cost.json 变为 $0、models_served 变为空列表，而保存的运行 JSONL 仍有 56 行和首次费用。此外本次日志只在全流程完成后才复制，若中途异常，已付费请求仅留在全局总账，不能从运行目录恢复步骤归属；代码/提示词变化后同目录的旧拒答/检查点还会直接复用。请保存每次调用的开始配置及运行/步骤日志归属，续跑累计完整运行费用、保留各段代码与模型来源，失败退出也留存记录；不兼容配置应拒绝复用或使用新目录。若用户选删句重跑 E1，应保留本次失败基线，使用新的实验目录，不能把现有开发集目录直接当作新配置运行。补测无新请求续跑、有新增请求续跑和中途异常的总账一致性。依据：CHECKLIST.md 原则 5、E1:378-380，paper.txt:303-306 的可复现设置及 :518-527 的实际 API 费用口径；本问题不否定当前单次 E1 的费用重算结果。

- **R-E1-2 [changes requested]（P2）：按 CSV 物理行数计算图片数，会被合法的多行描述污染。** `code/run_experiment.py:117-120,124` 用文件行数减一作为图片数及单图费用分母，但 GPTFoodDescription 可包含换行，CSV 会合法地把一个记录写成多行。对 D8 的两张 ASA24 表只把一条描述改成 `milk\nwith a glass`，再次离线运行后 config.images.asa24 从 2 变成 3，实际评测仍只有两张。请使用 CSV 解析后的记录数，且与输入/输出样本数核对；补测描述和回答字段带换行时 n、config 图片数和单图费用不变。依据：paper.txt:518-526 明确用 evaluated images 作费用分母，CHECKLIST.md:376、379-380 要求记录实际样本数和费用。当前留存 E1 的 10+10 计数恰好正确，但这个驱动缺陷会影响后续合法输出。

- **R-E1-3 [changes requested]（P2）：诊断记录不支持文档中部分事实和过强的因果结论。** CHECKLIST.md:385 写“每次请求的 prompt tokens 都是 390”，但 `runs/dev/diagnostics/answers.jsonl:10` 的 Nutrition5k 原尺寸请求是 560；`:6-7` 也表明换白底/原尺寸曾改变冰淇淋样例的回答（原尺寸答成土豆泥，并非识别正确）。更关键的是，删句实验的 `runs/dev/diagnostics/no_refusal_sentence.py:13-19` 只调用描述步骤，三张删句回答在 `runs/dev/diagnostics/answers.jsonl:12,14,16`；没有删句后的选码、shot、amount、grams 或营养输出。CHECKLIST.md:387 用确定语气归因并排除图像因素，现有证据只支持上述三图的描述诊断，不能外推到全部后续步骤。请纠正 token 数，限定为“这三张开发图上，删除拒答句改善了描述响应；份量/克重收益尚未验证”，区分响应产生与识别准确。当前 E1 是有价值的失败基线，但 ASA24 条件份量没有真实请求，不能称为全部分支已有付费实测验收。修正文档不要求新调用；用户若选 (b)，再在开发集验证下游，不能直接假定它能产出 MAE。依据：paper.txt:173-189 的多个独立推理步骤、:303-306 的实验记录要求及 CHECKLIST.md 原则 4、E1 的整管线检查目标。

**离线验证和审查边界**

- 在执行 `unittest` 前拦截 `socket.socket.connect`、`connect_ex`、`socket.create_connection`，运行 `.venv/bin/python -B` 的 `unittest` discover：**87 项通过，0 失败、0 错误、0 跳过，约 10.94 秒，网络连接尝试 0 次**。另跑上列临时离线反例、D8 mock 世界的续跑与多行 CSV 探针；没有把这些探针写进仓库测试，也没有修改现有结果。现有 87 项未覆盖所列缺陷，不能单凭全绿放行 E2。
- 独立调用纯评测函数重算 `runs/dev/metrics.json`，与留存文件完全一致；按仓库单价重算开发集 173 条响应为 **$0.14413438**，全局 215 条为 **$0.28118526**，全部状态 200，开发集 chat temperature 均为 0。ASA24 代码成功率 1/10、Nutrition5k 6/10，所有营养估计仍为空，与报告的 MAE n=0 一致。这里确认算术和已存数据，不把 HTTP 200 等同任务成功，也未重新验证服务端可用模型、即时价格或账单金额。
- 检查全部 71 个当前受审文本文件（含日志、结果、代码、测试和文档）、`git log -p acd1bf5..d4c1bf2` 与 `git show 425a869` 的提交说明及 diff：没有当前 `.env` key 的完整值、首 12 位或末 8 位，也没有 `sk-` 加 24 位以上凭据字符的候选。`.env` 仍被忽略。扫描未输出密钥；此结论限于本轮材料和这些匹配规则，不声称检查了任意外部文件或全部历史凭据格式。
- 原代码与论文的冲突登记基本充分：A3/A4 模型与温度、B4 抽样框、B6 缩放、C4 视觉选码、C6 两种克重、C8 重建提示词、D1/D2 条件筛选与 D5 单位差异均可追踪。现有样本划分和诊断材料未见在正式测试集上试提示词、调参或执行 E2 的证据；本次读取冻结测试清单只用于静态协议/换算校验，不是按测试表现选择方案。E2 仍须等上述 P1/P2 处理及用户的提示词决定。

**关于 E2 前三个提示词选择的意见（供用户决定，不代为决定）**

(a) 保留发布代码的提示词，最符合 CHECKLIST.md 原则 1 对“已有代码照原代码”的要求，适合回答“替换模型后原发布实现还能否工作”；目前证据预示有效 MAE 样本可能很少或为零，应允许如实报告失败，而不能因 E2 不好看再调参或重跑。它仍有已登记的模型替代，不能称为原论文模型的严格复现。(b) 只删除拒答那一句，是比换整个模型更小、也更容易归因的开发集适配：首个提交的 `rag_food_code.get_messages_from_url` 与 `rag_portion_size.create_prompt` 确实有这句，但 **Supplementary Figs. 4–5（MOESM2 第 3 页）的示例模板并没有这句**；paper.txt:125-127、179-186 也没有要求加入它。因此删句有论文模板层面的支持，但按原则 1 仍是对发布代码的有意偏离，须登记为模型替代背景下的提示词适配，保存原 E1，只在开发集验证描述、份量、克重和失败率后冻结配置，不能预言三张描述探针能解决所有拒答。若项目目标优先是获得可解释的小样本 MAE，这一选择更值得先验证；修解析错误是另一个独立事项，不应混入“只改一句”的提示词声明。(c) 换模型符合论文讨论中承认模型行为变化及可迁移的设计（paper.txt:559-565），但会增加一个模型变量，需重做兼容性、费用和开发集验证；A3 已登记的几种替代探测还存在 temperature=0 不被接受的问题，这些记录本轮没有重新付费确认，也不能推广成所有模型都如此。三种选择都必须在 E2 前由用户固定，之后遵守原则 4 与“一次正式运行”，不能利用正式测试表现再挑提示词或模型。

### 处理（实现 agent 写）

按 AGENTS.md 流程第 4 条处理，不再复审。CHECKLIST.md 里，结论 approved 的条目记为 approved（A3 按 R-A3-3 一并记为 approved）；C6、C8、C9、D7、E1 改完记为 fixed。每项修复的新测试都在修复前的代码上跑过，确认会失败（用 `git archive` 取修复前的代码，配上新测试）。

- **R-C6-1 → `fe3617e`**：`get_portion_weight` 对份量编码 98 按 1 克计，与 B4 的参考克重一致。测试：24123120 选 "6 pieces" 得 270 g，营养正确，n = 1；对真实份量序列的每一行，选中后算出的克重都等于参考克重。
- **R-C6-2 → `0c1d2b4`**：`parse_portion_amount` 只接受一个非负数，后面可以跟单位，支持小数、分数、带分数和千分位。负数、数字前有文字、有第二个数、千分位格式不对、无穷大和拒答都记为失败。C8 的克数用同一个解析，单位只能是 g。测试覆盖审查给的样例，以及它们在 D5、D6 成功率和 D2、D3、D7 MAE 子集里的结果。
- **R-C8-1 → `d05733a`**：
  - 新增 `rag_portion_size.food_items`，把 "food: code, code; food: code" 只解析一次。克重提问、IngredientNum/WeightError/FoodCodeError、营养、D6 的"有编码"和续轮跳过都用它的结果。
  - 解析规则：冒号结束食物名，名字里自带的分号保留；值是完整的编码列表，或到下一个分号为止的文字。没有 8 位码的食物仍算一种食物，计为失败。冒号后没有值的引导语和最后的尾句不算食物。克重回答按最后一个冒号切分。
  - 上一个实现会话留下的未提交版本有一处缺陷：最后一种食物有多个编码时，编码列表会退回到最后一个逗号之前。E1 选码表的 cauliflower 和 green beans 因此各丢了一个编码。已改正并补测。
  - 测试：E1 的四条真实回答；`rice: 11111111; chicken:22222222`，核对 D6 的两种份量成功率和 D7 complete 的 n；9 位数；名字里带冒号。
- **R-C9-1 → `258c829`**：ASA24 的续轮跳过条件改用 `parse_food_codes`，与 D1、D4、D6 的判断相同。测试：在真实的 `process_image_urls` 里，带前缀的有效回答处理一轮后保留，不再被覆盖；9 位数字进入下一轮。
- **R-D7-1 → `6a9cf98`**：`calculate_dish_nutrition` 的克重从空值开始，遇到第一种有克数的食物才开始累加。全部食物都失败的菜，GPTWeight 为空；明确回答的 0 g 仍算估计。测试经过 `process_results` 一直算到 D7 的两个子集，覆盖五种情况：全部 none、回答读不出、编码回答里解析不出食物、部分有效、0 g。
- **R-E1-2 → `10a83b4`**：图片数按 pandas 读出的记录数计算，并核对抽样表、选码表和营养表的行数，不一致就报错。测试写在新文件 `tests/test_run_experiment.py`，用 D8 的离线小世界：描述跨两行时，图片数、指标和每张图的费用都不变；表里多一行时报错。
- **R-E1-1 → `e8dd56a`**：
  - `config.json` 记下推理配置：数据划分、模型、temperature、图片尺寸，以及构造请求的五个代码文件和输入表的 sha256。配置不同，或者是旧驱动留下的目录（如 `runs/dev/`），都拒绝复用。
  - 每次调用记下开始时间、提交号、并发数、每一步在全局日志里的行号，以及结束状态或 `failed: <异常类型>`。
  - 每一步结束时（包括出错），把这一步的响应加上步骤名和调用序号，追加到运行目录。`cost.json` 和实际服务的模型按全部响应累计。
  - 测试：无新请求的续跑；步骤中途 Ctrl-C 后续跑，运行目录的账与全局日志一致；换模型、改输入表、旧驱动的目录、没有 config.json 的目录都被拒绝，目录内容不变。
- **R-E1-3 → `3bc1d13`**：按 `answers.jsonl` 改正了 CHECKLIST.md E1 的诊断记录：
  - Nutrition5k 原尺寸那次请求是 560 tokens；
  - 冰淇淋那张在白底下答对，原尺寸下答成土豆泥；
  - 删句后三张图都给出了描述，对照参考标签，一张对、一张部分对、一张错；
  - 结论只限于这三张图的描述步骤，下游各步留给重跑。

  上面"待审查"里的同类说法（"三张都描述正确""与图片传输、缩放无关"）以 CHECKLIST.md 为准。
- **删句（用户决定 (b)）→ `c881999`**：单独一个提交，不和解析修复混在一起。描述、shot、amount 三个提示词和重建的克重提示词，只删最后一句拒答出路及其前面的空白。TestPublishedPrompts 逐个核对：新提示词等于发布版本去掉这一句。登记在 CHECKLIST.md E1 的"提示词适配"里，C2、C5、C8 各加了一行指向它。
- **删句后的开发集重跑**（`runs/dev-no-refusal-sentence/`，代码 `8176379`）：423 次请求，$0.256。各步结果、MAE 和 n、E2 费用估算见 CHECKLIST.md E1。简要：描述和选码在两个数据集上都是 10/10；ASA24 端到端 9/10 有估计；ASA24 论文协议份量只有 1 张（Exact 1/10）；Nutrition5k 克重 8/10 换了说法拒答。E2 还没有跑。
- **克重提示词加句（用户 2026-10-27 决定）→ `3947390`**：只在 Nutrition5k 克重提示词末尾加 "If you cannot determine the exact weight, still give your best estimate in grams."，登记在 CHECKLIST.md C8 和 E4。
  - 开发集重跑的第一次随会话结束被终止，目录原样保留为 `runs/dev-grams-estimate-killed/`（`623cffd`）。
  - 第二次 `runs/dev-grams-estimate/`：问到克重的 7 道菜都给出了数字。份量成功率按菜 4/7、按食物项 9/14，剩下的失败来自解析和一个被拆开的食物名。Nutrition5k 选码这次是 7/10。详见 CHECKLIST.md E1。
  - E2 还没有跑。
- **测试**：`unshare -rn .venv/bin/python -m unittest discover -s tests`，在没有网络的命名空间里运行，101 项全部通过。仓库文件和 `511ff22..HEAD` 的提交里都没有 `sk-` 开头的长串。按协调会话的要求，我没有读 `.env`，完整 key 的比对由协调会话做。

## 审查节点二：E2、对照表、偏差清单和报告（`git log 8176379..HEAD`）

### 待审查（实现 agent 写）

**范围**：审查节点一处理之后的全部提交（`git log 8176379..HEAD`），包括：
- 用户决定的克重提示词加句，以及两处克重解析修复（C8）；
- 开发集重跑和离线重算（E1）；
- E2 的正式运行和输出 `runs/test/`；
- 对照表（E3）、偏差清单（E4）和实验报告 `REPORT.md`。

**条目与提交**

| 条目 | 提交 | 改了什么 | 测试 |
|---|---|---|---|
| E1 | `307599a` | 删句后的开发集重跑 `runs/dev-no-refusal-sentence/` | – |
| C8 | `3947390` | 克重提示词末尾加一句，要求给出估计值（用户决定） | TestC8 `test_grams_prompt` |
| E1 | `623cffd`、`053b9b6` | 加句后的开发集重跑：被终止的一次 `runs/dev-grams-estimate-killed/`，从头跑完的 `runs/dev-grams-estimate/` | – |
| C8 | `d9419aa` | 克重回答读全文，原代码只读第一段（用户决定） | TestC8 `test_estimates_after_a_disclaimer` |
| C8 | `1a7195f` | `food_items` 的 ";;" 缺陷，是我们自己的（用户决定按缺陷修） | TestC8 `test_empty_item_is_no_food` |
| E1 | `ea3c08b` | 用修好的解析离线重算 `runs/dev-grams-estimate/`：按菜 6/7、按食物项 13/14 | – |
| E2 | `54f218c` | 测试集正式运行一次 `runs/test/`；离线 bootstrap 区间 | – |
| E3 | `cf2c9a2` | REPORT.md 第 1–3 节，`code/report_tables.py`，离线失败分类 | `tests/test_run_experiment.py` TestE3Tables |
| E4 | `0f8af65` | REPORT.md 第 4 节，29 条偏差 | – |
| 报告 | 本节所在的提交 | REPORT.md 的概要、讨论与局限、复现材料 | – |

**E2 结果**（详见 REPORT.md 第 2、3 节）
- **运行**：一次调用跑完（2026-10-27 06:20–07:02 UTC），代码 `ea3c08b`，工作区无改动。
  - 8,867 次请求全部 200，与全局日志第 1673–10539 行逐条相同。实际服务的模型是 gpt-4o-2024-08-06 和 text-embedding-3-large。
  - 花费 $5.285，累计 $6.438，上限 $20。
- **ASA24**：选码 83.3%；论文协议 n = 21，重量 MAE 92.7 g（论文 49.4 g）、热量 93.0 kcal（论文 47.7 kcal）；端到端 74.7%，n = 112。
- **Nutrition5k**：
  - 选码 85.3%（论文 98.9%）；份量按菜 73.4%（论文 84.2%）、按食物项 83.3%（论文 80.5%）。
  - 完整的菜 n = 86，重量 MAE 95.0 g（论文 45.1 g）、热量 123 kcal（论文 68.2 kcal）。

**跑过的测试**
- `unshare -rn .venv/bin/python -m unittest discover -s tests`：104 项全部通过，在没有网络的命名空间里运行。
- 两处解析修复的新测试，都在修复前的代码上跑过，确认会失败：用 `git archive` 取修复前的代码，配上新测试。
- 离线重算和 E2 的诊断都在断网下运行，全局日志的行数不变。
- 密钥：我只扫了 `sk-` 长串，仓库文件里没有。我没有读 `.env`，完整 key 的比对请协调会话做。

**需要特别看的地方**
1. **测试集上没有调参**：
   - 提示词和解析的适配（偏差清单第 23–25 条）和 ";;" 的修复，都是在 E2 之前依据开发集记录由用户决定的。
   - E2 只运行一次。
   - E2 之后，`code/` 只新增了 `report_tables.py`（见 `git diff ea3c08b HEAD -- code/`），推理代码没变。
2. **适配的登记**：第 23–25 条改了发布的提示词和解析，所以结果不是论文流程的严格复现。请看 C8、E1 和偏差清单的登记是否足够。
3. **被终止的开发集运行**（`runs/dev-grams-estimate-killed/`）：
   - 进程被信号终止，`finally` 没有执行。因此 `config.json` 仍是 running，这一步的 278 个响应只在全局日志里。
   - 没有续跑：续跑会让 3 道菜多试一轮，超过 5 轮。
   - R-E1-1 的机制处理不了信号终止，所以 E2 改为在会话外运行。`run_experiment.py` 是否需要处理 SIGTERM，请给意见。
4. **E2 期间跑过一项离线测试**（TestE3Tables）：它的 API 和日志路径都指向临时目录，E2 的账与全局日志逐条一致。
5. **报告里的事后统计**：以下都是离线统计，用来说明误差来源和不确定性，不是论文的指标，也没有用来改任何东西：
   - 2.2 去掉两张饼干图后的 MAE，以及中位绝对误差；
   - 2.4 的 bootstrap 区间。
6. **失败分类**（2.2、2.3）：由 `runs/test/diagnostics/failures.py` 按回答文字和名字分类。"组合食物名被拆开"用的是简单规则（逗号、and、with），20 和 15 的划分是近似的；合计 38，与 WeightError 一致。
7. **空查询**（偏差清单第 28 条）：E2 的 300 张图都多出同样 4 个候选编码，和开发集重跑时的 4 个不同。照原代码，没有改。
8. **报告里不写操作系统、机器和运行环境**，已检查。复现材料只写了仓库里的脚本和命令。
9. **费用估算的偏差**：E2 估计 $4.9，实际 $5.285，因为 ASA24 选码的重试比开发集多。

审查范围：`git log 8176379..HEAD`。状态已改为 ready for review 的条目：
- C8：节点一之后的三处改动；
- E1：节点一之后的重跑和重算；
- E2、E3、E4。

### 结论（审查 agent 写）

审查日期：2026-10-27。审查基线为 `8176379`，被审查 HEAD 为 `0e383c3`，共 11 个提交；已读该范围的提交说明、代码与测试 diff、论文正文及 MOESM2 第 3–4 页，并与首个提交 `5946365` 对照。**本轮总评：changes requested。3 项 P2 必须处理，2 项 P3 建议；未发现 P1。** C8 的本轮改动、E1 重算、E2 的运行及主要点估计可以接受；E2 的附加区间、E3 的失败解释和 E4 清单需要补正。approved 项没有待修复问题，因此不另赋问题优先级。

**离线验证与范围**

- `unshare -rn .venv/bin/python -B -m unittest discover -s tests`：104 项通过（23.443 s）。所有实验重算也在断网命名空间中执行；未调用付费 API。
- 从 `runs/test/*_portion.csv` 重新计算两张营养表，输出到 `/tmp`，逐列与存档比较一致；再从营养表重算 `metrics.json`、`metrics.md`，均一致。`code/report_tables.py` 生成的 36 行表头/数据/分隔行均能在 REPORT.md 找到。`runs/test/diagnostics/bootstrap.py`、`failures.py` 的标准输出分别与存档 txt 完全一致；但脚本能复算不代表统计解释和分类没有问题，见下。
- 开发集的两张营养表与指标另行重算到 `/tmp`，与 `runs/dev-grams-estimate/diagnostics/recompute/` 一致。开发集和测试集的图片路径及文件内容 SHA256 均无交集；ASA24 测试集确为 150 行、50 个编码、117 张不同图片。
- 密钥仅在内存中比较，不输出值：将根目录 `.env` 中两个 key 值与本轮 11 个提交快照的 157 个不同 blob、提交说明和补丁比较，均未命中；另查长 `sk-` token、私钥头和 AWS access id，未命中。提交快照包含已跟踪的日志和结果。审查只改本节，不改代码、运行存档或其他文件，不提交。

- **R-C8-2 [approved]：本轮的加句、读全文与空项修复有开发集依据，且范围与登记相符。** `3947390` 只在克重提示末尾加要求估计的一句（`code/rag_portion_size.py:81-89`）；`d9419aa` 去掉第一段截断并跳过空行（`code/nutrient_estimate_mix.py:16-35`）；`1a7195f` 去掉下一食物名前的多余分号（`code/rag_portion_size.py:263-277`）。首个提交 `5946365:code/nutrient_estimate_mix.py:9` 确有第一段截断。CHECKLIST.md:283、291-296、437-475 登记了开发集来源、用户决定和重算；三处都早于 E2 的 `ea3c08b`。`tests/test_pipeline.py:663-675,740-758` 覆盖两个真实开发集回答，104 项测试含这些用例均通过。论文依据：paper.txt:173-189 要求按识别食物估份量、求和；MOESM2 第 3 页 Supplementary Fig. 5 提供数量模板，没有新增的 best-estimate 句。报告已将它们列为适配，不能称为严格复现，这个边界成立。

- **R-E1-4 [approved]：开发集重跑、终止记录和离线重算可核实。** 两处解析修复后的原始回答重算得到 Nutrition5k 按菜 6/7、按食物项 13/14、完整菜 n=5，与 CHECKLIST.md:468-475 和存档指标一致。被终止目录只保存 210 个响应，而全局第 639–1126 行共有 488 个响应、$0.28625895；缺少的正是第 849–1126 行的 278 个，`runs/dev-grams-estimate-killed/config.json:30-51` 的 running/null 状态与此相符。这次未被冒充完整运行，费用已计入全局累计；后续是另建目录从头运行。依据：CHECKLIST.md 原则 4、5；paper.txt:303-306 的运行可复现性和 :518-527 的实际 API 费用口径。

- **R-E2-1 [approved]：现有记录支持一次正式运行、配置冻结、无测试后调参；主要结果和账目正确。** `runs/test/config.json:29-78` 只有一次 completed 调用，提交 `ea3c08b`、无未提交改动。五个构造请求文件及六个输入表的 SHA256 均与当前文件相符，代码 SHA256 也与该提交相符；`git diff ea3c08b..0e383c3 -- code/` 只新增离线 `report_tables.py`。运行 JSONL 去掉 invocation/step 字段后，与全局第 1673–10539 行的 8,867 个响应逐条相同，全部 HTTP 200；分步骤 token、费用与 `cost.json` 全部一致，E2 为 $5.2845672，全局为 $6.43753024。temperature=0 适用于聊天请求，embedding 没有该参数。测试输入答案列为空，所有样本 GPTAttempts 均在 1–5。`tests/test_leakage.py:183-221` 与本轮只改提示末句/解析的 diff 支持标签隔离：ASA24 的共同编码和真实单位仍限于已登记的条件分支，Nutrition5k 食物名来自模型回答。依据：CHECKLIST.md 原则 3–5、E2；paper.txt:151-171、224-228 右栏、303-306、518-527。这里的“一次”指一次正式运行，内部最多五轮见 R-E4-2；没有证据支持额外正式运行或按测试表现调整提示词。

- **R-E3-1 [approved]：主指标、对照表和论文常数可以复算。** `code/evaluate.py:30-46,54-67,83-175,178-207` 的 per dish、per unit、有效子集、累计匹配和成功率，与 CHECKLIST.md D1–D7 的已登记口径一致。用保存的回答重算后，ASA24 option n=21、amount n=20、端到端 n=112，Nutrition5k complete n=86、any-estimate n=102；另用逐食物营养向量求和核对完整菜，并得到 190/228 个食物项有克数。REPORT.md:139-186 的四组对照表与生成脚本一致。论文依据：paper.txt:200-220、224-228 右栏、249-254、314-325（Table 1）、334-350（Table 2）、368-380（Table 3）、445-448（Table 5）；MOESM2 第 4 页 Supplementary Table 2 的 98.9/84.2/80.5、Fig. 6a 的 93/89/84，以及 Table 3 的约 $0.1，均核对过。ASA24 的条件口径/端到端区别、any/first 和两种重量读法也已披露。此项只批准主指标与表格，不包括下面的失败归因和区间解释。

- **R-E3-2 [changes requested]（P2）：存在一例纯克重拒答，被错误归为改名，报告“128 道都给数字”不成立。** `runs/test/nutrition5k_nutrition.csv:327` 的 `dish_1561574479`，GPTAmount 是 “I'm unable to determine the exact weight of the foods in the image.”，没有任何数字；IngredientNum=1、WeightError=1、GPTWeight 为空。它正确计为主指标失败，故不需要改 MAE 或成功率。但 `runs/test/diagnostics/failures.py:49-65` 没有纯拒答分类，空的回答名字集合落入最后的“renamed, or split or merged otherwise”，导致 REPORT.md:102 的“128 道都给出了数字，没有不带数字的拒答”以及 :105-107、245、256、276 的归因不实。**请只修离线分类和文字**：实际为 127/128 道给出了数字、1 道纯拒答；按当前近似拆分规则，38 项应分为 20 项组合名拆开、14 项其他改名/拆合、3 项 Not visible、1 项整段拒答，名字问题合计 34 项。为该真实记录补一项离线回归检查，并核对每类能回到具体 dish_id；不要求修改推理解析、调提示词或重跑 E2。依据：paper.txt:224-228 右栏及 :546-550 要求按实际产出的响应判定成功；CHECKLIST.md 原则 4、D6 的失败不能被掩盖要求。报告中的“已没有拒答”和“只是名字问题”也必须遵守这个区别。

- **R-E2-2 [changes requested]（P2）：ASA24 的逐行 bootstrap 没有体现实际抽样单位，不能直接解释为此次设计的 95% 抽样区间。** `runs/test/diagnostics/bootstrap.py:40-43` 丢掉失败行后，对误差数组的每一行独立重抽样；但 CHECKLIST.md:148-150、REPORT.md:50,53 指定先抽 50 个 FoodCode、每个固定取三档，同一图片还可关联多个编码。实际 option 的 21 行只来自 10 个编码；端到端的 112 行来自 47 个编码、89 张不同图片。对行进行独立抽样破坏了每编码三档的成组结构，重复图片的行也被当成独立样本。因此 REPORT.md:115、119-122、191、266 把这些区间称为样本抽样误差并据此比较论文，依据不足。离线敏感性核对：种子 20261027，10,000 次从原 50 个编码中有放回各抽 50 个，保留各编码全部三档及失败，用每次误差总和/有效行数计算条件 MAE，option 重量区间约 37.0–153 g，端到端热量约 137–797 kcal；现有逐行结果分别为 46.5–145 g、154–686 kcal。这些示例用于证明抽样单位影响区间，不是替实现方选定最终方案。**请按编码成组重算并说明条件成功子集、重复图片和总体范围；或撤下这些 95% 抽样区间及相应推断。** Nutrition5k 按菜重抽样没有这个三档抽样问题，主要 MAE 点估计也不受影响。依据：paper.txt:227-239、300-307 的按食物三档设计；论文没有规定或报告这种 bootstrap，这是新增分析，必须使其方法与本次抽样设计相符。修复全部可以离线完成，不重跑推理。

- **R-E4-1 [changes requested]（P2）：偏差清单遗漏了 R-C8-1 的整体食物列表解析改写。** REPORT.md:232-238、246 只列数量解析、编码失败、续轮跳过、";;" 和克重读全文，没有列出对发布版食物列表解析的整体替换。首个提交 `5946365:code/nutrient_estimate_mix.py:30-61` 按 `'; '`、`': '` 切分，解析不了的项被丢弃；现在 `code/rag_portion_size.py:245-277` 与 `code/nutrient_estimate_mix.py:39-53` 共用 food_items，保留名字自带的分号/冒号、去掉引导语和列表标记、合并同名项，并保留没有合法编码的食物作为失败。这会改变克重请求列出的食物、IngredientNum、失败分母和完整菜子集，不只是第 22 条的空项修复。CHECKLIST.md:279-282 已有登记，旧审查 R-C8-1 及其处理也有依据，故无需重新决定或撤回修复；**请在 E4 增列这项并指向这些登记，与“换模型后的三处适配”区分。** 另按 R-E3-2 改正第 24、29 条的 E2 观察。其余 29 条的主要来源和 CHECKLIST 定位可以核对，未发现新的标签例外。论文依据：paper.txt:162-189 的识别食物列表及逐项求和、:224-228 右栏的成功率定义；CHECKLIST.md 原则 1 和 E4 要求披露相对原代码的差异。

- **R-E4-2 [changes requested]（P3，建议）：集中登记“正式运行一次”和“失败语义最多五轮”的区别。** REPORT.md:34 已写最多五轮，这一点没有隐瞒；建议 E4 也说明它继承自 `5946365:code/rag_food_code.py:208-224`、按 CHECKLIST.md:301-310 和节点一意见保留。它与 SDK 对 429/5xx 的相同请求重发不同：即使 HTTP 200，没给编码也从描述开始重新生成。E2 两个数据集的 GPTAttempts 合计分别为 309、295，分别有 54、53 个样本超过一轮。paper.txt:303-306 的“Each image was processed once per model”与这种内部重试存在协议解释空间，不能仅以一次 completed 调用消除该区别。建议登记为原代码与论文的一项口径歧义，提醒成功率是五轮后的最终结果；不要求改变已冻结逻辑、作一次机会的事后择优比较或重跑 E2。

- **R-E1-5 [changes requested]（P3，建议）：未来运行补 SIGTERM/异常退出对账，本轮不以此阻止报告。** `code/run_experiment.py:173-187,215-220` 依靠 finally 保存步骤和状态，默认 SIGTERM/SIGKILL 不保证执行；开发集留存已经证明可出现 running 状态、步骤响应未归档和已付费尝试未写回计数。建议以后捕获可处理的终止信号，并在恢复前核对未闭合步骤的全局日志和尝试次数；SIGKILL 仍需靠恢复时对账，不能承诺信号处理解决一切。当前缺口已披露且没有续跑这份目录，E2 的账完整，故不要求改写历史目录或为此重跑。依据：CHECKLIST.md:400,438-440；paper.txt:303-306、518-527 的可复现和实际支出口径。

- **R-REPORT-1 [approved]：遵守报告的环境信息边界。** REPORT.md 全文未写操作系统、机器、虚拟环境、Python 版本或安装方式；:281-297 只有代码、原运行命令、结果和离线测试入口。命令中的 `python` 是运行入口，没有披露版本或环境，不违反 CHECKLIST.md 原则 6。模型、temperature、图片尺寸、抽样和评测口径则按 paper.txt:227-240、303-306 正常保留。报告整体仍需处理 R-E3-2、R-E2-2、R-E4-1 后才能定稿。

按 AGENTS.md 的本轮流程，P2 逐条修复并在下节引用编号记处理结果；P3 可不改但需说明理由。此次意见不要求新增付费调用、测试后调参或第二次 E2；修复由协调对话离线确认，不再复审。

### 处理（实现 agent 写）

按 AGENTS.md 流程第 4 条处理，不再复审。全部离线完成：没有发请求，没有重跑 E2，也没有改推理代码、提示词和解析。`git diff 0e383c3 HEAD -- code/` 只新增了离线的 `failure_causes.py`。CHECKLIST.md 里 C8 记为 approved，E1、E2、E3、E4 改完记为 fixed。

- **R-E3-2 → `fa18a4b`**：
  - **分类**：移到新文件 `code/failure_causes.py`，增加"整段拒答"一类（整段回答没有任何数字）。判断顺序如下：
    - 名字在回答里但值不是数字，归为 Not visible 类；
    - 整段回答没有数字，归为整段拒答；
    - 名字按逗号、and、with 拆开后有部分出现在回答里，归为组合名被拆开；
    - 其余归为其他改名、拆合。
  - **E2 的 38 种**：20 种组合名被拆开，14 种其他改名或拆合，3 种 "Not visible"，1 种整段拒答（dish_1561574479）。名字问题合计 34 种。`runs/test/diagnostics/failures.txt` 列出每一类对应的菜。
  - **回归检查** `tests/test_failure_causes.py`：
    - 这条真实记录归为整段拒答。原来的分类把它算作改名，旧的 `failures.txt` 里 "renamed" 是 15。
    - 四类各有一个合成样例。
    - 在 E2 的表上核对：各类的数目对得上，整段拒答只有 dish_1561574479，每道菜的失败数等于它的 WeightError。
  - **REPORT.md 改正**：
    - 2.3：127/128 道给出了数字，1 道整段拒答；38 种的分类和分类规则；
    - 偏差清单第 25、30 条（原第 24、29 条）；
    - 第 5 节两处。
  - 主指标和成功率不变。
- **R-E2-2 → `49cb80f`**：
  - **重抽方法**：ASA24 按编码成组重抽。每次有放回地抽 50 个编码，保留各自三档（含失败的行），MAE = 有估计的行的误差总和 ÷ 有估计的行数。重抽 10,000 次，种子 20261027，每次都抽到了有估计的行。
  - **结果**：
    - option：重量 37–153 g、热量 46.1–146 kcal，都包含论文值；
    - 端到端：重量 80.7–216 g、热量 137–797 kcal，与审查的敏感性核对一致；
    - Nutrition5k 仍按菜重抽，改为每个口径单独设生成器，数值略变：重量 80.1–111 g、热量 99.4–150 kcal。
  - **REPORT.md 2.4**：写明重抽单位，以及三点：
    - 条件成功子集：论文协议的 21 行来自 10 个编码；
    - 重复图片：区间可能偏窄；
    - 区间代表的总体：284 个编码的抽样框，以本次回答为准，不含模型回答的随机性，不代表论文的 1,000 个编码。
  - **依赖区间的推断**：概要、3.5 和第 5 节按新区间改写。ASA24 论文协议的区间包含论文值，定不出差距；Nutrition5k 的区间仍明显高于论文值。
- **R-E4-1 → `4284514`**：
  - 偏差清单 4.4 增列第 22 条"Nutrition5k 食物列表解析的整体改写（R-C8-1）"，写明原代码的切分方式和丢项、现在的规则，以及它改变的食物列表、IngredientNum、失败分母和完整菜子集。
  - 这一条指向 CHECKLIST.md C8 的"食物列表的解析"和 R-C8-1，与 4.5 的换模型适配分开列。
  - ";;" 的修补成为第 23 条，后面各条顺延一位。报告和 CHECKLIST.md E4 里的编号引用一并更新。
  - 原第 24、29 条（现第 25、30 条）的 E2 观察已在 `fa18a4b` 改正。
  - 4.4 的标题去掉了"设计不变"，因为这一条会改变计数。
- **R-E4-2（P3）→ `4dc4ea6`**：采纳。偏差清单 4.7 增列第 31 条：
  - E2 是一次正式运行，但描述和选码对没有编码的图片照原代码最多重做 5 轮，与 SDK 对同一请求的重发不同。
  - E2 的尝试轮数合计 ASA24 309、Nutrition5k 295，用了不止一轮的分别有 54 张、53 道。
  - 登记为原代码与论文 "Each image was processed once per model" 之间的口径歧义；成功率是 5 轮之后的最终结果。
  - C9 加了指向这一条的说明。
- **R-E1-5（P3）→ `78d941a`**：不改代码。之后不再有新的运行，加信号处理和恢复前的对账已经用不上，所以把它登记为已知局限（REPORT.md 第 5 节、CHECKLIST.md E1）。E2 没有中断，账目完整。
- **approved**：R-C8-2、R-E1-4、R-E2-1、R-E3-1、R-REPORT-1，没有改动。
- **测试和检查**：
  - `unshare -rn .venv/bin/python -m unittest discover -s tests`：107 项全部通过，其中新增 `tests/test_failure_causes.py` 3 项。
  - 两个诊断脚本在断网下运行，`failures.txt`、`bootstrap.txt` 就是它们的输出。
  - REPORT.md 里仍然没有操作系统、机器和运行环境。


## 模型对照审查节点一：F1–F3 和 F5 预先实现的分析（`git log ddbc200..HEAD`）

### 待审查（实现 agent 写）

- **范围**：`ddbc200..HEAD` 的 F1 模型选择／temperature、F2 官方单价及推理 token 费用、F3 参数兼容和全部开发集输出；F5 仅预先实现的离线配对统计代码及 Exact 诊断参数化。F4 尚未开始，测试目录 `runs/test-gpt-6.1-sol/` 尚不存在。F1–F3 已标 ready for review；F5 的结果和报告留待节点二。
- **不变量**：对照 `ddbc200`，`evaluate.py`、`rag_portion_size.py`、`nutrient_estimate.py`、`nutrient_estimate_mix.py` 逐字不变；描述／查询／选码提示词、索引逻辑、重试及解析函数 AST 一致。没有新下载、没有重建索引，仍是 5,624 条。
- **开发集证据**：`runs/dev-gpt-6.1-sol-probe/` 单图确认旧参数被拒，费用 $0.004498；`runs/dev-gpt-6.1-sol/` 保留 200-token 描述上限耗尽的完整轮；最终 `runs/dev-gpt-6.1-sol-4096/` 的描述上限 4096、份量 600，212 次响应、92 次 chat 全部 stop，无空回答／截断，费用 $0.13707871，源代码指纹和参数在 config.json、响应日志、validation.json 中。
- **测试**：完整离线 unittest 119 项通过；新模型的四条 chat 路径、完整 mock 管线、目录配置隔离、费用、样本配对、成组 bootstrap 均覆盖。`agents/validate_model_run.py` 离线核对日志、费用和指标 PASS。用旧 E2 与自身比较，20 项 MAE 差值及区间全为 0（n=21/86）。旧 Exact 诊断输出逐字不变。runs/logs key 扫描通过。
- **特别核对**：temperature 1 与原 0 的联合偏差、描述上限增加是否必要且完整登记；SDK 1.12 与 LangChain 0.0.7 经 extra_body 的实际请求；推理 token 不重复收费；共同 Exact／完整菜的样本对齐与配对重抽分母；HTTP 200 与语义失败的区别。
- **预算**：累计 $6.71201545，剩余 $13.28798455；正式测试按开发集估算 $2.05618065，两倍余量 $4.1123613。审查和后续离线分析不调用付费 API。
- 按 AGENTS.md，本节点只审一次。审查 agent 只修改 REVIEW.md，给出逐项结论和优先级；实现方等待结论，处理 P1/P2 后才开始 F4。

### 审查（独立审查 agent，2026-10-27）

**总评：changes requested。** 本次审查范围固定为 `ddbc200..9e2b222`：F1、F2 approved；F3 的兼容实现和已留存的最终开发集证据成立，但离线校验器存在一项 P2（R-F3-1）；F5 预先提交的分析代码 approved，F4 和最终结果／报告不在本轮范围。没有发现 P1。按流程修复 R-F3-1 并由协调方离线确认后可继续 F4；此项不要求新的付费开发集运行，也不要求改变已冻结的提示词、解析、上限或重试。

- **R-F1-1 [approved]：可选模型切换和 temperature 偏差有隔离、有登记。** `code/config.py:18-34`、`code/run_experiment.py:239-252` 默认仍选 `gpt-4o-2024-08-06`，显式选择才同时切换文字和视觉模型，embedding 不变。`code/rag_food_code.py:39-63,182-187`、`code/chagApp_openai.py:56-78` 在四条 chat 路径按请求模型选 temperature；离线 MockTransport 检查确实落到请求 JSON，基线为 0，Sol 为 1。与 `ddbc200` 比较，描述、检索、选码的提示词、索引和重试函数 AST 不变；份量、评测和两个营养脚本逐字不变。`CHECKLIST.md:547-551` 已明确这是模型与采样设置的联合对照，不能严格归因于模型能力，符合 HANDOFF 5.2、5.4 对必要偏差的授权。论文依据：paper.txt:303-306 要求每图每模型一次、全部 temperature 0；本轮没有把 Sol 的设置说成与该条件相同，也未新增标签进入推理。

- **R-F2-1 [approved]：当前运行的单价、推理 token 和累计账目可复算。** `code/run_experiment.py:37-81,154-155` 保存价格来源、日期和单价，对无价模型／未配置的 Sol 长上下文显式报错；按非缓存输入、缓存输入和 completion 计费，reasoning 只另列，不再收费。审查时核对 [OpenAI 官方 Sol 模型页](https://developers.openai.com/api/docs/models/gpt-6.1-sol)：标准短上下文输入／缓存输入／输出分别为 $2／$0.10／$10 每百万 token；[官方推理说明](https://developers.openai.com/api/docs/guides/reasoning)说明推理 token 按输出计费。实际新 chat 响应均为 default 服务，缓存及 cache-write token 为 0，因此本轮账目不涉及缓存写入或其他服务档位。独立从日志重算三轮分别为 $0.004498、$0.13290850、$0.13707871；全局 10,962 条响应，累计 $6.71201545，余 $13.28798455，最终开发集的 150+150 张投影 $2.05618065、两倍余量 $4.11236130 均与留存值一致。`tests/test_model_comparison.py:73-92` 的手算也覆盖了缓存折扣和不重复计算推理 token。论文依据：paper.txt:518-527，费用以实际 API 支出除以评估图片数；这里的每图数值是数据集均摊值，`CHECKLIST.md:568` 已披露日志未逐图关联，未伪称逐图实测。

- **R-F3-1 [changes requested]（P2）：离线校验器会给空回答／截断的运行写出总体 PASS，须将账目一致与响应健康分开判定。** `agents/validate_model_run.py:34-48` 只断言模型、temperature 和 token 参数；`finish_counts` 和 `empty_chat_responses` 只是汇总字段，`checks` 在 :44 无条件为 `PASS`。审查的离线负面检查仅在内存日志副本里，把最终开发集同一个 request 的全局／运行记录设为 `finish_reasons=['length']`、`empty_contents=[True]`，不改 usage、配置、CSV 或文件；`validate()` 仍返回 `{'checks': 'PASS', 'finish_counts': {'length': 1, 'stop': 91}, 'empty_chat_responses': 1}`。这不是假设中的新失败：旧数值上限的真实开发记录 `runs/dev-gpt-6.1-sol/openai_api.jsonl:94` 就是 HTTP 200、length、空内容且 200 个 completion 全为 reasoning，`runs/dev-gpt-6.1-sol/nutrition5k_food_codes.csv:3` 还继续产出了编码。提高上限后的原始记录目前干净，但总体 PASS 不能承担 F3/F4 的语义健康核对。请让空回答、非正常完成或缺失健康元数据得到明确的非 PASS／needs-review 结论，并列出 request id 和 step；也可以将“账目／指纹核对通过”与“响应健康”分成两个独立状态。补离线负面回归，保留干净开发集通过的正例。无需因此改推理流程、自动重试或重跑已留存的开发集；非空 stop 的拒答和下游解析失败仍按冻结评测统计。依据：CHECKLIST.md:563-570 和本轮“特别核对”的 HTTP 200 与语义失败区别；paper.txt:224-228 的 SR 是产生相关食物／份量信息，paper.txt:303-306 的单次协议也不支持事后通过再跑来掩盖失败。

- **R-F3-2 [approved]：token 参数适配、必要上限偏差和最终开发集本身的证据成立。** 首个提交的 `code/rag_food_code.py:39`、`code/chagApp_openai.py:46` 确为描述 200／份量 600。`runs/dev-gpt-6.1-sol-probe/probe.py:18-36` 只由开发集第 0 行读取图片，不把标签传给模型；`probe.json:3-86` 留存旧参数的 400 及新参数三档正常回答。`code/config.py:37-51`、`code/rag_food_code.py:41-50` 用现有 SDK 的 extra_body 透传，离线实际请求验证没有把 extra_body 当作模型 JSON 字段，也没有带 max_tokens；描述只对 Sol 提高为 4096，份量仍 600，基线仍 200／600，多查询和选码仍不限。最终开发集 `runs/dev-gpt-6.1-sol-4096/config.json:8-38,40-90` 是单次 completed、开始时工作树干净；独立核对当前输入／源指纹、全局对应日志、费用和重新计算的 metrics 全部一致，212 次响应中的 92 次 chat 全部 stop、非空。原来的 200-token 完整轮保留，偏差与原／新 token 上限不完全等价已登记在 `CHECKLIST.md:560-570`；改变依据是开发集空回答，没有测试集调参证据。已有 Chroma 索引只读计数仍为 5,624。论文依据：paper.txt:130-160、237-240、303-306；上限数值来自作者代码，4096 是已披露的推理模型适配，不能说成论文原设定。此 approved 只确认这些实现和原始证据，不覆盖 R-F3-1 的总体 PASS 含义。

- **R-F5-1 [approved]：预先提交的配对分析保留了原评测定义、样本配对和成组分母。** `code/compare_models.py:22-31,95-112` 拒绝重复键、样本差异、参考标签漂移和未完成运行，校验 split／输入指纹／图片尺寸／embedding／份量代码一致。ASA24 用 FoodCode、Image、Size，Nutrition5k 用 dish_id 对齐；:60-74,114-142 分开报告各自成功子集及共同 Exact／完整菜，每个目标的有效行与原 `evaluate.mae` 一致，per unit 仍是 MAE 除以对应有效参考均值。:34-57 的同一组抽样同时用于两边，ASA24 保留所有抽到编码的三档和失败，Nutrition5k 按菜；共同子集两边使用同一有效行，完全无估计的重抽显式计数，未把两个独立重抽的区间当成配对区间。`tests/test_compare_models.py:14-66` 的手算例覆盖乱序、重复／标签漂移、不同成功子集、完全无估计及会区分“按行重抽”的成组反例。独立以旧 E2 与自身比较，20 个 MAE 差值及 95% 区间全为 0，ASA24 n=21、Nutrition5k n=86；各目标 MAE／per unit 与旧 metrics 在浮点精度内吻合。`runs/test/diagnostics/exact_misses.py:19-21` 仅参数化目录，对旧 E2 的输出与 `ddbc200` 逐字一致。论文依据：paper.txt:200-220 的 Exact／份量分类，:227-240 的编码三档抽样，:242-259 的参考标签与 MAE，:299-307 的配对比较，以及 :324-325 的 per unit 定义。配对 bootstrap 是本项目新增分析，代码／清单正确限定为当前回答条件下的不确定性；最终 F4 的配对结果和报告仍留节点二审查。

**离线验证与边界：** `PYTHONDONTWRITEBYTECODE=1 unshare -rn .venv/bin/python -m unittest discover -s tests`：119 项全部通过（26.215 秒）；另做上述原始记录复算、F5 自身比较、Exact 诊断逐字对照和校验器负面检查。范围内最终文件及所有提交 diff 的 `sk-` 长串扫描未命中，新增响应日志仅存白名单元数据（`code/api_log.py:87-122`）；没有发现本轮 key 泄漏。没有调用付费 API、下载数据、修改代码或运行输出；本次只追加 REVIEW.md，不提交。


### 处理（实现 agent 写）

- **R-F3-1（P2）→ fixed**：`agents/validate_model_run.py` 将账目／指纹／指标一致性与响应健康分开：reconciliation_checks=PASS 只说明前者；空回答、非 stop 或缺失／无效健康元数据使 response_health 和总体 checks 为 needs review，附 request id、step 和问题，CLI 返回非零。不会自动重试、改推理或掩盖失败。
- 新增 `tests/test_validate_model_run.py`：负面测试在内存中向全局与运行账目同时注入同一个空回答＋length，保证账仍一致但总体不再 PASS；另覆盖内容过滤和健康元数据缺失；真实干净开发集仍 PASS。全部 **121 项离线测试通过**。
- 已重新运行协调方校验：最终开发集 reconciliation_checks=PASS、response_health=PASS、health_issues=[]，212 条响应和指标／费用仍一致，validation.json 已更新。没有重跑开发集，没有新增 API 调用、下载或推理代码修改。
- **approved 保留**：R-F1-1、R-F2-1、R-F3-2、R-F5-1。按单次审查流程不复审，F1/F2 标 approved、F3 标 fixed；本节点全部 P1/P2 已处理，直接继续 F4。F5 最终结果仍交节点二。


## 模型对照审查节点二：F4 正式结果、F5 配对分析和报告（`git log fbe5157..HEAD`）

### 待审查（实现 agent 写）

- **范围**：`fbe5157..HEAD` 的 F4 单次正式测试输出，以及 F5 全部离线对照、Exact／失败诊断、REPORT 第 7 节和开头的模型对照结论。报告第 1–6 节标明保留第一轮记录。F4/F5 均 ready for review；节点一已处理，不做复审。
- **一次正式运行**：`runs/test-gpt-6.1-sol/config.json` 一次 completed，提交 fbe5157、开始时工作区干净；09:02:43–09:43:34 UTC，150+150 行，与最终开发集相同的推理源指纹。没有重跑、下载、重建索引、提示词／解析／评测更改。
- **费用和实际模型**：3,234 个响应，3,233 个 200 和 1 个 500；成功 chat 1,391 个全部 stop，无空内容或截断，实际模型与请求一致。费用 $2.29594796，项目累计 $9.00796341。原始日志／费用／指纹／指标协调方重新核对一致。
- **需要特别审查的历史错误**：HTTP 500 request id `req_4daec2277b3a4b03b121a13a547af336` 在 ASA24 选码，由原 SDK 逻辑重试后流程完成。校验器未将其忽略：reconciliation_checks=PASS、response_health 与总体 checks=needs review，CLI 返回非零并列此请求。错误响应没有 model_served，新增校验器分支仅对 200 核对实际模型，仍核对所有请求。这个改动只影响离线核对，没有改 API／推理／评测。请确认这条历史异常的披露和账目，不通过改写状态或重跑消除它。
- **结果与统计**：各自 ASA24 Exact 21→11，MAE 92.65→59.68 g，但子集不同；共同 Exact 10 行／8 编码，102.28→59.4 g，配对区间含 0，分类 30%→30%。Nutrition5k 各自完整菜 86→118；共同 79 道，重量 96.01→62.24 g、区间 −48.92～−19.66；热量 126.86→131.83，区间含 0。共同菜低估改善但营养误差没有同步改善。正文没有把它写成“全部差距都来自模型”或反向断言。
- **材料**：`runs/comparison-gpt-4o-vs-sol/comparison.json`／`.md` 有各自／共同五项目标、per unit、差值区间、共同键、有效行和无估计的重抽次数；表格原样嵌入 REPORT。统计方法在 F4 前已提交并获节点一 R-F5-1 approved，正式测试后只改离线表格的呈现，没有改统计计算。
- **诊断**：同一个 Exact 脚本得到 127/139 未进候选、12/139 检索后未选；同一失败规则得到 32 项（30 组合拆开、2 其他改名）并与 WeightError 对上；名称分类仍注明启发式、近似。
- **验证**：完整离线 unittest 121 项通过；报告嵌表逐字一致、共同分类逐行对错一致、报告不含操作系统／机器／环境信息；推理、解析、营养和评测与正式开始提交无差异。新增结果及提交前 key 扫描通过。
- 本节点只审一次。只修改 REVIEW.md，不改代码或提交，可运行离线核对，不得调用付费 API、下载或重新运行正式测试。P1/P2 实现方逐项处理后由协调方离线确认，不再复审。

### 审查（独立审查 agent，2026-10-27）

**结论：approved。** 本次只审 `fbe5157..0a1f627` 的 F4 正式输出、F5 最终配对结果／诊断、REPORT 第 7 节与模型对照概要，以及离线校验器对历史 500 的披露；没有复审节点一。未发现本节点需要修改的 P1、P2 或 P3。

- **R-F4-1 [approved]：正式运行、样本和参数与冻结配置相符，没有发现测试后调参或新增标签进入推理的证据。** `runs/test-gpt-6.1-sol/config.json:2-46,47-90,120-123` 留存一次 completed invocation、启动提交 `fbe5157`、干净工作树、150+150 行、模型／temperature／token 参数和输入／源代码指纹。独立核对当前六个输入表的 sha256、启动提交的五个推理源文件及最终开发集的对应源指纹，全部一致；`fbe5157..0a1f627` 没有修改推理、份量、营养或评测源文件。原始日志中 307 次描述均用 4096，470 次份量均用 600，614 次成功多查询／选码不限；成功 chat 实际模型均为 gpt-6.1-sol、temperature 1、未指定 reasoning_effort、default 服务，1,842 次 embedding 请求仍是 text-embedding-3-large。两模型的 ASA24 键与参考份量／重量、Nutrition5k 的 dish_id 与五项参考标签逐行相同且无重复键；两份正式表均为 150 行。`REPORT.md:327-343` 披露了 temperature、推理 token 上限及条件评测边界，没有将本轮写成论文原设定。论文依据：paper.txt:155-160、227-240 的 embedding／数据处理，:303-306 的每图每模型一次、temperature 0；本轮必要偏差已明确登记，单次运行不等于不存在原代码内部的重试。

- **R-F4-2 [approved]：500 及重发如实留存，账目一致没有被写成全部响应健康。** `runs/test-gpt-6.1-sol/openai_api.jsonl:185` 是唯一 HTTP 500，request id 为 `req_4daec2277b3a4b03b121a13a547af336`，没有 model_served／usage／完成元数据；`runs/test-gpt-6.1-sol/process_images.log:251-252` 同时留存 500 与 SDK 重试。`agents/validate_model_run.py:57-78` 的新分支只对 200 要求实际模型一致，所有 chat 仍核对请求模型和参数，非 200 仍进入健康问题；`runs/test-gpt-6.1-sol/validation.json:2-24` 如实保留 reconciliation_checks=PASS、response_health／checks=needs review 和该请求。独立调用只读的 validate 函数，结果与存档一致；3,234 个响应是 3,233 个 200 加 1 个 500，1,391 个成功 chat 均 stop、非空。按原始日志和已登记单价用 Decimal 另行计账，本轮 **$2.29594796**，全局 14,196 条响应累计 **$9.00796341**，与 `cost.json:64-78`、`validation.json:29-52` 一致；124,310 个 completion token 已包含 64,977 个 reasoning token，没有重复收费。`REPORT.md:350-355` 明确费用按返回 token 估算，并区分表级最多五轮与 SDK 重发；500 无 usage 没有被虚构成有已知 token 的收费记录。论文依据：paper.txt:224-228 的成功率是产生食物／份量信息，不能由 HTTP 状态替代；:303-306 的运行协议和 :518-527 的费用均摊定义。本次接受历史异常的披露与处理，不要求重跑，也不要求把原健康状态改为 PASS。

- **R-F5-2 [approved]：最终配对样本、全部点值／per unit 和区间可由原始表复算。** `code/compare_models.py:22-74,95-149` 保留节点一已批准的统计计算；本范围对它的修改仅在 :153-207 的表格呈现。以原始 CSV 重新计算 comparison JSON／Markdown，保存值和报告嵌表逐字一致；另用原始参考营养密度、逐行绝对误差和每次抽样的组出现次数独立复算全部 **20 组**点值、per unit 和 10,000 次差值百分位区间，均一致（浮点差小于 1e-9）。ASA24 各自 Exact 21／11 行，分别来自 10／9 个编码，共同 10 行／8 编码；共同重量 102.275→59.4 g，差值区间 −88.1507～0.75；共同份量分类两边逐行对错一致，均 3/10，因此本次条件区间为 0～0。Nutrition5k 各自完整菜 86／118，共同 79；共同重量 96.0127→62.2405 g，差值区间 −48.9157～−19.6614，共同热量 126.857→131.832 kcal，区间含 0。原始表直接复算的共同重量符号误差 −75.0506→−25.1519 g、比值中位数 0.678733→0.940171 也一致。证据：`runs/comparison-gpt-4o-vs-sol/comparison.json:20-99,190-233,302-326,520-658`、`REPORT.md:359-406`。ASA24 每个目标和共同准确率均有 1 次无估计重抽，Nutrition5k 为 0，已显式记录，没有补成 0 误差；共同目标两边使用相同有效行。论文依据：paper.txt:200-220 的 Exact／份量指标，:227-240 的按编码三档抽样，:242-259 的预测对参考标签 MAE，:299-307 的配对比较及 :324-325 的 per unit 定义。成组 bootstrap 是新增分析，报告正确限定为本次回答条件下的抽样区间。

- **R-F5-3 [approved]：失败没有混入成功，诊断及结论没有超出证据。** 从 `asa24_portion.csv` 和 `nutrition5k_portion.csv` 在内存中重做份量／营养计算，两套最终表的全部派生列与存档相符；重新执行只读 Exact 诊断，输出 sha256 与 `runs/test-gpt-6.1-sol/diagnostics/exact_misses.txt` 完全相同。原始候选表核实 139 个非 Exact 中 127 个标签未进候选、12 个进候选但未选，32 行选中同照片关联编码（该文件 :21-24）；失败逐项复算为 207 项食物中的 32 项克数缺失，32 道菜各一项，30 个组合拆开、2 个其他改名，与每道菜 WeightError 及 `diagnostics/failures.json:4-8,169-180` 对齐，FoodCodeError=0。`REPORT.md:411-425` 正确保留两轮分母差别、失去／新增成功样本、名称分类的启发式局限，未将 150/150 有编码等同于编码正确；共同子集上的克重改善没有被扩展为全部测试行、营养改善或模型能力的单独因果效应。概要 `REPORT.md:5-7` 与第 7 节一致，temperature／上限同时变化、只有一次抽样、共同成功子集选择和共享照片相关的局限均已说明。论文依据：paper.txt:200-228 的匹配／份量／SR 区别，:242-259 的营养评测与 :303-306 的模型和确定性设置；本轮未用新的失败归因更改冻结解析或评测。

**离线验证与边界：** `PYTHONDONTWRITEBYTECODE=1 unshare -rn .venv/bin/python -m unittest discover -s tests`：**121 项全部通过**（29.124 秒）。额外完成上述逐请求账目、配置／指纹、原始份量到营养表、独立配对重抽、诊断和报告嵌表核对。新增结果文件及两个提交的完整 diff 未发现 `sk-` 长串；响应日志仍仅含白名单元数据，未发现本轮 key 泄漏。没有调用付费 API、下载、重跑正式测试或修改代码／运行输出；仅追加 REVIEW.md，不提交。以上 approved 接受已披露的历史 500，不改变 validation.json 的 needs review。


### 处理（实现 agent 写）

- 节点二 **R-F4-1、R-F4-2、R-F5-2、R-F5-3 全部 approved**，没有 P1/P2/P3 要处理，按流程不复审。F4、F5 标 approved，F1/F2 保持 approved，F3 保持 fixed（节点一 R-F3-1 已离线确认）。
- 报告与结果定稿，未追加 API 调用、下载、推理或评测改动，正式测试仍为一次。`validation.json` 仍保留历史 500 引起的 needs review；节点二接受其披露和复算，未改写成总体 PASS。
- 审查方已独立确认 121 项离线测试及全部统计、派生表、费用和诊断；最后仅更新清单与审查处理记录，不重复运行测试或实验。

## F6：用户要求的英文整合版（文档修订记录，非新增审查节点）

- 用户要求把补充模型对照整合进原报告，说明原 GPT-4 Turbo 停止服务是开展对照的原因，精简部分表述，并将全文改为英文。
- 实现方将 REPORT.md 的两轮方法、结果和讨论合并，保留关键样本数、各自／共同子集、五项 MAE 与 per unit、配对区间、历史 500、模型参数偏差和结论边界。详细逐项修复历史仍在 CHECKLIST.md／本文件，旧报告可由提交 `0dd2160` 查询。
- 英文报告中的五个指标表逐项对应保存的 comparison.json／metrics.json；论文目标与 evaluate.PAPER 对应，中文残留、链接、表格结构和敏感串检查通过。没有改代码、原始结果或日志，没有下载或调用 API，也没有重复正式测试。
- 本轮是按用户要求进行的翻译与编辑，按每节点只审一次的既定流程不发起复审。上面独立审查的文件行号和章节编号对应其审查提交；不应将其解释成对本次英文表述的新增审查。
