# C：仅替换视觉模型为 Gemini 3.8 Flash

用户2026-11-05授权全843开发图：主文字模型Sol、视觉模型Gemini；endpoint沿zicc，总32并发。
模型在config.py分llm与llm_vision，按消息有无图片路由，包括携带历史图片的格式修复。
N5 314张重新预测原C布局/选码/份量，ASA529张重新识别/选码/估重；原Sol结果不覆盖。
原C提示、图像预处理、多查询FNDDS、k4、同食物1–3码密度均值、总重×比例及评分算法均不改。
重新按完整关联组五折拟合N5半修正与ASA完整修正，不沿用Sol系数，不加入图库。
底层仅完全相同请求复用：hash含model与payload；文字Sol及官方embedding缓存可复用。
每个请求最多3次持久传输，全局32槽；独立验收封存，无GitHub上传。
密钥仅private.env（600权限、git忽略），不进入冻结、源码或日志。

先运行run.py --prepare，接口小检查使用同一运行缓存；随后run.py --run --allow-paid --workers 32。
完成后verify_completed.py与compare_baseline.py离线核验。

首图格式兼容：Gemini在JSON前附解释，两次有效HTTP回复被旧严格格式判失败。
原首图源码/冻结/结果/2次用量存preformat_snapshot。仅Gemini接口提取唯一完整JSON对象原substring，
数组、多对象、截断或对象外结构符号均不提取；原契约继续检查，原始回复保留，提取前后hash审计。
重新准备后精确请求重放旧缓存，不重发成功回答；总用量包括归档2次。
