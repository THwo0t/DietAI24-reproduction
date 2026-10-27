# DietAI24 复现 checklist

**目标**：以作者发布的原代码（v1.0-paper，commit `8bc77c3`，见首个提交）为基础，原代码缺的部分按论文补全，在分层小样本上得到能与论文 Table 1、Table 2 对比的 MAE。

## 原则

1. **原代码与论文的关系**：原代码已有的，照原代码；原代码缺的，按论文补；两者冲突的，在对应条目里登记，论文正文明确写了的以论文为准。
2. **提交方式**：改动尽量小，每个条目单独提交。提交说明以条目编号开头（如 `C4: …`），写明论文出处。
3. **标签隔离**：推理只接收图片，参考标签只在评测时读取。论文 ASA24 协议本身用到的真实编码和份量信息（D1、C5）是例外，必须在结果里标明为"论文协议的条件设定"。
4. **不在测试集上调参**：要试跑就用开发集，开发集与测试集不重叠。
5. **下载和付费调用**：联网下载数据、调用付费 API 之前先征得用户同意。每次运行都记录配置、请求日志（去掉 key）和 token 用量。用户 2026-10-27 已批准：
   - 下载 Nutrition5k 俯拍 RGB 图（测试 150 张、开发 10 张，上限 200 张、约 80 MB）和 tiktoken 的 cl100k_base；
   - 付费调用（embedding 建索引、E1、E2）合计不超过 $20，按 `logs/openai_api.jsonl` 的 token 用量和单价累计；E1 后按实际花费估算 E2，超过上限先停下问用户；
   - 样本量：正式运行 ASA24 50 个编码 × 大中小 3 档共 150 张，Nutrition5k 150 张；开发集 ASA24 10 张、Nutrition5k 10 张，与测试集不重叠。只做论文的这两个数据集，E5 不做。
6. **运行与报告**：所有运行都在本机完成，不做跨机器交付。最终实验报告也在本机撰写，报告里不写操作系统、机器和运行环境（虚拟环境、Python 版本、安装方式等）；模型、数据、评测口径和偏差照常写。
7. **条目状态**：`todo` → `in progress` → `ready for review` → `approved`，或 `changes requested` → `fixed`（按审查意见改完，不再复审）。审查记录写在 REVIEW.md。

## 论文目标（DietAI24，MAE per dish / per unit）

| 数据集（样本） | 重量 (g) | 热量 (kcal) | 脂肪 (g) | 碳水 (g) | 蛋白质 (g) |
|---|---|---|---|---|---|
| ASA24（3000 张） | 49.4 / 0.348 | 47.7 / 0.196 | 1.8 / 0.174 | 6.95 / 0.208 | 1.38 / 0.233 |
| Nutrition5k（1000 张） | 45.1 / 0.156 | 68.2 / 0.197 | 4.01 / 0.226 | 5.98 / 0.212 | 3.88 / 0.188 |

per unit = MAE ÷ 参考均值（Table 1、Table 2 注释）。

## 资料位置

| 资料 | 路径或来源 |
|---|---|
| 论文正文（双栏抽取，左右栏同行交错，下文行号均指此文件） | `/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/paper/paper.txt` |
| 补充材料（Supplementary Information 含 Tables 1–3、Figs. 1–6，其中 Figs. 4–5 是提示词模板；另有审稿意见与作者回复、Reporting Summary） | `paper/supplementary/`（PDF 不提交，来源与 sha256 见 SOURCES.md） |
| FNDDS 2019–2020、ASA24 图片与元数据、NHANES XPT | `/home/lelouch/Data/Projects/DietAI24_mac_snapshot_20261022/data/`（只读；之前的 Mac 版从官方下载） |
| Nutrition5k 元数据 | `/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/audit_data/`；图片需从官方存储下载 |
| 基于 Mac 重写版的旧结果（端到端对照，不改） | `/home/lelouch/Data/Projects/DietAI24/` |

## 对齐清单：之前 Mac 重写版偏离原项目的地方

之前的结果来自 Mac 版重写的代码：只保留了作者的文件名，逐行相似度 4–12%，`main.py`、`evaluate.py` 是新写的。下表每一行都必须按原项目对齐，审查时逐行确认。其中 temperature 和选码两行，Mac 版其实与论文一致，偏离论文的是作者原代码本身，按原则以论文为准。

| 环节 | 原项目（论文与原代码） | 之前的 Mac 版 | 对应条目 |
|---|---|---|---|
| 模型 | GPT-4 Turbo（已下线，改用 `gpt-4o-2024-08-06`） | gpt-4o-mini | A3 |
| temperature | 论文为 0；原代码是 0.01、0.1、0.3，按论文改为 0 | 0 | A4 |
| 图片 | 统一缩放到 256×256 | 原尺寸 | B6 |
| 检索 | `text-embedding-3-large`、LangChain Chroma、MultiQueryRetriever | 本地 MiniLM 加关键词打分 | A2、C1、C3 |
| 选码 | 论文：视觉模型看图片和候选；原代码用文字模型、没传图片，按论文修正 | 视觉模型看图片和候选 | C4 |
| ASA24 份量 | 在该食物的 ASA24 份量序列里选（shot），再问有几个真实单位（amount） | 在预测编码的全部 FNDDS 份量里选，固定 1 个单位 | C5、C6 |
| Nutrition5k | 每种食物估克数；同一食物的多个候选编码，营养取平均（`nutrient_estimate_mix.py`） | 修复前整盘只算一个食物 | C8 |
| 评测口径 | 有条件：只算预测编码包含真实编码的图片（FoodCodeCommon），营养按真实编码计算，失败不计入 MAE | 端到端，任何参考信息都不进推理 | D1、D2（端到端另报 D3） |

## A 环境与配置

### A1 Python 环境 — 状态：approved（第 1 轮）
- **原代码**：`env/env.yml` 固定了 Python 3.10.13、langchain 0.1.9、langchain-community 0.0.24、langchain-core 0.1.35、langchain-openai 0.0.7、chromadb 0.4.24、openai 1.12.0、pandas 2.2.1、numpy 1.26.4、tiktoken 0.6.0。
- **要做**：建 Python 3.10 虚拟环境，只装代码实际 import 的包，版本按 env.yml 固定，写成 `requirements.txt`。本机只有 Python 3.14，需要先装一个 3.10（例如用 uv）。
- **验收**：`code/` 下各脚本都能 import；`pip freeze` 存档。
- **登记**：
  - `code/ViT/` 不装：它需要 torch、transformers、fire，env.yml 里没有，ViT 基线也不在复现范围内。
  - greenlet 3.0.3 不在 env.yml：SQLAlchemy 2.0.27 在 Linux x86_64 上依赖它，作者的 macOS arm64 上不需要。取的是 env.yml 建立时（2024 年 3 月）greenlet 的最新版。
  - 其余依赖的版本都取自 env.yml（pip 部分优先，其次 conda 部分）。存档 `env/pip-freeze.txt` 共 119 个包，`tests/test_env.py` 逐个核对。

### A2 API 配置 — 状态：approved（第 1 轮复审）
- **原代码**：`config.py` 和 `rag_food_code.py` 用 Azure（AzureChatOpenAI、AzureOpenAIEmbeddings、deployment 名）；`chagApp_openai.py` 用 `OpenAI()` 读环境变量。
- **要做**：改为 OpenAI 官方接口（langchain_openai 的 ChatOpenAI、OpenAIEmbeddings）。key 只从 `.env` 读，模型名集中在 `config.py`。
- **验收**：代码里没有 key，`.env` 被 git 忽略。
- **登记**：
  - `config.load_api_key` 只读仓库根目录的 `.env`，先找 `OPENAI_API_KEY`，再找 `CHAT_API_KEY`（旧项目 `.env` 用的名字），读不到就报错。不读 shell 环境变量，也不把 key 写进 `os.environ`。端点固定为 `https://api.openai.com/v1`，`OPENAI_BASE_URL` 和 `OPENAI_API_BASE` 不起作用。
  - `.env` 的值按字面读取，关闭 python-dotenv 的 `${...}` 插值（默认会用 shell 环境变量展开）。值里出现 `$` 就报错，不支持占位符（R-A2-1）。
  - 模型名集中到 `config.MODELS`：`rag_portion_size.py`、`baseline_chatGPT.py` 原来写死的 `Vision("gpt-4-turbo")` 改为读 `MODELS['llm_vision']`。Azure 部署名 `gptv` 在 OpenAI 上没有同名模型，所以 A2 暂时把 `llm_vision` 设为原代码 OpenAI 路径用的 `gpt-4-turbo`，具体模型在 A3 定。
  - `chatApp_azure.py` 没有改：任何脚本都不 import 它，它不在运行路径上。

### A3 模型 — 状态：approved（审查节点一 R-A3-3：R-A3-2 的修复成立；用户 2026-10-27 确认用 `gpt-4o-2024-08-06`）
- **论文**：GPT-4 Vision-Preview 与 GPT-4 1106-Preview（GPT-4 Turbo），embedding 用 text-embedding-3-large（paper.txt 第 155–157、303–305 行）。
- **现状**：论文的两个模型均已下线。2026-10-27 调用 `gpt-4-turbo` 和 `gpt-4-turbo-2024-04-09` 都返回 404 "model … has been deprecated"。同日测试：`gpt-4o-2024-08-06` 可用，支持 temperature=0；`gpt-5.6-sol`、`gpt-6-astra`、`gpt-6-luna`、`gpt-6.1-sol` 能看图，但都拒绝 temperature=0（返回 400 "Only the default (1) value is supported"），而且是推理模型，会额外产生推理 token。
- **要做**：视觉和文字步骤统一用 `gpt-4o-2024-08-06`；embedding 保持 text-embedding-3-large。作者回复审稿意见时也说明是通过 OpenAI API、temperature 0 调用（审稿文件 MOESM1）。
- **验收**：运行配置里记录实际提供服务的模型名。
- **登记**：
  - 论文 Methods 写的是 GPT-4 Vision-Preview 和 GPT-4 1106-Preview（第 303–304 行），Results 称"the latest GPT-4 Turbo Vision model"（第 472、507 行）。原代码选码步骤用 Azure 部署 `gptv` 和 `gpt-4-turbo`；份量步骤和 GPT 基线用 OpenAI 的 `gpt-4-turbo`，这个别名自 2024-04-09 起指向 `gpt-4-turbo-2024-04-09`，不是 1106-Preview。这些模型都已下线，`config.MODELS` 的 `llm` 和 `llm_vision` 统一改为 `gpt-4o-2024-08-06`。
  - 记录方式：所有 OpenAI 客户端都由 `api_log.openai_client()` 创建，每次响应往 `logs/openai_api.jsonl` 写一行，内容包括请求的模型、响应里的 `model`（实际提供服务的模型）、temperature、max_tokens、token 用量、request id 和错误码。不写 header（含 key）、消息内容和错误信息（401 的错误信息会带 key 的片段）。E1、E2 的运行配置从这个文件汇总实际模型名。
  - LangChain 的 ChatOpenAI 和 OpenAIEmbeddings 是通过 `client=` 接入这个客户端的：langchain-openai 0.0.7 的 `llm_output` 只给出请求的模型名，拿不到响应里的模型名。
  - API 报错（例如 401）时，SDK 的异常信息会原样带上响应里的错误信息，其中有 key 的首尾片段，而原代码会把 `str(e)` 写进处理日志、结果 CSV 和 print。现在 `openai_client()` 返回的 `RedactedOpenAI` 先去掉响应里 key 的回显，再交给 SDK 构造状态错误，所以异常信息、`e.body`、`e.response` 都来自同一份去掉回显的内容（R-A3-1）。状态码保留，request id 留在 `e.response.headers` 和调用日志里。LangChain 默认另建的异步客户端不经过这里，本项目只用同步调用。
  - 只替换 key 的回显：完整 key；含 `***` 的 token（401 信息把 key 写成"前 8 位****后 4 位"）；前面不紧挨字母、数字、`_`、`-` 的 `sk-` token；以 key 前 8 位开头、后 4 位结尾的 token。单独的片段不替换，因为 key 的后 4 位可能就是 `rate`、`_key`、`null` 这类普通文字。JSON 响应按结构处理：先解析，只处理字符串值，再重新序列化；错误的 `type`、`code`、`param` 原样保留。没有回显的响应原样交给 SDK（R-A3-2）。

### A4 temperature — 状态：approved（第 1 轮）
- **论文**：所有调用 temperature = 0（第 305 行）。
- **原代码**：`rag_food_code.py` 视觉 0.1、文字 0.3；`chagApp_openai.py` 0.01。
- **要做**：统一为 0。这是冲突项，按论文处理。
- **登记**：
  - 三处都改为读 `config.TEMPERATURE = 0`：`chagApp_openai.Vision.chat` 原来是 0.01，`rag_food_code` 的视觉模型原来是 0.1、文字模型原来是 0.3。LangChain 把 temperature 存成 float，所以请求里是 `0.0`。每次调用实际发出的 temperature 也会写进 A3 的调用日志。
  - `chatApp_azure.py` 里的 0.3 没有改：没有脚本 import 它（见 A2）。

### A5 每张图独立调用 — 状态：approved（第 1 轮）
- **论文**：每张图每个模型只处理一次（第 304–305 行）。
- **原代码**：`chagApp_openai.Vision.chat` 把每轮问答累积在 `self.messages` 里，同一实例处理的后续图片会带上之前所有图片和回答。
- **要做**：每次调用只包含 system 提示和当前的问题与图片。
- **验收**：离线测试确认连续两次调用的消息长度相同。
- **登记**：
  - 现在 `Vision.chat` 每次只发 `self.messages`（只有 system 提示）加当前的问题和图片，回答不再写回 `self.messages`。
  - 原来的问题：`rag_portion_size.main` 用同一个 Vision 实例依次处理所有图片，shot 和 amount 各一轮，所以第 n 次请求会带上前面所有的图片和回答。
  - `append_message` 保留了，但没有调用方。
  - `rag_food_code` 的图片描述步骤本来就是每张图新建一组消息，测试也覆盖了这一步。

## B 数据

### B1 FNDDS 食物描述表 — 状态：approved（审查节点一）
- **论文**：5,624 种食物的描述做 embedding（第 129–160 行）。
- **原代码**：`fndds_proc.py`，把 Foods and Beverages 表转成 "The image shows the food category of …" 文本。
- **要做**：把 FNDDS 2019–2020 At A Glance 的三个 xlsx 放进 `FNDDS/`（文件名按原代码期望），然后运行。
- **验收**：输出 CSV 有 5,624 行。
- **登记**：三个 xlsx 由 `code/place_inputs.py` 从本机快照复制到 `FNDDS/`，按 sha256 核对，文件名按原代码。`fndds_proc.py` 原样运行，输出 5,624 行、5,624 个编码，与论文 J = 5624 一致（第 130–131 行）。

### B2 FNDDS 份量与营养表 — 状态：approved（审查节点一）
- **原代码**：`nutrient_estimate.py` 读 `../FoodWeights.csv`（列：Food Code、Portion Code、Subcode、Portion Weight）和 FNDDS Nutrient Values xlsx。FoodWeights.csv 的生成脚本缺失。
- **要做**：从 FNDDS 2019–2020 Portions and Weights 表生成 FoodWeights.csv，列名对齐。
- **验收**：行数与 xlsx 一致；抽查 3 个编码。
- **登记**：
  - At A Glance 的 Portions and Weights 表没有份量编码，所以新写的 `code/fndds_weights_proc.py` 改从 FNDDS 2019–2020 详细库（`FNDDS_2019-2020_SAS.EXE` 解出的 `foodweights`、`foodportiondesc`）生成。两表逐行一致，共 22,710 行，重量和描述都相同。论文写的是"over 23,000 portion sizes"（第 132 行）。
  - FNDDS 2019–2020 没有份量子编码，(Food Code, Portion Code) 唯一，所以 Subcode 记为 0，`get_portion_weight` 不会用到它。另加了 Seq Num 和 Portion Description 两列，原代码不读。
  - 根目录下原代码读写的表（`../FoodWeights.csv` 等）加入 `.gitignore`。

### B3 ASA24 前 1000 个高频编码 — 状态：approved（审查节点一）
- **论文**：按 NHANES 消费频率取前 1000 个编码，占美国日常食物消费的 81.4%（第 227–229 行）。
- **原代码**：`asa_proc.py`，用 4 个周期的 DR1IFF，筛 DR1DRSTZ==1。
- **要做**：放好 NHANES XPT 后运行。
- **验收**：输出 1000 行；记录其中有 ASA24 图片的编码数。
- **登记**：
  - 四期 DR1IFF（G、H、I、P）由 `code/place_inputs.py` 从本机快照复制，按 sha256 核对。
  - `asa_proc.py` 改了两处才能运行：`load_data` 原来把输出路径也当输入读（第一次运行时文件不存在）；描述列原来读 `Main Food description`，B1 的 `fndds_proc.py` 写出的列名是 `Food description`。描述列只用于报表，不影响选码。
  - 结果：555,140 条记录（DR1DRSTZ==1），7,761 个编码；前 1000 个占 81.36%，与论文 81.4% 一致。第 1000、1001 名都是 83 条，按原代码的稳定排序取前者（22400120）。`tests/test_data.py` 的 TestB3 重新计算核对。
  - 1000 个编码里，857 个在 FNDDS 2019–2020 里；666 个出现在 ASA24 元数据 AssociatedCodes 中，其中 650 个有 PORTION 类型、带份量文字、且在图片包里的图片。抽样规则见 B4。

### B4 ASA24 图片与标签表 — 状态：approved（审查节点一）
- **论文**：每个编码取最大、中间、最小份量各 1 张，共 3000 张（第 230–232 行）。每张图链接到 FNDDS 编码和份量（第 199–206 行）。
- **原代码**：`rag_portion_size.py` 和 `nutrient_estimate.py` 读 `../df_image_link.csv`（FoodCode、Portion、Multiplier、Link 等）和 `../df_results.csv`，两张表的生成脚本缺失。
- **要做**：
  - 由 ASA24 元数据生成这两张表。
  - 按用户决定抽分层小样本：从前 1000 个编码里随机取 50 个（固定种子），每个编码 3 档，共 150 张；开发集 10 张，编码不在测试集里。
  - ASA24 旧元数据的份量编码与 FNDDS 2019–2020 不一致时怎么处理，要写清规则。之前 Mac 版发现约 43% 的行需要推断映射。
- **验收**：150 行，每个编码 3 档，与开发集不重叠。
- **登记**：
  - 新脚本 `code/asa24_proc.py` 写出 `../df_image_link.csv`（每个合格编码的份量序列，一张图一行）、`../df_results.csv`（测试集 150 行）和 `../df_results_dev.csv`（开发集 10 行）。图片包和元数据由 `place_inputs.py` 按 sha256 复制到 `ASA24/`，用到的 443 张图解压到 `ASA24/images/`。
  - 取哪些行：AssociatedCodes 中 ImageType 为 PORTION、ModCode 为 0、图片在包里、ImageFileInventory 有份量文字（Portion）的行。SIZE 类型是容器图，没有份量文字，大多也不在包里。
  - 参考克重 = Multiplier × FNDDS 2019–2020 中 (FoodCode, PortionCode) 的克重；PortionCode 98（1 克）记为 Multiplier 克。按元数据 ReadMe，Multiplier 是 PortionCode 那个量的倍数，例如 "1/4 cup" 记为 2 × fl oz。
  - **份量编码映射规则：不推断。** 元数据的 PortionCode 来自 ASA24 当时的 FNDDS 版本，只有约 40% 的行能在 FNDDS 2019–2020 里精确找到。找不到的图不进入该编码的份量序列；同一张图的几行（不同 PortionCode）克重相差超过 1% 的也去掉。
  - 合格编码：在前 1000 个里、在 FNDDS 2019–2020 里，序列里每个份量文字只对应一个克重，且至少有 3 个不同克重，共 284 个，其中饮料类占 13%（全部 543 个候选编码为 10.5%）。试过更严的规则（每张图都要有克重、一个 PortionCode 覆盖整个序列），只剩 123 个编码、饮料占 30%，所以没有采用。
  - 每张图保留该编码最常见 PortionCode 的那一行，让原代码按 Multiplier 排序时尽量在同一尺度上。284 个编码中有 90 个的序列混有不同 PortionCode，`rag_portion_size.py` 仍照原代码按 Multiplier 排序，不改。
  - 大中小三档：在该编码的不同克重里取最大、中位（个数为偶数时取较小的中间值）、最小；同一克重有几张图时取文件名最小的。
  - 抽样：合格编码排序后用 `random.Random(20261027)` 打乱，前 50 个是测试集；之后的编码依次各取一张图（大、中、小轮流），图片与测试集重复的跳过，取满 10 张作开发集。
  - 测试集 150 行只有 117 张不同的图：ASA24 的一张图可以关联多个编码，例如同一杯液体的图同时用于牛奶、咖啡和茶。按论文"每个编码三张图"保留，每行单独评测。
  - df_results 不带 FC_Description，由 D1 按 FoodCodeCommon 从 df_image_link 补上。没有正确编码的行没有描述，原代码的 `analyze_portions` 会跳过它们。
  - 验收见 `tests/test_data.py` 的 TestB4，抽样可复现。

### B5 Nutrition5k 样本 — 状态：approved（审查节点一）
- **论文**：按食材列表去重后随机抽 1000 张（第 235–237 行）。
- **原代码**：`nutrition5k_proc.py` 负责去重（食材集合相同的只保留质量最大的一条）和检查图片是否可用，但图片 URL 的前缀被删掉了；随机抽样的代码缺失。
- **要做**：
  - 按用户决定随机抽 150 张（固定种子），另抽开发集 10 张，不重叠。
  - 下载这些菜的俯视 RGB 图（需要用户同意）。
  - 官方整盘营养全为 0、但重量大于 0 的记录，按缺失标签处理并登记。
- **验收**：测试集 150 行、开发集 10 行，图片哈希存档。
- **登记**：
  - 元数据（两个 dish_metadata CSV 和 `imagery/realsense_overhead/` 的对象清单）由 `place_inputs.py` 从之前审计时下载的副本复制，按 sha256 核对。
  - `nutrition5k_proc.py` 改了四处：
    - 读 CSV 时原来用 `on_bad_lines='skip'`，静默丢掉了食材比文件第一行多的 423 道菜（共 5,006 道）。论文是在全部去重后的菜里抽样（第 235–237 行），所以现在按最长的一行读入全部行。
    - `filter_unavailable_images` 原来的 URL 前缀被删掉了，补上官方存储地址；原来用 GET（会下载全部图片），改成 HEAD，8 个线程并发。去重后没有重设索引，原来的 `df.loc[i]` 会取错行或报 KeyError，现在先重设索引。HEAD 结果与对象清单逐一核对，不一致就报错。
    - 原来在模块顶层读 `metadata_sample.csv`，但从不使用，这个文件也不存在。现在删掉这一行，其余读文件移进 `main()`。
    - 新增缺失标签过滤、随机抽样和下载（原代码缺）。
  - 结果：去重后 2,435 道菜，2,035 道有俯拍 RGB 图；去掉 129 道"热量、脂肪、碳水、蛋白质全为 0 但重量大于 0"的菜（缺失标签，其中 128 道是 Cafe 2 的菜，另 1 道是空盘 "plate only"），剩 1,906 道，全部来自 Cafe 1。
  - 抽样框按原代码取两个餐厅（Cafe 1 和 Cafe 2），没有改用 `dish_ids_splits_rgb_*.txt`：这两个文件恰好是 Cafe 1 的全部 4,768 个编号。由于 Cafe 2 有图的菜都没有标签，两种做法的抽样框都是 Cafe 1 的这 1,906 道菜。
  - 抽样：排序后用 `random.Random(20261027)` 抽 160 道，前 150 道为测试集（`../dish_metadata.csv`），后 10 道为开发集（`../dish_metadata_dev.csv`）。只下载这 160 张图，共 64 MB；sha256 存在 `samples/nutrition5k_images.sha256`。
  - 验收见 `tests/test_data.py` 的 TestB5：两个 CSV 全部行都读入；抽样可复现；图片与哈希一致。

### B6 图片统一缩放到 256×256 — 状态：approved（审查节点一）
- **论文**：两个数据集的所有图片都统一为 256 × 256（第 237–240 行）。
- **原代码**：没有这一步，直接传图片 URL。
- **要做**：在本地缩放后以 data URL 传入，并写清缩放方式。
- **验收**：抽查图片尺寸。
- **登记**：
  - `chagApp_openai.image_url(link)`：本地图片在发送前缩放成 256×256，以 PNG data URL 传入；已经是 URL 的原样传。`Vision.chat` 的图片经过它，C2、C4 的两处也用它。磁盘上的图片不改。
  - 缩放方式：直接拉伸到 256×256（不保持长宽比，不裁剪、不补边），双三次插值。论文只说统一为 256×256、不做其他预处理，没说怎么缩放（第 237–240 行）。ASA24 原图 160×160 到 307×230 不等，Nutrition5k 俯拍图 640×480。
  - ASA24 的 PNG 是带透明背景的 RGBA，透明像素底下是白色。按作者直接传原图的做法保留透明通道，不合成到白底。颜色和透明度分开缩放：Pillow 整体缩放 RGBA 时会预乘 alpha，把透明像素底下的白色变成黑色。
  - 验收见 `tests/test_images.py`：输出是 256×256，ASA24 类图片仍是 RGBA 且透明像素底下仍为白色，`Vision.chat` 发出的是缩放后的图。

## C 流程（论文 Methods，第 140–189 行）

### C1 向量索引 — 状态：approved（审查节点一）
- **原代码**：`rag_food_code.setup_vector_database`（CSVLoader + Chroma）。
- **要做**：只改 embedding 接口（见 A2）；索引持久化，不要每次重建。调用 text-embedding-3-large 是付费操作，已在原则 5 的费用上限内获批。
- **验收**：索引里有 5,624 条。
- **登记**：
  - 索引存放在 `index/chroma`（git 忽略）。集合里已有全部 5,624 条时直接读取，不再调用 embedding；原代码 `Chroma.from_documents` 每次运行都在内存里重建（论文第 158–159 行：只建一次）。
  - 文档 id 用 CSV 行号，重试时只补缺的行；原代码的 id 是随机的，重试会重复加入。按 Chroma 的最大批量（5,461）分批加入。第一次实现时一次加入 5,624 条，被 Chroma 拒绝，而原代码的重试每次都会重新 embedding；失败三次、多用约 676K tokens（约 $0.09）后手动停下，改为分批。`from_documents` 本身是分批的。
  - 关闭 Chroma 的匿名遥测（`anonymized_telemetry=False`）。
  - tiktoken 0.6.0 第一次使用时下载了 cl100k_base（1.7 MB，sha256 `223921b7…b2a7`，与 tiktoken 内置的期望值一致），缓存在 `/tmp/data-gym-cache`。
  - 结果：5,624 条，成功的一次构建用了 7 次请求、225,444 tokens；连同失败的三次，embedding 共 901,776 tokens。再次运行时直接读取，没有 API 请求。
  - 测试：`tests/test_pipeline.py` 的 TestC1VectorIndex（建一次后复用、重试只补缺、分批）。

### C2 图片描述 — 状态：approved（审查节点一）
- **原代码**：`get_messages_from_url`（系统提示加用户提示，max_tokens 200），图片以 URL 传入。
- **要做**：改为传 B6 生成的 data URL，提示文字不改。
- **登记**：
  - `get_messages_from_url` 的图片改为 `{"url": image_url(link)}`：原来直接给字符串，现在的接口要求对象（第 1 轮"留给后续条目的事项"）。本地图片经 B6 缩放成 256×256 的 data URL。系统提示、问题文字和 max_tokens 200 不变。
  - `process_image_url` 原来对每个链接发 HEAD 请求检查能否访问；现在 http(s) 链接照旧，本地图片检查文件是否存在。文件不存在时照原逻辑记为失败（GPTFoodDescription 写 "Image URL is not accessible"，GPTFoodCode 为空）。
  - E1 之后按用户决定删掉了提示词最后一句拒答出路，见 E1 的"提示词适配"。
  - 测试：`tests/test_pipeline.py` 的 TestC2ImageDescription。

### C3 多查询检索 — 状态：approved（审查节点一）
- **论文**：GPT 把描述扩展成多条查询，逐条检索后去重（第 162–171 行）。
- **原代码**：MultiQueryRetriever 加 RETRIEVE_PROMPT（5 条改写加原描述）。
- **要做**：`food_code_chain` 把整个输入 dict 传给了 retriever，要核对检索器实际收到的是不是描述文本。记录每张图的候选列表。
- **登记**：
  - 核对结果：原来的 `{"context": retriever_from_llm, ...}` 把整个输入 dict 交给 retriever，生成查询的提示里 `{question}` 是这个 dict 的字符串，带着图片链接（data URL 时就是整张图的 base64）。按论文和 Supplementary Fig. 2（查询由描述 d 生成），现在用 `itemgetter("question")` 只传描述文本。RETRIEVE_PROMPT、MultiQueryRetriever 的设置（每条查询取 4 条、合并去重、不加原始描述）不变。
  - 链的输出改为 dict，`context` 是检索到的候选文档，`answer` 是选码回答。`process_image_url` 把候选编码按检索顺序写进 GPTCandidateCodes 列。
  - 原模板的 `{url_str}` 现在能拿到值（原来缺这个变量，链会报错）；C4 再把图片改为随消息发送。
  - 测试：`tests/test_pipeline.py` 的 TestC3Retrieval，用真实的 MultiQueryRetriever 加假模型，核对生成查询的提示只含描述、每条查询都检索、候选去重并记录。

### C4 选码要结合图片 — 状态：approved（审查节点一）
- **论文**：由 GPT_Vision_Model 结合图片分析候选编码，推断图中实际有哪些编码（第 173–178 行）。
- **原代码**：`setup_code_prompt_chain` 用的是文字模型 `llm`，图片只以 URL 文本出现在模板里，而且模板变量 `{url_str}` 没有传进去。
- **要做**：改为视觉模型，输入图片和候选上下文，保留原提示文字。输出可以有多个 8 位编码。补充材料 Supplementary Fig. 5 的选码提示词明确带图片。
- **验收**：离线测试确认请求里带了图片，候选来自 C3。
- **登记**：
  - 选码改用视觉模型 `MODELS['llm_vision']`，一条用户消息里放提示文字和图片（B6 的 256×256 data URL），与 Supplementary Fig. 5 一致。原代码用文字模型 `llm`，图片只以 `{url_str}` 文本出现在模板里。
  - 提示文字保留原代码的模板，只把 "the given food image: {url_str}," 改为 "the given food image,"，图片随消息发送。`{context}` 仍是候选文档列表的字符串形式，与原代码 ChatPromptTemplate 的格式化结果相同。
  - 这一步不设 max_tokens：原代码的文字模型没有设，描述步骤的 200 只属于描述步骤。`code_model()` 用同一个模型名、同一个记录日志的客户端和 temperature 0 新建一个 ChatOpenAI；pydantic 的 `copy()` 会丢掉 `callbacks` 等字段，不能用。
  - 测试：`tests/test_pipeline.py` 的 TestC4CodeSelection，核对模型收到的是一条带图片和全部候选的消息、请求发往视觉模型、没有 max_tokens、temperature 为 0。

### C5 ASA24 份量（论文协议） — 状态：approved（审查节点一）
- **论文**：份量从 FNDDS 标准描述中选，必要时按单位调整（第 179–186 行）。份量评测使用 ASA24 的真实份量编码（第 413–433 行）。
- **原代码**：`rag_portion_size.py` 有两种问法：
  - shot 模式：选项是 FoodCodeCommon 在 ASA24 图片序列里的全部份量（按 Multiplier 排序），描述用 FoodCodeCommon 的 FNDDS 描述。
  - amount 模式：问图里有多少个"真实份量的单位"。
- **要做**：保持原逻辑，补齐输入表。结果里要写明：这一步以识别正确为前提，选项来自真实编码的份量序列。Supplementary Fig. 5 的两个份量提示词与原代码两种模式一致；Supplementary Fig. 3（Algorithm 3）规定选项不合适时按单位调整；Supplementary Table 1 是各档份量示例。
- **验收**：开发集上跑通，输出 GPTPortionDescription 和 GPTPortionAmount。
- **登记**：
  - 两个提示词、选项（FoodCodeCommon 的份量序列，按 Multiplier 从大到小，用 " ," 连接）、单位（真实份量文字的单位，单数化）和 NFS/NS 替换都照原代码。属于论文协议的条件设定：选项来自真实编码的份量序列，amount 问的是真实份量的单位，只对 FoodCodeCommon 非空（识别正确）的图片提问。
  - 真实份量的数量：原代码 `float(Fraction(...))` 遇到 ASA24 的带分数（如 "1-1/2 cups"，占份量序列 15%）会抛 ValueError，整个 `process_dataframe` 中断。现在按"整数-分数"相加（`parse_amount`），不是数字时记为空。
  - `main` 原来读 `../ASA24_GPTFoodCodes_portion.csv`，这个文件是从 `output.csv` 手工得到的；现在直接用处理后的表，续跑时再读该文件。路径改为命令行参数，默认值是原路径。调用 D1 的 `add_food_code_common` 后再 `process_dataframe`。
  - `analyze_portions`：已有回答的行不再重问（续跑）；输出路径作为参数；写 CSV 不带索引（原来每次都多一列索引）。`workers` 默认 1，即原来的逐行、每次间隔 10 秒；大于 1 时并行提问，每行仍是独立的一次请求（协调会话补充第 6 点），不再间隔。
  - E1 之后按用户决定删掉了两个提示词最后一句拒答出路，见 E1 的"提示词适配"。
  - 测试：`tests/test_pipeline.py` 的 TestC5PortionProtocol（数量和单位、选项顺序、提示词内容、没有 FoodCodeCommon 的行不提问、续跑不重问、`main` 跑通）。

### C6 份量描述 → 份量编码 → 克重 — 状态：fixed（审查节点一 R-C6-1、R-C6-2）
- **原代码**：`nutrient_estimate.py` 用 FoodCodeCommon、PortionCode、PortionSubCode 查 FoodWeights；把 GPTPortionDescription 映射成 PortionCode/SubCode 的代码缺失。
- **要做**：在 df_image_link 里按同一编码的份量描述反查；查不到时记为失败，计入成功率。
- **验收**：离线测试覆盖精确匹配和查不到两种情况。
- **登记**：
  - `nutrient_estimate.map_portion`：在同一编码的份量序列（df_image_link）里按文字查模型选的份量，比较时忽略大小写、首尾空格和引号、末尾句号。查不到（回答不是选项之一）就记为失败：克重和营养为空，计入成功率。B4 保证一个编码的每个份量文字只对应一个克重。
  - 克重 = GPTMultiplier × FoodWeights 中 (FoodCodeCommon, GPTPortionCode) 的克重。原代码只查份量编码一个单位的克重，没有乘 Multiplier；按 ASA24 元数据，图片的量是 Multiplier 个 PortionCode（B4）。
  - PortionCode 98 是 ASA24 的"1 克"，FoodWeights 里没有这个编码。`get_portion_weight` 对 98 按 1 克计，与 B4 的参考克重一致（R-C6-1；原来是 NaN，份量序列里 9 个编码共 52 行受影响）。测试对真实份量序列的每一行核对：选中该行的份量，换算出的克重等于参考克重。
  - 原代码读 PortionCode、PortionSubCode。这两列在 df_results 里是参考标签（B4），所以预测的份量写进 GPTPortionCode、GPTPortionSubCode、GPTMultiplier，`nutrient_estimate` 改读这三列。
  - 第二种口径：论文说重量是"multiplying the estimated portion size by the corresponding weight (g) per portion"（第 252–253 行），也可以理解为 amount 回答的数量乘一个单位的克重。AmountWeight = amount 回答的数 × 该食物一个单位的克重，单位克重取份量序列中同一单位各选项"克重 ÷ 数量"的中位数。D2 两种口径都报。
  - 数量回答的解析（`parse_portion_amount`，R-C6-2）：回答必须是一个非负数，后面可以跟单位，允许小数、分数、带分数和千分位（"1,000" 读作 1000）。负数、数字前有文字、有第二个数、格式不对的千分位（"1,5"）、无穷大和拒答都记为失败；原来取第一个数字，"-2" 读成 2，"1,000" 读成 1，拒答句里的数字也会被读出。D3 的数量和 C8 的克数用同一个解析。
  - Supplementary Fig. 3 第 7–8 行（标准份量都不合适时按单位调整）：原代码对每张图两种问法都问，没有"不合适"的判断，所以 amount 不作为 shot 失败时的替补，只作为第二种口径单独报。
  - `nutrient_estimate.py` 原来在模块顶层直接运行，现在改为 `main()`，路径作为命令行参数，默认值是原路径。没有 FoodCodeCommon 的行直接跳过（原来每行都打印 "not found"）。
  - 测试：`tests/test_pipeline.py` 的 TestC6PortionToGrams（精确匹配、规范化后匹配、查不到、Multiplier 乘克重、amount 解析和单位克重）。

### C7 营养计算 — 状态：approved（审查节点一）
- **论文**：每项营养 = 每 100 g 含量 × 克重 / 100，多项求和（第 151–171 行右栏）。
- **原代码**：单项在 `nutrient_estimate.get_nutrition_values`；多项求和在 `nutrient_estimate_mix.py`。
- **要做**：核对 FNDDS Nutrient Values 表的列名和 sheet 名（skiprows=1）。
- **登记**：
  - 核对结果：sheet 名 "FNDDS Nutrient Values"、`skiprows=1` 正确，表头在第 2 行；前 4 列是编码、描述和 WWEIA 分类，`columns[4:]` 正好 65 种营养成分，与论文 l = 65 一致（第 151 行）；5,624 行，编码唯一。Table 1、2 用到的四列名是 `Energy (kcal)`、`Total Fat (g)`、`Carbohydrate (g)`、`Protein (g)`。
  - 公式 `每 100 g 含量 × 克重 × 0.01` 与论文一致，代码不改（C6 只把读文件移进 `main()`、函数改为显式传入表格）。多项求和见 C8。
  - 测试：`tests/test_pipeline.py` 的 TestC7Nutrients，读真实的 xlsx，用全脂牛奶 1 杯（244 g）手算核对四项。

### C8 Nutrition5k 多食物识别与克重 — 状态：approved（审查节点二 R-C8-2：节点一之后的克重加句、读全文和 ";;"；审查节点一的 R-C8-1 已 fixed）
- **论文**：识别所有食物、估份量、求和；提示词在 Supplementary Figs. 4–5。
- **原代码**：`nutrient_estimate_mix.py` 解析两列：
  - GPTFoodCode，格式为"食物: 编码, 编码; …"；同一食物有多个编码时，营养取平均。
  - GPTAmount，每行"食物: 克数"。
  
  产生这两列的提示词和调用脚本缺失。
- **要做**：补充材料里没有单独的 Nutrition5k 克重提示词。按 Supplementary Fig. 5 的第二个模板（how many {portion_unit} of the {food_description} are visible），以 grams 为单位为每种食物重建，并登记为"按论文模板重建"；参考 Supplementary Table 2（Nutrition5k 份量成功率：每道菜 84.2%，每个食物项 80.5%）。核对重量数字的解析：原来的 `re.search(r'\d+')` 会把 12.5 截成 12。
- **验收**：开发集跑通；解析测试覆盖小数。
- **登记**：
  - 选码（`rag_food_code.py --dataset nutrition5k`）：原代码没有混合菜的选码提示词，`nutrient_estimate_mix.match_food_codes` 按 "food: code, code; food: code" 解析。Nutrition5k 的选码提示把 "Please provide only the eight-digit codes without any extra information." 换成要求这种格式的一句，其余文字和 ASA24 相同（按论文模板重建）。回答若是每行一种食物，用 "; " 连成一行再存。后续轮次的跳过条件改为"至少一种食物有 8 位编码"（按下面的 `food_items`）：原条件看第 3–10 个字符，对以食物名开头的回答永远不成立，会每轮重问。
  - 食物列表的解析（`rag_portion_size.food_items`，R-C8-1）：克重提问的食物名、计数（IngredientNum、WeightError、FoodCodeError）、营养和 D6 的"有编码"用同一个解析。
    - 冒号结束食物名，名字从上一种食物的值之后开始，所以名字自带的分号保留（FNDDS 有 171 个名字带分号）。值是冒号后的完整编码列表，或到下一个分号为止的文字。
    - 值里没有 8 位编码的食物仍算一种食物，计为失败，不缩小分母。冒号后没有值的是引导语（如免责声明 "here are some possible matches:"），最后一个值之后的文字不是食物，同名食物合并。
    - 原来按 `'; '` 和 `': '` 切分：E1 的两条免责声明成了食物名，名字自带的分号把菜名切断；冒号后没空格的食物被丢掉，菜却仍算完整。克重回答现在按最后一个冒号切分，FNDDS 唯一带冒号的名字（Beef taco filling: …）也能对上。
    - ";;" 是空项，不算食物（用户 2026-10-27 决定按缺陷修）。选码回答的一行以分号结尾时，按行用 "; " 连接后成了 ";;"，多出的分号原来留在下一个名字里（`runs/dev-grams-estimate/` 的 "; spinach"），对不上克重回答里的 "spinach"。克重提问列出的食物名也随之改正。
  - 克重（`rag_portion_size.py --dataset nutrition5k`）：补充材料没有单独的 Nutrition5k 克重提示词。按 Supplementary Fig. 5 第二个模板（how many {portion_unit} of the {food_description} are visible），以 grams 为单位重建，登记为"按论文模板重建"。每道菜一次请求，列出选码回答里的全部食物名，要求每种食物一行 "food: 数值"，与 `parse_food_items` 读的格式一致。食物名来自模型自己的选码回答，不含参考标签。
  - `nutrient_estimate_mix.py`：
    - 克重解析由 `\d+` 改为 C6 的 `parse_portion_amount`，单位只能是 g、gram、grams 或不写。原来 12.5 会读成 12，"-20" 读成 20 g，"1,000" 读成 1 g（R-C6-2）。
    - 拒答原来只认 "I can't help to analyze this text."，现在也认 "...this image."（提示词里写的是 image）。
    - GPTFoodCode 或 GPTAmount 为空的菜原来会在 `split` 处抛错，现在记为没有估计（IngredientNum 为 0，或全部食物计入 WeightError）。
    - 某种食物有克重，但它的编码都不在 FNDDS 里：原来克重计入 GPTWeight、营养静默按 0 计，现在计入 FoodCodeError 并打印。
    - 路径作为命令行参数，默认值是原路径。同一食物多个编码时营养取平均、各食物求和，照原代码。
    - 克重回答读全文（用户 2026-10-27 决定，在加句后的开发集重跑之后）：
      - 原代码的 `parse_food_items` 只读第一段（`split('\n\n')[0]`）。gpt-4o-2024-08-06 常先写一段免责声明，空一行后才给出 "food: 克数"（`runs/dev-grams-estimate/` 的 7 道里有 2 道），原来这些估计值读不到。
      - 现在逐行读整个回答，跳过空行。读不出数字的行（如免责声明）对不上任何食物名，不影响结果；同名的后一行覆盖前一行，照原代码。
      - 只改克重回答的解析，其他步骤的解析不动，开发集上没有看到它们有损失。这是换模型后对原代码解析的适配，列入 E4。
  - E1 之后按用户决定删掉了克重提示词最后一句拒答出路（重建时照发布的份量提示词加上的），见 E1 的"提示词适配"。
  - 克重提示词末尾加了一句 "If you cannot determine the exact weight, still give your best estimate in grams."（用户 2026-10-27 决定），其他文字不动；描述、选码和 ASA24 的 shot、amount 提示词都没改。这是换模型后对提示词的适配：删句后的开发集重跑（`runs/dev-no-refusal-sentence/`）里，gpt-4o-2024-08-06 对 10 道菜中的 8 道回答 "I'm unable to determine the exact weight of the food from the image." 之类，按菜的份量成功率 0.2（论文 0.842）。这个提示词原代码里没有，是按 Supplementary Fig. 5 第二个模板重建的，模板里也没有这一句。没有在开发集上试别的写法。列入 E4。
  - 加句后的开发集重跑（`runs/dev-grams-estimate/`）：有编码的 7 道菜都问了克重，7 道都给出了数字，没有拒答。份量成功率按菜 4/7、按食物项 9/14；剩下的失败来自解析和一个被拆开的食物名，见 E1。
  - Supplementary Table 2 的成功率（每道菜 84.2%、每个食物项 80.5%）在 D6、D7 统计。
  - 测试：`tests/test_pipeline.py` 的 TestC8Nutrition5k（含 E1 的四条真实回答、冒号后没空格、丢项后的 D6/D7，以及 `runs/dev-grams-estimate/` 里免责声明段之后的克重回答和带 ";;" 的选码回答）；TestPublishedPrompts 与首个提交对照，确认描述、多查询、份量两种问法的提示词与发布版本一字不差，选码提示只有 C4 登记的改动。

### C9 失败重试 — 状态：fixed（审查节点一 R-C9-1）
- **原代码**：`rag_food_code.process_image_urls` 对失败的图片最多重试 5 轮。
- **要做**：保留这个逻辑，记录每张图的尝试次数；成功率按最终结果统计。
- **登记**：
  - 原代码的退避时间 `min(2 ** attempts * 30)`（`rag_food_code.py:165`，首个提交 `5946365` 里在 `:166`）对单个整数调用 `min`，会抛 TypeError，所以遇到 429 实际不会重试。这个 TypeError 落到外层 `except`，结果 CSV 的 GPTFoodDescription 写成 `'int' object is not iterable`，原来的限流错误也丢了。由第 1 轮复审指出（REVIEW.md R-A3-2 一节），在 C9 处理。
  - 修复：改为 `min(2 ** attempts * 30, 240)`，等待 30、60、120、240 秒，第 5 次仍是 429 时照原逻辑失败，结果里保留原来的 429 错误。240 是 5 次尝试内能达到的最大值，注释所说的"最大等待时间"。原代码只在描述步骤处理 429，没有扩大到其他步骤。
  - 5 轮重试保留：每轮跳过已有编码的图片，最后仍没有编码的记为失败，成功率按最终结果统计。新增 GPTAttempts 列，记录每张图被处理的轮数。
  - "已有编码"改为与 D1、D4、D6 相同的判断：回答里有前后不连数字的 8 位码（`parse_food_codes`，R-C9-1）。原代码看第 3–10 个字符能否转成整数：`['Food code: 63101000']` 评测算有编码，却会被重问，后面的失败会把它覆盖；`['631010001']` 没有合法编码，却被跳过，不再用剩下的轮次。这是对原代码解析错误的修复，重试轮数、请求和提示词不变。
  - 并发（协调会话补充第 6 点）：`process_image_urls` 加 `workers` 参数，默认 1，即原来的逐张处理。大于 1 时，同一轮里待处理的图片并行处理，每张图仍是自己独立的一组请求；表格和 CSV 的写入加锁，checkpoint 改为每轮结束时保存。
  - SDK 的自动重试次数由默认的 2 次改为 6 次（`api_log.MAX_RETRIES`）：遇到 429 或 5xx，SDK 按退避重发同一个请求，避免并发时把限流算成失败。重发不改变请求内容，每个响应（包括 429）都写进调用日志。
  - 测试：`tests/test_pipeline.py` 的 TestC9Retries（退避序列、轮数计数、跳过条件与评测一致、并行、SDK 重发并记录）。
  - 最多 5 轮与论文 "Each image was processed once per model"（第 304–305 行）之间有解释空间：没有编码时，即使请求成功也从描述起重做，不同于 SDK 对同一请求的重发。REPORT.md 偏差清单第 31 条登记为口径歧义（R-E4-2）。E2 的 GPTAttempts 合计 ASA24 309、Nutrition5k 295，用了不止一轮的分别有 54 张、53 道。

## D 评测（原代码基本缺失；论文 Evaluation metric，第 242–259 行，以及右栏第 198–228 行）

### D1 FoodCodeCommon — 状态：approved（审查节点一）
- **原代码**：`rag_portion_size.has_common_element`（求交集）定义了但没有调用；生成 FoodCodeCommon 的代码缺失。
- **论文**：食物识别的指标只统计识别成功的图片（第 385–388 行）。
- **要做**：FoodCodeCommon = 预测编码集合 ∩ 真实编码，并附上代码和论文依据来论证这个解读。
- **验收**：审查确认这个解读。
- **登记**：
  - 实现：`rag_portion_size.add_food_code_common`。预测编码是 GPTFoodCode 里所有前后不连数字的 8 位数（`parse_food_codes`），FoodCodeCommon = `has_common_element(预测编码, [真实编码])`，非空时就是真实编码，否则为空。同时按 FoodCodeCommon 从 df_image_link 补上 FC_Description（B4）。
  - 原代码的数据流：`process_dataframe` 用 FoodCodeCommon 取份量序列（`df_image_link['FoodCode'] == FoodCodeCommon`）；`analyze_portions` 只处理 FC_Description 不为空的行；`nutrient_estimate.py` 用 FoodCodeCommon 查克重和每 100 克营养。FoodCodeCommon 为空的行没有份量选项，克重为 NaN，不产生营养估计。同一文件里定义的 `has_common_element` 是求交集，名字也指"共同的编码"。
  - 论文原文：份量评测"on the ASA24 dataset, which includes ground truth portion size codes"（第 415–417 行），Table 5 的分类准确率要和真实份量比；Table 6 一段说 SR 和 MAE "calculated based on the same inferred food code and portion size as in Tables 1 and 2"（第 465–467、542 行）；Table 3 "focusing on images where food was successfully detected"（第 385–388 行）只说明 Table 3 的范围（第 1 轮审查意见）。
  - 结论：原代码只能对预测编码包含真实编码的图片算出营养，这时营养密度和份量序列都来自真实编码，MAE 只反映份量估计的误差。论文没有明说 Table 1 的 MAE 只统计这些图片，所以按协调会话第 7 点两种口径都报：D2 是原代码数据流下的条件口径（论文协议的条件设定），D3 是不用真实编码的端到端口径。
  - 测试：`tests/test_evaluation.py` 的 TestD1FoodCodeCommon。

### D2 ASA24 营养 MAE（论文协议） — 状态：approved（审查节点一）
- **论文**：报告 MAE per dish 和 per unit，覆盖重量和四项营养（Table 1）。
- **要做**：在 FoodCodeCommon 非空且份量有效的图片上计算，同时报告 n、成功率，并按三档拆分。
- **验收**：手算 3 张核对。
- **登记**：
  - 新文件 `code/evaluate.py`（原代码没有评测代码），`asa24_mae` 实现论文协议口径：只算 FoodCodeCommon 非空（D1）、份量能换成克数的图片。参考值 = 真实编码每 100 g 的营养 × 参考克重（B4）÷ 100；预测值是 FoodCodeCommon（也就是真实编码）的营养按预测克重算出的值，所以误差只来自份量。
  - MAE per dish 是平均绝对误差，per unit = MAE ÷ 同一批图片参考值的均值（Table 1、2 注释）。重量和四项营养分别按大、中、小三档和合计报告，附 n。
  - 两种克重口径都报（C6）：option 用选中的份量（原代码的数据流，主口径），amount 用 amount 回答的数量乘单位克重。成功率见 D6。
  - 测试：`tests/test_evaluation.py` 的 TestD2Asa24Mae，手算 3 张（另有 1 张没有共同编码、1 张回答不是选项，都不进入 option 口径）。

### D3 ASA24 端到端 MAE（我们补充） — 状态：approved（审查节点一）
- **要做**：不使用真实编码，取第一个预测编码，份量从该编码的 FNDDS 份量里选；失败也要计数。与 D2 并列报告。
- **2026-10-27 用户决定**：报告只写 Exact 数量和论文协议（D2）的 MAE，端到端在评测口径里一笔带过，数字只留在 `runs/test/metrics.json`。
- **登记**：
  - 推理（`rag_portion_size.py --end_to_end`）：编码取回答中第一个在 FNDDS 里的 8 位码；描述取该编码在 FNDDS 的 Main food description（NFS、NS 照原代码替换）；选项是该编码在 FoodWeights 里的标准份量（按 Seq Num 排序），去掉 "Quantity not specified" 和 "Guideline amount …"（前者是数量不明时的默认份量，后者是加进其他食物的用量，都不是看得见的份量）。先用原代码的 shot 提示词选份量，再用 amount 提示词问有几个所选份量的单位（"1 cup" 的单位是 "cup"，不以 "1 " 开头的份量用整段文字）。这一步不用任何参考标签，测试逐条检查了提示词。
  - 克重 = amount 回答的数量 × 所选 FNDDS 份量的克重（`nutrient_estimate.end_to_end_weight`）；营养用预测编码的每 100 g 含量。
  - 指标（`evaluate.asa24_end_to_end`）：参考值同 D2。没有编码、份量回答不是选项、数量读不出来的图片都算失败，计入成功率；MAE 只在有估计的图片上算，附 n。按三档和合计报告。
  - `analyze_portions` 增加一个条件：该行的选项或单位为空时不提问（论文协议那一步里这两项从不为空）。
  - 测试：`tests/test_evaluation.py` 的 TestD3EndToEnd（选项来自预测编码、提示词里没有参考标签、克重、成功率和 MAE 手算）。

### D4 编码匹配级别 — 状态：approved（审查节点一）
- **论文**：Exact（完全相同）、Close（前两位相同）、Far（首位相同）、Mismatch，按三档统计（第 200–211 行，Table 3）。
- **登记**：
  - `evaluate.asa24_match_levels`：分母是有预测编码的图片（Table 3 "images where food was successfully detected"，第 385–388 行），没有编码的图片计入 D6 的失败。按 Table 3 的数字（Far + Mismatch = 100%）采用累计口径：Close 包含 Exact，Far 包含 Close，Mismatch = 1 − Far。
  - 回答里有多个编码时，论文没说取哪个，两种都报：any 取所有预测编码中最好的级别（与 D1 的 FoodCodeCommon 一致，Exact 的比例就是有 FoodCodeCommon 的比例），first 只看第一个编码。按三档和合计报告。
  - 测试：`tests/test_evaluation.py` 的 TestD4MatchLevels。

### D5 份量分类准确率与单位误差 — 状态：approved（审查节点一）
- **论文**：Table 5，第 413–433 行。
- **登记**：
  - `evaluate.asa24_portions`：分母是被问了份量的图片（FoodCodeCommon 非空）。分类准确率 = 选中的选项就是真实份量文字（比较时忽略大小写、引号和末尾句号）；回答不是选项、没回答的都算错。
  - 预测误差：Table 5 的单位是"units"（0.72、0.31、0.16），方法部分却写"absolute difference (in grams)"（第 218–220 行），两种都报。单位误差 = |amount 回答的数量 − 真实数量|，只算读得出数量的图片；克数误差分别按 option 和 amount 两种克重口径算（C6）。附 n，按三档和合计报告。
  - 测试：`tests/test_evaluation.py` 的 TestD5Portions。

### D6 成功率 — 状态：approved（审查节点一）
- **论文**：只要产出了食物编码和份量就算成功，不论对错（第 224–228 行右栏）。
- **登记**：
  - ASA24（`evaluate.asa24_success_rates`，按三档和合计）：
    - 编码成功率：回答里有 8 位编码的图片 ÷ 全部图片（Supplementary Fig. 6a 的口径，"regardless of naming accuracy"，第 546–550 行）。5 轮重试后的最终结果。
    - 份量成功率：在被问了份量的图片（有 FoodCodeCommon）里，option 能换成克数的比例和 amount 回答读得出数量的比例。
    - 营养成功率：按论文协议得到营养估计（D2 的 option 口径）的图片 ÷ 全部图片。
  - Nutrition5k（`evaluate.nutrition5k_success_rates`，对应 Supplementary Table 2）：编码成功率按菜计；份量成功率按菜计时，分母是有编码的菜，分子是所有识别出的食物都有克数的菜；按食物项计时，是有克数的食物 ÷ 识别出的食物。
  - 失败不会算成成功：没有编码、回答不是选项、读不出数字、API 出错都留空，统计时计入失败。
  - 测试：`tests/test_evaluation.py` 的 TestD6SuccessRates。

### D7 Nutrition5k 营养 MAE — 状态：fixed（审查节点一 R-D7-1）
- **论文**：MAE per dish 和 per unit（Table 2）。缺失标签的处理规则见 B5。
- **登记**：
  - `evaluate.nutrition5k_mae`：主口径只算完整的菜，即有编码、每种识别出的食物都有克数、每种食物都有 FNDDS 编码（D6 按菜计的成功）；另报"所有有估计的菜"，包括只算了部分食物的菜。参考值是官方整盘的 total_mass、total_calories、total_fat、total_carbs、total_protein；缺失标签的菜在 B5 已排除。per unit 的算法同 D2。
  - "有估计"指至少一种食物给出了克数（R-D7-1）。`nutrient_estimate_mix.calculate_dish_nutrition` 原来从 0 开始累加克数，所有食物都没有克数（none、回答读不出、编码回答解析不出食物）的菜也得到 0 g，被算进"所有有估计的菜"；现在这种菜的 GPTWeight 为空。模型明确回答的 0 g 仍是估计。
  - `evaluate.py` 的 `main` 把一次运行的全部指标写成 `metrics.json`（NaN 写成 null）和 `metrics.md`，表里并列 Table 1、2 的 DietAI24 数值供对照。
  - 测试：`tests/test_evaluation.py` 的 TestD7Nutrition5kMae、TestNoWeightIsNoEstimate（全部 none、读不出的回答、部分有效、明确的 0 g）。

### D8 防泄漏检查 — 状态：approved（审查节点一）
- **要做**：推理调用的输入只能有图片和检索结果（C5、D1 的例外已登记）。用离线测试检查请求内容。
- **登记**：
  - `tests/test_leakage.py`：在一个离线的小世界里（2 张 ASA24、2 道 Nutrition5k，API 和分词器都用 mock，临时索引）用 `run_experiment.run` 跑完整条管线，记录每个请求，按提示词判断是哪一步。
  - 检查内容：
    - 任何请求的文字里都没有参考克重、Nutrition5k 的整盘标签和真实食材、图片文件名和图片目录；
    - ASA24 元数据里的描述和真实份量文字只出现在论文协议的份量请求里（C5、D1 的例外），而且只出现在回答包含真实编码的那张图上；
    - 描述和生成查询两步的请求里没有任何食物编码，选码请求里的编码只出现在检索到的 FNDDS 行（context）里；
    - 每张图都以 256×256 发送；
    - 指标、费用和 config 文件正确，运行目录里没有 key。
  - 选码请求的 context 照原代码是文档列表的字符串，其中 metadata 带 FNDDS 表的路径和行号，不是标签。

## E 实验与报告

### E1 开发集试跑 — 状态：fixed（审查节点二：R-E1-4 approved，R-E1-5 登记为已知局限、没有改代码；审查节点一的 R-E1-1、R-E1-2、R-E1-3 已 fixed，提示词按用户决定 (b) 删句）
- **要做**：ASA24 10 张（编码不在测试集里）加 Nutrition5k 10 张，检查整条管线和费用。
- **登记**：
  - 新脚本 `code/run_experiment.py --split dev|test --workers N`：依次调用各脚本自己的 `main()`，顺序是两个数据集的选码、ASA24 论文协议份量（C5）、ASA24 端到端份量（D3）、Nutrition5k 克重（C8）、克重和营养（C6、C7、C8）、指标（D2–D7）。这次运行的表都在 `runs/<split>/`，中断后重跑会跳过已完成的部分。`nutrient_estimate_mix.py` 的 `__main__` 移进 `main(args)`，加 `--output_path`。
  - 费用：每个 API 响应都是 `logs/openai_api.jsonl` 的一行。每一步新增的行就是它的用量，复制到 `runs/<split>/openai_api.jsonl`；`cost.json` 按单价算出每一步、整次运行和每张图的费用。单价（美元/百万 tokens，OpenAI 价格页 developers.openai.com/api/docs/pricing，2026-10-27 查得 gpt-4o 标准档）：gpt-4o-2024-08-06 输入 2.50、缓存输入 1.25、输出 10.00；text-embedding-3-large 0.13。日志里出现没有单价的模型时直接报错，不会按 0 计。
  - 图片数按 CSV 解析后的记录数计，并核对抽样表、选码表和营养表的行数一致，不一致就报错（R-E1-2）。原来按文件行数减一，描述带换行时一条记录占多行，图片数和每张图的费用都会算错。
  - `config.json` 记录模型名（请求的和实际提供服务的）、temperature、图片尺寸、并发数、起止时间、提交号和工作区是否有未提交改动。提交号和工作区状态在运行开始时记录（E1 之后的小改动；E1 运行期间工作区没有改动，记录的 `8f81d2e` 就是运行所用的代码）。
  - 续跑和中断（R-E1-1）：一个目录只放一次运行。`config.json` 记下这次运行的推理配置：数据划分、模型、temperature、图片尺寸，以及构造请求的代码（`rag_food_code.py`、`rag_portion_size.py`、`chagApp_openai.py`、`config.py`、`api_log.py`）和输入表的 sha256；配置不同，或是旧驱动留下的目录（如 `runs/dev/`），就报错，要求换新目录。每次调用开始时先记下开始时间、提交号、并发数，每一步开始和结束时记下它在 `logs/openai_api.jsonl` 里的行号；每步结束（包括出错）后把这一步的响应加上步骤名和调用序号追加到运行目录的 `openai_api.jsonl`，再重写 `cost.json`、`config.json`。费用和实际服务的模型按整个目录的全部响应累计，失败或 Ctrl-C 记为 `failed: <异常类型>`。原来每次调用只汇总自己新增的响应却覆盖这两个文件，无新请求的续跑会把费用写成 $0、模型写成空，中途出错时运行目录里没有这一次的任何记录。
  - **结果**（`runs/dev/`，代码 `8f81d2e`，4 个线程，2026-10-27 04:26–04:28 UTC）：173 次请求，$0.144，实际服务的模型是 gpt-4o-2024-08-06 和 text-embedding-3-large，没有 429 或其他错误。管线各步都跑通了，但 **gpt-4o 大量拒答**，没有一张图得到营养估计，所有 MAE 的 n 都是 0：
    - ASA24：10 张中 9 张的描述步骤 5 轮都回答 "I can't help to analyze this image."，理由如 "The image is too small to accurately identify the food"、"I can't identify the food based on the given image"。编码成功率 1/10（42110110，真实 42110100，Close）。没有图片得到 FoodCodeCommon，所以论文协议的份量步骤没有发出请求；唯一有编码的那张，端到端份量也被拒（"I can't determine the portion size from the image alone"）。
    - Nutrition5k：编码成功率 6/10，另 4 道 5 轮都被拒（"I can't view or interpret images directly"）。6 道有编码的菜，克重请求全部被拒（"I cannot accurately determine the weight of food from an image"），按菜、按食物项的份量成功率都是 0。另有 2 道菜的选码回答带免责声明（"I'm unable to identify specific foods or their codes from images. However, ... here are some possible matches:"），声明句被当成了食物名。
  - **诊断**（开发集的 3 张图，只测描述这一步，脚本和回答在 `runs/dev/diagnostics/`，17 次请求、$0.020，没有采用任何改动；R-E1-3 按记录改正）：
    - 描述提示词不变，换图片形式（`answers.jsonl` 第 1–11 行）：
      - 120710108（ASA24）在白底、原尺寸 160×160、放大到 512 下都拒答。
      - 113032（ASA24）在白底下答 "vanilla ice cream"；原尺寸下答 "mashed potatoes"，有回答但认错了；放大到 512 仍拒答。
      - Nutrition5k 那道菜在原尺寸 640×480 和 512 下都拒答。
      - prompt tokens 在 256 和 512 下是 390，Nutrition5k 原尺寸是 560，说明请求带着图。
    - 去掉描述提示词的最后一句 "If you can't provide assistance with this image, simply respond with 'I can't help to analyze this image.' and provide the reason on a new line."（第 12、14、16 行），三张都给出了描述，但不都对（对照参考标签）：
      - 113032 答 vanilla ice cream，参考是 Light ice cream，相符；
      - Nutrition5k 那道菜说出了胡萝卜、肉和菠菜，漏了米饭和藜麦；
      - 120710108 答成炒蛋配蔬菜，参考是 Chicken or turkey pot pie，认错了。
    - 保留这句、设 `detail: high`（第 13、15、17 行），三张仍拒答。
    - 结论只限于这三张图的描述步骤：去掉这句后描述有了回答，换图片形式没有稳定的效果。删句后的选码、shot、amount、克重和营养都没有测过，能不能产出估计、准不准，要看开发集重跑。E1 里论文协议的份量分支没有发出过真实请求，还没有付费实测。论文的 GPT-4 Turbo 用同样的提示词，在 ASA24 上的编码成功率是 84–93%（Supplementary Fig. 6）。描述、shot、amount 三个发布的提示词和按模板重建的 Nutrition5k 克重提示词都有这一句；选码提示词没有。
  - 费用：ASA24 每张 $0.0061，Nutrition5k 每道 $0.0083（拒答后后续步骤不再发请求，所以这个单价偏低）。到目前为止共花 $0.281：建索引 $0.117（含 C1 失败的三次），E1 $0.144，诊断 $0.020。
  - **E2 之前需要用户决定**（E1 时写）：按原样保留发布的提示词（忠于原代码，但按 E1，ASA24 几乎没有可算 MAE 的图），还是登记为模型替换造成的偏差、去掉这一句拒答出路（只改这一句，先在开发集上重跑 E1 确认），或者换模型。
  - **提示词适配（用户 2026-10-27 选 (b)）**：
    - 描述、shot、amount 三个发布的提示词和按模板重建的 Nutrition5k 克重提示词，删掉最后一句拒答出路，连同它前面的空白；其余文字不动。D3 的端到端份量用的是同样的 shot、amount 提示词。删掉的句子：
      - 描述："If you can't provide assistance with this image, simply respond with 'I can't help to analyze this image.' and provide the reason on a new line."
      - 份量和克重："If you cannot analyze the image, reply with "I can't help to analyze this image." and specify the reason on a new line."
    - 登记为模型替换背景下的提示词适配。Supplementary Figs. 4–5 的模板里没有这一句，只有首个提交的 `rag_food_code.get_messages_from_url`、`rag_portion_size.create_prompt` 有，所以有论文模板层面的依据；但按原则 1，这是对发布代码的有意偏离，列入 E4。
    - 代码里认这句原话的判断（`process_image_url`、`update_dataframe`、`parse_food_items`）保留。模型换个说法拒答时，描述照原代码流向检索和选码；份量和克重的回答不是选项、读不出数字，计为失败。
    - 没有在开发集上试别的改法。E1 的失败基线 `runs/dev/` 保留不动，删句后的重跑用新目录。
  - **删句后的开发集重跑**（`runs/dev-no-refusal-sentence/`，代码 `8176379`，工作区无改动，4 个线程，2026-10-27 05:35–05:38 UTC）：423 次请求，$0.256，全部 200，temperature 0，实际服务的模型是 gpt-4o-2024-08-06 和 text-embedding-3-large。
    - ASA24（10 张）：
      - 描述 10/10 有回答，都是一轮完成；选码 10/10 有编码（E1 是 1/10）。按累计口径，Exact 1/10、Close 5/10、Far 7/10，any 和 first 相同。有 2 条选码回答开头是免责声明，但仍给出了编码。
      - 论文协议份量：只有 1 张有 FoodCodeCommon（番茄酱 74404010）。shot 选 "1/2 cup"（真实 "1 cup"），option 克重 130 g（参考 260 g）；amount 答 1，克重 260 g。n = 1。
      - 端到端：9/10 有克重。另 1 张的 shot 回答 "The portion size is less than 1 cup." 不是选项，计为失败。重量 MAE 109 g（per unit 0.56），热量 182 kcal（0.49），n = 9。
    - Nutrition5k（10 道）：
      - 描述 10/10，选码按菜 10/10（E1 是 6/10），其中 4 道用了 2–4 轮。共 17 种食物，其中 apple 没有编码；3 条选码回答带免责声明，按 R-C8-1 解析正确。
      - 克重：10 道都问了，8 道回答 "I'm unable to determine the exact weight of the food from the image." 之类，是换了说法的拒答，计为失败。份量成功率按菜 0.2（论文 0.842），按食物项 4/17 = 0.24（论文 0.805）。
      - MAE：完整的菜 n = 1（重量误差 26 g），所有有估计的菜 n = 2。
    - 观察（没有改）：生成的查询之间有空行，MultiQueryRetriever 把空字符串也当成一条查询（`process_images.log` 的 Generated queries）。所以每张图的候选第 5–8 个都是同样的 4 个编码（93502100、11000000、14102010、14410620），正好是第二条查询（空串）的检索结果。这是原代码在 langchain 0.1.9 下的行为（C3），列入 E4。
    - 费用：ASA24 每张 $0.0091，Nutrition5k 每道 $0.0166。到目前为止共花 $0.538：建索引 $0.117、E1 $0.144、诊断 $0.020、重跑 $0.256。按这个单价估 E2（150 + 150）约 $3.9，加上已花的约 $4.4，在 $20 上限内。
    - 结论：删句后，描述和选码不再拒答，ASA24 端到端能产出估计；但 Nutrition5k 克重仍大面积拒答，ASA24 论文协议份量因为 Exact 只有 1/10，只有 1 张图进入。按协调会话的要求停在这里，不再改提示词或换模型，等协调会话确认后再跑 E2。
  - **克重提示词加句后的开发集重跑**（用户 2026-10-27 决定，见 C8；代码 `3947390`，配置与 E2 相同，4 个线程）：
    - 第一次（2026-10-27 05:48–05:51 UTC）跑到 Nutrition5k 选码的第 4 轮时，进程随上一个实现会话结束被信号终止，`finally` 没有执行。因此 `config.json` 里这次调用仍是 `running`；这一步的 278 个响应（`api_log_lines` 从 848 起，即 `logs/openai_api.jsonl` 第 849–1126 行）没有复制进运行目录。整次共 488 次请求、$0.286（第 639–1126 行），全部 200。
    - 这个目录改名为 `runs/dev-grams-estimate-killed/`，原样保留，没有续跑。终止时第 4 轮已为第 7、9、10 道菜（行 6、8、9）发出请求，但还没记进 `GPTAttempts`；续跑会让它们多试一轮，超过 5 轮的协议。
    - 已知局限（R-E1-5，没有改代码）：
      - `run_experiment.py` 靠 `finally` 记账，进程被信号终止时不保证执行。
      - 之后不再有新的运行，所以没有加终止信号的处理和恢复前的对账，只在 REPORT.md 第 5 节登记。
      - E2 没有中断，账目完整。
    - 第二次（`runs/dev-grams-estimate/`，2026-10-27 05:58–06:02 UTC）从头跑完。记录的提交是 `623cffd`，比 `3947390` 只多了上面这条登记和被终止那次的记录，构造请求的代码 sha256 相同，工作区无改动。共 546 次请求、$0.329，全部 200，temperature 0，实际服务的模型是 gpt-4o-2024-08-06 和 text-embedding-3-large。
    - ASA24（10 张）：提示词没改，结果与删句后的重跑几乎相同。
      - 描述、选码 10/10，都是一轮完成。按累计口径，Exact 1/10、Close 5/10、Far 7/10。
      - 论文协议份量仍只有 1 张（番茄酱）：shot 选 "1/2 cup"，option 克重 130 g（参考 260 g）；amount 读数 260 g。n = 1。
      - 端到端 9/10 有克重，另 1 张的 shot 仍答 "The portion size is less than 1 cup."。重量 MAE 110 g（per unit 0.56），热量 183 kcal（0.50），n = 9。
    - Nutrition5k（10 道）：
      - 描述 10/10。选码按菜 7/10；删句后的重跑是 10/10，选码的代码和提示词都没变。
        - 3 道 5 轮都没有编码：dish_1559590130 和 dish_1560456348 回答 "No appropriate food codes found from the context information."；dish_1562963059 回答 "I'm unable to identify or describe the contents of the image. Please provide a description of the food items shown, ..."。
        - 另有 2 道分别在第 2、第 5 轮才有编码。
        - temperature 0 下回答仍有变化：被终止的那次里，也有 3 道菜前 3 轮都没有编码。
      - 克重：有编码的 7 道都问了，7 道都给出了数字，没有不带数字的拒答（删句后的重跑是 10 道中 8 道拒答）。其中 2 道先写一段 "I'm unable to determine the exact weight..., but I can provide an estimate:"，空一行后才给出 "food: grams"。
      - 份量成功率按菜 4/7 = 0.571（论文 0.842），按食物项 9/14 = 0.643（论文 0.805）。没读到克重的 5 项：
        - dish_1563307575 和 dish_1562184628 共 4 项：估计值写在免责声明那段之后，而 `parse_food_items` 只读第一段（`split('\n\n')[0]`，首个提交原样）。
        - dish_1563307575 的 spinach 另有一个问题。选码回答的第一行以分号结尾，按行用 "; " 连接后成了 ";;"，`food_items` 把多出的分号留在下一个名字里（"; spinach"），对不上克重回答里的 "spinach"。这是 R-C8-1 `food_items` 的缺陷，没有改。
        - dish_1563391989 的 1 项：选码回答只有一种食物 "Chicken or turkey, rice, and vegetables"（FNDDS 的混合菜名），克重回答拆成 Chicken or turkey、Rice、Vegetables 三种，名字对不上。
      - 离线重算，只作诊断，没有采用（`diagnostics/grams_counterfactual.py`，不发请求）：读整段回答时，按菜 5/7、按食物项 12/14；再去掉 ";;" 的问题，是 6/7、13/14。
      - MAE：
        - 完整的菜 n = 3：重量 103 g（per unit 0.48）、热量 103 kcal（0.43）、脂肪 1.97 g（0.20）、碳水 21.3 g（1.02）、蛋白质 7.47 g（0.41）。
        - 所有有估计的菜 n = 4：重量 120 g（0.45）、热量 147 kcal（0.47）。
    - 费用：
      - ASA24 每张 $0.0093，Nutrition5k 每道 $0.0236。Nutrition5k 选码的重试最贵：378 次请求，$0.227。
      - 累计 $1.153，共 1672 次响应，全部 200：建索引 $0.117、E1 $0.144、诊断 $0.020、删句后的重跑 $0.256、被终止的一次 $0.286、这次 $0.329。
      - 按这次的单价估 E2（150 + 150）约 $4.9，按删句后重跑的单价约 $3.9。加上已花的约 $6.1，在 $20 上限内。
    - 结论：
      - 加句后克重不再拒答，问到的 7 道菜都给出了数字。
      - 按原代码的解析，份量成功率按菜 0.571、按食物项 0.643，仍低于论文。剩下的失败来自解析（只读第一段，以及 ";;"）和一个被拆开的食物名，不是拒答。
      - Nutrition5k 选码这次只有 7/10。
      - 按协调会话的要求停在这里，没有再改提示词，也没有改代码。等协调会话决定后再跑 E2。
  - **修两处解析后对这次回答的离线重算**（用户 2026-10-27 决定；`d9419aa` 克重回答读全文，`1a7195f` 修 ";;"）：
    - 用 `runs/dev-grams-estimate/` 保存的回答重算克重、营养和指标，断网运行，不发请求（全局日志仍是 1672 行），原始结果的校验和不变。脚本是 `diagnostics/recompute.py`，输出和改动清单（`changes.txt`）在 `diagnostics/recompute/`。
    - 克重成功率按菜 6/7 = 0.857（原 4/7），按食物项 13/14 = 0.929（原 9/14），与诊断时的估算一致。剩下的 1 项是被拆开的混合菜名（dish_1563391989），只登记，不改。
    - 只有 dish_1563307575、dish_1562184628 两道菜变了：克重 200 g（参考 419 g）、120 g（参考 121 g），营养随之算出。ASA24 的营养表和指标完全不变；Nutrition5k 选码 7/10、食物项数 14 不变。
    - Nutrition5k MAE：
      - 完整的菜 n = 5：重量 106 g（per unit 0.45）、热量 172 kcal（0.47）、脂肪 8.03 g（0.40）、碳水 17.9 g（1.01）、蛋白质 14.0 g（0.49）。
      - 所有有估计的菜 n = 6：重量 116 g（0.44）、热量 190 kcal（0.48）。
    - 协调会话给的三条都符合：离线测试 103 项通过；按菜 6/7、按食物项 13/14；其他指标没有意外变化。接着跑 E2。

### E2 正式运行 — 状态：fixed（审查节点二 R-E2-2；R-E2-1 approved）
- **要做**：ASA24 150 张加 Nutrition5k 150 张一次跑完，配置固定，日志去掉 key，记录 token 用量。论文 Supplementary Table 3 估计每张图约 0.1 美元，可作为费用参照。
- **登记**：
  - 运行：`code/run_experiment.py --split test --run_dir ../runs/test --workers 4`，2026-10-27 06:20:44–07:01:42 UTC，一次调用跑完。`config.json` 只有一条调用记录，状态 completed。代码 `ea3c08b`，工作区无改动。进程用 setsid 和 nohup 放在会话之外运行，因为开发集那次随会话结束被终止过。
  - 运行前核对：
    - 测试表里的模型答案列全为空；150 + 150 张图片都在。
    - 与开发集的编码、图片和菜都不重叠。
    - 累计 $1.153 加估算 $4.9 不超过 $20。
  - 8,867 次请求，全部 200，与全局日志第 1673–10539 行逐条相同。请求和实际服务的模型都是 gpt-4o-2024-08-06 和 text-embedding-3-large，temperature 0，`runs/test/` 里没有 `sk-` 长串。
    - 运行期间跑过一项离线测试（TestE3Tables）。它的 API 和日志路径都指向临时目录，E2 的账里没有混入它的记录。
  - 费用 $5.285：
    - ASA24 选码 $2.306（4,326 次）、Nutrition5k 选码 $2.553（4,135 次）；
    - ASA24 论文协议份量 $0.042（42 次）、端到端份量 $0.226（236 次）、Nutrition5k 克重 $0.159（128 次）。
    - 每张图 ASA24 $0.0172、Nutrition5k $0.0181。估算的 $4.9 偏低，主要因为 ASA24 选码的重试比开发集多：25 张 5 轮都没有编码。
    - 累计 $6.438（10,539 次响应）。
  - 结果概要（详见 REPORT.md 第 2、3 节）：
    - ASA24：选码 83.3%；论文协议 n = 21，重量 MAE 92.7 g；端到端 74.7%，n = 112。
    - Nutrition5k：选码 85.3%；份量成功率按菜 73.4%、按食物项 83.3%；完整的菜 n = 86，重量 MAE 95.0 g。
  - 离线诊断（不发请求）：`runs/test/diagnostics/bootstrap.py` 给出主要口径 MAE 的 95% bootstrap 区间。
  - 区间的重抽单位（R-E2-2）：
    - 原来对有估计的行逐行独立重抽，破坏了"每个编码三档"的成组结构。论文协议的 21 行只来自 10 个编码，端到端的 112 行来自 47 个编码、89 张图。
    - ASA24 现在按编码成组：每次有放回地抽 50 个编码，保留各自三档，失败的行也保留；MAE = 有估计的行的误差总和 ÷ 有估计的行数。Nutrition5k 仍按菜重抽，每个口径单独设生成器，数值随随机数流略有变化。
    - 结果：option 重量 37–153 g、热量 46.1–146 kcal，包含论文值；端到端热量 137–797 kcal；Nutrition5k 重量 80.1–111 g。
    - REPORT.md 2.4 写明三点：这是条件成功子集上的区间；有重复图片，区间可能偏窄；区间描述的是从 284 个编码的抽样框里抽样，以本次回答为准。概要、3.5 和第 5 节依赖区间的说法也按新区间改写。

### E3 与论文的对照表 — 状态：fixed（审查节点二 R-E3-2；R-E3-1 approved）
- **要做**：列出 per dish、per unit、n、成功率，注明模型替代和样本量。
- **登记**：
  - 对照表在 REPORT.md 第 3 节，由新脚本 `code/report_tables.py runs/test/metrics.json` 从 E2 的 `metrics.json` 生成，共四张表：
    - 营养 MAE（Table 1、2）；
    - 成功率（Supplementary Fig. 6a、Supplementary Table 2）；
    - 编码匹配级别（Table 3，取 GPT-4 Turbo 那几行）；
    - 份量（Table 5）。
  - 论文数值的出处：Table 3、Table 5 见 paper.txt 第 364–380、443–447 行；Supplementary Table 2 来自补充材料；Supplementary Fig. 6a 只有图，取正文和图上的 84–93%。每张表都注明 n，模型替代和样本量写在第 3 节开头。
  - 第 2 节是 E2 的结果和失败分类（`runs/test/diagnostics/failures.py`，离线）；2.4 是主要 MAE 的 bootstrap 区间（E2 的诊断）。
  - 测试：`tests/test_run_experiment.py` 的 TestE3Tables，在 D8 的离线小世界跑一遍，核对表的行数、数值和论文值。
  - 失败分类的改正（R-E3-2）：
    - dish_1561574479 的克重回答整段拒答，没有数字。原来的分类没有"整段拒答"这一类，把它算成了改名，REPORT.md 因此写了"128 道都给出了数字"。
    - 分类移到 `code/failure_causes.py`，增加这一类。38 种 = 20 种组合名被拆开 + 14 种其他改名或拆合 + 3 种 "Not visible" + 1 种整段拒答。
    - `failures.txt` 列出每一类对应的菜。`tests/test_failure_causes.py` 用这条真实记录做回归检查，并在 E2 的表上核对：各类的数目对得上，每道菜的失败数等于它的 WeightError。
    - 主指标和成功率本来就把它计为失败，不受影响。

### E4 偏差清单 — 状态：fixed（审查节点二 R-E4-1、R-E4-2）
- **要做**：逐条列出与论文或原代码的差异（A3、A4、B4 的映射规则、B6、C4、C8 等）。
- **登记**（陆续补充）：
  - C8 克重提示词加了一句要求给出估计值（用户 2026-10-27 决定）："If you cannot determine the exact weight, still give your best estimate in grams."。起因是 gpt-4o-2024-08-06 对克重问题大面积拒答，依据是删句后开发集重跑的记录（`runs/dev-no-refusal-sentence/`，8/10 道菜拒答）。属于换模型后对提示词的适配，论文模板和原代码里都没有这一句。加句后的开发集重跑（`runs/dev-grams-estimate/`）里，问到克重的 7 道菜都给出了数字，见 E1。
  - C8 克重回答的解析读全文（用户 2026-10-27 决定）。原代码 `parse_food_items` 只读第一段（`split('\n\n')[0]`），而 gpt-4o-2024-08-06 常先写一段免责声明，空一行后才给出数字；依据是加句后开发集重跑的记录（`runs/dev-grams-estimate/`，7 道里有 2 道）。属于换模型后对原代码解析的适配：只改克重回答，其他步骤的解析不动。
  - 完整的清单在 REPORT.md 第 4 节，按性质分 7 组共 31 条，每条注明对应的条目：
    - 模型和接口不可用，替换；
    - 原代码与论文冲突，按论文处理；
    - 原代码缺失，按论文重建；
    - 缺陷的修复：原代码的缺陷、R-C8-1 对食物列表解析的整体改写（第 22 条，R-E4-1 补列），以及我们自己的 ";;" 缺陷；
    - 换模型后的提示词和解析适配（用户决定，依据都是开发集记录）；
    - 样本与范围；
    - 观察到、没有改的原代码行为：空查询；被拆开的组合食物名；"正式运行一次"与"每张图最多五轮"的口径歧义（第 31 条，R-E4-2）。
  - 上面两条是清单的第 25、26 条，第 24 条是删去拒答出路（E1）。

### E5（可选）GPT Vision 直接估计基线 — 状态：不做（用户 2026-10-27 决定）
- **要做**：用 `baseline_chatGPT.py`，只问五项。

## F 模型对照（2026-10-27，HANDOFF_CODEX.md 第 5 节）

本组沿用已批准的 $20 累计费用上限，不下载数据。开发集、测试集、索引、embedding、提示词、解析和 `evaluate.py` 均冻结为 E2 版本。每种配置正式测试仅一次；先开发集、独立审查节点一、处理 P1/P2，再正式测试；报告定稿前独立审查节点二，均只审一次。

### F1 可选模型和 temperature — 状态：approved（模型对照节点一 R-F1-1）
- **依据**：paper.txt:303–305 的模型及 temperature 0；HANDOFF 5.1–5.4 要求隔离模型因素。
- **实现**：`run_experiment.py --model gpt-6.1-sol` 同时切换文字、视觉模型；默认仍为 `gpt-4o-2024-08-06`，embedding 不变。三个 LangChain 客户端与 Vision 均按请求模型选择 temperature。
- **偏差**：Sol 不支持 temperature 0，发送支持的默认值 1；baseline 仍发送 0。这是模型与采样设置的联合对照，一次回答只是一次抽样，不能把差别严格归因于模型能力。
- **验收**：离线 mock 检查描述、多查询、选码、份量实际请求中的模型、temperature 和相同消息；配置记录实际 temperature。原 107 项基线测试通过。

### F2 单价、推理 token 和费用 — 状态：approved（模型对照节点一 R-F2-1）
- **依据**：paper.txt:518–527 的费用讨论；HANDOFF 5.4，查官方单价并在开发集实测后估算测试费用。
- **单价**：2026-10-27 查 [官方价格](https://developers.openai.com/api/docs/pricing)、[Sol 模型页](https://developers.openai.com/api/docs/models/gpt-6.1-sol)，standard、输入不超过 272K：输入 $2、缓存输入 $0.10、输出 $10／百万 token。未配置长上下文价格时显式报错。
- **统计**：completion_tokens 已包含 reasoning_tokens；仅另列推理 token，不重复收费。保存价格来源、日期及运行所用单价。离线手算覆盖缓存折扣和推理 token。
- **账目基线**：全局日志 10,539 条，只有 gpt-4o 和 embedding 的成功响应；新调用前重算累计 $6.43753024，剩余 $13.56246976。`.env` 与现有索引均存在，未读取或输出 key。

### F3 token 参数兼容与开发集试跑 — 状态：fixed（模型对照节点一 R-F3-1；R-F3-2 approved）
- **依据**：paper.txt:303–305 的同一推理流程，原代码描述 200、份量 600 token 上限；HANDOFF 5.2、5.4–5.5，先测兼容性，再登记必要偏差。
- **单图探测**：仅用 ASA24 开发集第 0 行，不传标签。`runs/dev-gpt-6.1-sol-probe/` 保留脚本、响应摘要和日志。`max_tokens=200` 返回 400 unsupported_parameter；`max_completion_tokens` 为 200、600、4096 时均正常结束，分别输出 107、102、134 token（含推理 83、78、113），没有空回答。共 $0.004498。
- **兼容实现**：只对 Sol 用 `extra_body` 给现有 SDK 传 `max_completion_tokens`，经现有 LangChain 透传；原上限 200／600 暂时不变，多查询及选码仍不限。默认 gpt-4o 的旧参数不变，无依赖升级、提示词或解析改动。
- **日志与配置**：记录 token 参数、完成原因、内容是否为空、reasoning_effort、service_tier；不存消息内容或错误消息。reasoning_effort 不发送，沿用模型默认 medium。max_completion_tokens 包含推理与可见输出，和旧非推理模型的 max_tokens 不完全等价。
- **离线验收**：114 项通过，覆盖全部 chat 请求、完整 Sol mock 管线、旧运行目录配置冲突及费用；接下来运行原开发集 10+10 张，目录 `runs/dev-gpt-6.1-sol/`。
- **完整开发集（原数值上限）**：`runs/dev-gpt-6.1-sol/` 一次 completed，207 次响应全部 HTTP 200，费用 $0.1329085；其中一张 Nutrition5k（dish_1563391989）的描述 finish_reason=length，200 个输出 token 全是 reasoning，content 为空。后续仍给出编码，不能把 HTTP 200 当作描述成功。其余请求均 stop，份量没有截断。
- **必要上限调整**：仅 Sol 的描述由 200 增至 4096，给推理留余量；Sol 的份量仍为 600，多查询／选码仍不限。默认 gpt-4o 的 200／600 不变。不根据开发集或测试集 MAE 调参，不改提示词和解析。再次跑同一开发集到新目录 `runs/dev-gpt-6.1-sol-4096/`，原轮完整保留，成本全部累计。
- **冻结前验证**：新目录一次 completed，212 次响应全部 HTTP 200，其中 92 次 chat 全部 stop，没有空回答或截断；实际模型 gpt-6.1-sol 和 text-embedding-3-large。两数据集均 10/10 产出编码，ASA24 Exact 1/10；Nutrition5k 份量项成功 12/15、完整菜 7/10，未改解析或提示词。
- **费用与 token**：最终开发集 $0.13707871，输出 7,537 token（含推理 3,856）。ASA24 平均每张 $0.007036652、推理 212.3 token，Nutrition5k 平均每道 $0.006671219、推理 173.3 token。这是各数据集均摊值，日志没有逐图关联字段。
- **预算门槛**：全局累计 $6.71201545，余 $13.28798455。按开发集均摊估算测试 150+150 张为 $2.05618065，按两倍余量为 $4.1123613，均在上限内。
- **协调方离线核对**：`agents/validate_model_run.py` 对上源代码指纹、全局／运行日志、费用、实际请求参数和重新计算的指标，`validation.json` 留存 PASS。评测、份量提示词／解析、营养代码与 E2 逐字不变；描述／查询／选码提示词、重试与索引逻辑 AST 不变。
- **R-F3-1 处理**：校验器分开给出 reconciliation_checks、response_health；空内容、非 stop、缺失或无效健康元数据使总体 checks=needs review，并列 request id／step／问题，CLI 非零退出。账目一致不再遮盖异常。离线向两份账目注入同一空回答＋length，能复现账目 PASS、健康 needs review；干净开发集两个状态均 PASS。没有改推理或重跑开发集，完整离线测试 121 项通过。

### F4 正式测试一次 — 状态：approved（模型对照节点二 R-F4-1、R-F4-2）
- **依据**：paper.txt:303–305；仅在节点一 P1/P2 处理后、预算允许时运行新目录。
- **启动门槛**：节点一唯一 P2 R-F3-1 已离线修复并确认，未发现 P1；预算估算通过。计划用最终开发集相同配置，4 workers，在 `runs/test-gpt-6.1-sol/` 正式运行一次；不改任何提示词、解析或评测，不因测试结果重新运行。
- **正式运行**：2026-10-27 09:02:43–09:43:34 UTC，提交 `fbe5157`，一次 invocation、completed、开始时工作树干净。源指纹与最终开发集一致，全部原样本 150+150 行。
- **响应与健康**：3,234 次响应，3,233 个 HTTP 200、1 个 HTTP 500（ASA24 选码，request id `req_4daec2277b3a4b03b121a13a547af336`）；客户端按原 SDK 逻辑重试，最终流程 completed。1,391 个成功 chat 均 stop，无空内容／截断。校验器账目／指纹／指标一致性 PASS，但 response_health 和总体 checks 如实保留 needs review，指向这条 500 及其缺少完成元数据；没有改为总体 PASS。
- **离线校验适配**：错误响应通常没有 model_served，校验器仅对 HTTP 200 核对实际模型，仍核对所有请求模型和参数；500 保留为健康问题。没有改推理代码、失败定义或费用算法。121 项离线测试通过。
- **费用**：本轮 $2.29594796，输出 124,310 token（含推理 64,977）；ASA24 平均 $0.007874283／张，Nutrition5k $0.007432037／道。全局累计 $9.00796341，余 $10.99203659，没有超预算、下载或重建索引。
- **结果概览**：两数据集编码成功均 150/150；ASA24 Exact 11/150（7.33%），论文协议 n=11，重量 59.68 g、热量 71.19 kcal。Nutrition5k 完整菜 n=118，重量 69.42 g、热量 124.57 kcal。详细配对与解释见 F5 和 REPORT 第 7 节。

### F5 配对对照、区间及报告 — 状态：approved（模型对照节点二 R-F5-2、R-F5-3）
- **依据**：paper.txt:242–259、303–307、Tables 1–3、5；HANDOFF 5.6，分别报告各自成功子集和共同成功子集，ASA24 按编码、Nutrition5k 按菜配对重抽。只做离线分析。
- **预先实现的分析**：`code/compare_models.py` 校验样本唯一键及参考标签一致后配对；报告各自子集、共同 Exact／完整菜的五项 MAE 和 per unit、共同 Exact 分类准确率，以及各自／共同完整菜的重量符号误差、预测／真实比中位数。
- **区间定义**：差值=Sol−gpt-4o，同一组重抽同时用于两个模型；ASA24 在全部抽到的编码上保留三档和失败，Nutrition5k 在全部抽到的菜上保留失败。各自子集的分母可不同，共同子集两边使用相同有效行。10,000 次，种子 20261027；无估计的重抽计数写入 JSON，区间只对本轮回答条件成立，不覆盖模型随机性、论文值的不确定性或跨编码重复照片的相关。
- **Exact 诊断**：原脚本新增 `--run-dir`，默认仍为 `runs/test`；对旧 E2 的输出逐字不变。5 项离线手算测试覆盖配对、重复键／标签漂移、成组重抽、成功子集不同和完全无估计。
- **状态说明**：分析方法和代码在正式测试前写好，报告及最终结果尚待 F4 和节点二。
- **节点一**：R-F5-1 approved，仅覆盖预先实现的分析代码，结果和报告仍待节点二。
- **正式对照**：`runs/comparison-gpt-4o-vs-sol/` 保存 JSON／Markdown；REPORT 第 7 节写明冻结范围、新增偏差、运行、全部五项 per dish／per unit、识别、失败、共同子集区间和解释。表格从脚本输出原样嵌入；正式测试后分析代码只改表格呈现，未改预先提交的统计计算。
- **共同子集**：ASA24 共同 Exact 10 行、8 个编码，重量 102.275→59.4 g，差值区间 −88.151～0.75，含 0；共同分类准确率都是 30%，逐行对错相同。Nutrition5k 共同完整菜 79 道，重量 96.013→62.241 g，差值 −33.772，区间 −48.916～−19.661；热量 126.857→131.832 kcal，区间含 0。
- **低估**：共同 79 道平均符号误差 −75.051→−25.152 g；预测／真实比中位数 0.6787→0.9402。
- **识别与失败**：Exact any 21/125→11/150，按全部行计 21/150→11/150；127/139 个 Sol 非 Exact 的真实编码不在候选，12 个在候选但没选。Sol 207 项食物中 175 项有克数，32 项按原启发式分类为组合名拆开 30、其他改名 2，FoodCodeError=0；分类与 WeightError 总数核对一致。
- **结论边界**：克重低估部分改善，热量及其他营养未见稳定改善，Exact 下降。不能将全部差距归为模型能力，也不能断言其余一定来自样本／协议。一次抽样、temperature 和 token 上限变化、共同成功子集、照片标签歧义及区间局限均已披露。
- **验收**：121 项离线测试通过；报告表格逐字对应生成文件、无环境信息；推理、提示词、解析、营养及评测自 F4 启动后无改动。待模型对照节点二一次审查。
- **节点二完成**：R-F4-1、R-F4-2、R-F5-2、R-F5-3 全部 approved，无新增 P1/P2/P3。审查方独立复算 20 组 MAE／per unit／配对区间、原始份量→营养派生、费用和诊断，121 项离线测试通过；保留历史 500 与 needs review，不重跑测试或改写历史状态。本组完成。

### F6 英文报告整合与精简 — 状态：fixed（按用户要求进行文档修订，已离线核对）
- **用户要求**：将模型对照整合进原报告，明确它由原 GPT-4 Turbo 停止提供服务引出；精简重复内容，整份 REPORT.md 改为英文。
- **依据**：paper.txt:303–305 的原模型与 temperature 设置、:242–259 的评测定义；A3 的历史 404 deprecation 记录，以及已审查的 E2、F4、F5 结果。本轮没有增加科学分析或新实验。
- **改动**：REPORT.md 从 435 行整合为 211 行；统一两轮的方法和结果，保留各自／共同子集的五项 MAE、per unit、配对区间、样本数、识别／份量指标、偏差、费用、500 警示及结论限制。原逐项偏差清单压缩为分组摘要，完整决定保留在本文件与 REVIEW.md。旧中文版由 Git 历史保留。
- **目录映射**：原中文第 7 节的模型对照现并入英文第 1–3、5–6 节；原中文第 4 节的偏差清单对应英文第 4 节。此前条目和审查中的章节／行号为当时版本，按对应提交查询。
- **文档核对**：五个指标表由保存的 comparison.json／metrics.json 生成并逐表比对；论文目标值与 evaluate.PAPER 一致；报告无中文残留，链接目标和 Markdown 表格结构有效，未加入运行环境信息或密钥。code、tests、runs、logs 均无修改，没有付费调用、下载或测试集重跑。
- **审查范围**：已有两个审查节点不重复审查；本次英文表述与结构修订未宣称获得新的独立审查。121 项测试是既有实现与结果的审查验证，本次只做文档检查。

## G GitHub 与 Mac 演示交付（用户 2026-10-27 要求）

### G1 可配置和验证的演示入口 — 状态：fixed（离线验证通过）
- **要求**：公开源码到 `THwo0t/DietAI24-reproduction`；Mac 拉取后由 Codex 配环境，先展示已验证结果，配置本地 key 后可跑少量真实推理。
- **依据**：沿用 paper.txt:151–160、237–259、303–305 的流水线和指标；此项只包装演示，不改变 E2/F4 的科学实现、参数、提示词、解析、结果或论文差异。
- **实现**：`setup.sh` 校验并本地安装固定 uv/Python 3.10.13，按原 freeze 安装 `.venv-demo`；`tools/demo.py` 提供无 key、无 API 的交互展示和证据哈希/CSV 算术检查。英文 MD、PDF、DOCX 同步交付。
- **在线准备**：28 文件 runtime 包含 20 张原开发图、必要营养/份量/映射和原 5624×3072 embedding；校验 float32 与原向量一致，Mac 重建原生 Chroma，不搬 Linux HNSW，不调用 API 重建 embedding。SHA256 和字节数固定在 `demo/runtime-release.json`。
- **新推理**：wrapper 调用原代码，仅各一张开发图，独立 `demo-runs`。显式 `--allow-paid`；每请求 timeout 45 秒、SDK retry 1、最多 80 次 HTTP，usage 估计阈值在请求之间停止，单次在途调用可能超过。上述演示差异另存 config，不作为新正式测试。
- **验证**：原 121 项加 9 项交付验收，共 130 项离线测试通过；例图、数据集/子集切换和报告入口已在浏览器验证。发布前还需全新环境与实际 Mac CI 记录；dry-run 不代表真实付费推理成功。
- **交接**：`START_HERE_MAC.md`、`MAC_DEMO.md` 和 AGENTS 新入口防止 Mac Codex 执行历史 HANDOFF 重跑；来源与数据条款在 `THIRD_PARTY.md`，上游 README 原样保留。

### G2 发布与干净拉取验证 — 状态：in progress
- **范围**：扫描可达 Git 历史与待发布文件，不包含 `.env`、原始大数据、虚拟环境和 native index；公开仓库保存源码/结果/三版报告，固定 release 提供 runtime。
- **验收**：全新 clone 自动安装、离线检查/页面、原生索引恢复、无 key dry-run；实际 Mac CI 与 Linux CI 的架构/状态明确记录，不把无 key 检查称为真实 API 演示。
