# 分阶段模型：一次有限离线审查

2026-11-05：核心部分 **approved**，无 P1/P2 必修。

范围：run.py、pipeline.py、config.py、provider.py、newcommon.py、stage_routes.py。verify_completed.py、compare_baseline.py、batch.py 当时仍在由其他实现者修改，不在本次核心审查结论内；batch 后续仅增量检查。

- run.py source_index/source_value 校验源完成记录的 freeze/records hash、逐阶段文件 hash、sid、value hash；实际只读执行 source_index(rows_only())，获得 N5 layout/identity/portion/record 各314和 ASA identity529，全部校验通过。initialize_imports 原值重封装入新freeze，N5记录不重预测，ASA全身份复用并建立新identity_seal。
- run_asa 禁止缺失身份时重预测，取得完整529身份后建立/验证屏障，再读取开发参考标签构造已登记条件上下文。新ASA portion/record绑定 identity hash、config及portion_model；不导入旧ASA portion或record。
- StageRoutingMixin 在原 _stage 完整修复循环外设置 ContextVar 路由；不同线程/调用不共享可变阶段。ASA portion 明确 Sol，有图的 recognition/selection仍Gemini；纯MultiQuery仍Sol。provider 再次按dataset/stage/图片验证模型，返回模型校验保留，JSON包装提取仅限Gemini。
- pipeline改动仅增加路由mixin与delegate类型，原提示、解析、选项投影及营养算法未改。保留原ASA条件推理/主码结果复用规则。newcommon保留请求完整payload/model hash、跨进程请求锁、全局32槽和持久最多3次attempt，route只入审计不改模型消息。
- 新N5入口若没有导入完成记录即拒绝重预测；ASA禁用新检索函数，当前份量流程不执行新检索。

独立执行26项离线测试，全部通过。未读取private.env、任何.env或key，未调用API，未访问独立验收，未修改预测与源码。此结论只涵盖核心源码及离线行为，不代表新付费预测已运行或完成。

## 运行管理与离线核验：增量检查

2026-11-05：**approved**，无 P1/P2 必修。本节只检查核心审查后的 batch.py、删除不可达N5在线重跑路径，以及 verify_completed.py / compare_baseline.py 的新关键断言。

- batch.completed_worker 要求 ASA worker_done 的status/profile/freeze/records/usage hash有效，再独立核 completion 和身份seal。只启动ASA worker；预测等待有40分钟运行上限，超时失败停止，不能被当完成。有效标记后最多等待10秒，仍未退出则有限终止并明确记录worker_exit_issue，不伪称自然退出。随后依次score、verify、compare，各离线进程限180秒且非0停止。
- run.py已删除N5在线重跑实现，ASA单一路径调用；freeze_value增加batch.py及compare_baseline.py，改动需在prepare前冻结。
- verify_imports重建并比较完整source_index、重核来源文件hash与导入值；N5 raw records及完整校准OOF（含fold参数）要求与源完全相同。ASA要求529相同集合、身份字段与源完全相同、条件176名单完全一致。
- verify_provider_route只接受ASA/chat/portion/Sol；同时覆盖新传输和exact-cache observations，传输要求有图、HTTP200返回模型必须Sol；N5没有provider日志时允许缺失，不会误要求重跑。
- compare基线为当前Gemini全视觉版，完整N5原始记录和OOF必须相同；ASA身份字段不变、Exact176集合相同；条件176与529总体单列，raw/retained各自比较，未混集合。

再次独立执行26项离线测试，全部通过；未运行需要凭据扫描的完整verify，未读取任何凭据、未API、未访问验收或修改预测。可在全部源码最终固定后prepare并按已授权范围启动；实际运行与完成以新的封存产物为准。
