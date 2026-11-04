# 设计报告与评审材料

**主报告：[面向钢材缺陷分类的卷积加速器设计报告](design_report.md)**

本目录按企业赛道3.3.5.3组织仓库技术材料。主报告包含背景及相关工作、系统原理与框图、软硬件划分、优化过程及前后比较、大模型交互与纠错、Skill提炼、从零操作步骤和验证范围。

| 材料 | 用途 |
|---|---|
| [design_report.md](design_report.md) | 仓库完整设计报告，配图位于assets目录 |
| [hardware_tradeoffs.md](hardware_tradeoffs.md) | 硬件设计取舍和历史优化过程 |
| [optimization_comparison.csv](optimization_comparison.csv) | 性能、资源和比较范围 |
| [ai_collaboration_log_a.md](ai_collaboration_log_a.md) | A端提示、模型回答、自我纠错及工具工作流 |
| [ai_collaboration_log_b.md](ai_collaboration_log_b.md) | B提供的真实交互节选及纠错过程 |
| [b_ai_quote_records.csv](b_ai_quote_records.csv) | B端节选的字符数、来源标识和哈希 |
| [ai_collaboration_log.md](ai_collaboration_log.md) | 另行标明的历史协作摘要 |
| [reproducibility_guide.md](reproducibility_guide.md) | 从环境、载荷到硬件/固件的操作索引 |
| [claim_evidence_map.csv](claim_evidence_map.csv) | 报告主张与证据的对应关系 |
| [软件验证说明](validation/software_review_20261104.md) | 25文件语法和18项运行检查的范围、结果及日志入口 |
| [Skill总览](../03_skill/README.md) | 可复用调试规则、快速开始和试用边界 |

## 与官网模板报告的关系

官网模板Word属于另一路上传材料；仓库以本目录的Markdown设计报告为主，并补充可直接浏览的交互记录、图表和复现入口。二者核心数据、统计口径和验证边界须一致，结构与篇幅可以不同。当前包不收录旧模板Word/PDF，避免误认为它们是官网最新稿。

## 证据与来源

正式准确率、时序和性能属于历史冻结工件；本轮软件检查单独记录，不改写为重新板测或完整硬件复现。A端助手接手补充工作，不署名C本人独立签认；真人Skill独立试用尚未完成。B端会话片段由B提供，其长度与哈希已核对，但未独立调取B平台原消息。

[source_index_b120.csv](source_index_b120.csv)是历史B120输入快照，27项公开来源哈希绑定该输入；当前文件身份以仓库根清单为准。PRIVATE项只给出内部原件的逻辑身份，不是可下载路径。私有模型、数据、Golden、硬件二进制和原始板端日志不在本目录分发。

[design_report_supplement.md](design_report_supplement.md)保留补充章节的来源文本，其内容已合入主报告。
