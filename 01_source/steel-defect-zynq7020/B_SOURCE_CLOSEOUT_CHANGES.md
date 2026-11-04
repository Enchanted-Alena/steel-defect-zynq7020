# B源码收尾：R3.1 C02差分复核候选

基于原R3 SHA-256 a984d4121701315c11983bd05ad4c7b165d635200d0cb3fc35484707ad16ea6f，在新目录修订，旧包和正式冻结工件不改。

- C02 P1：重写环境记录与可复现缺口，区分已有历史文档/训练命令/合同参数和缺失的原机器导出/终端日志。
- C02 P2：补生成器兼容分支帮助、完整脚本集Python3.12说明；builder显式要求NeedsExplicitBoardSession=true，独立verifier显式核对ProtocolVersion/FormalFrozenReplay/DoNotProgram/NeedsExplicitBoardSession。
- A状态同步：原模型前三条后续9条正确性补测PASS；C已首次复核、仍需修订后差分；新HLS完整实现/新BSP/异机仍未验证。
- 数值算法、HLS、RTL、正式main/driver/model_ops、兼容固件源及依赖wheel锁保持原字节；不以新说明替换旧轮次实验归属。
- 按A说明处理文档，但未收到A两份overlay原件，不主张逐字合入。
- 更新本候选来源表、白名单和RC清单；外部Skill独立复核，不悄悄计入源码100项。

本候选未重新ARM编译、上板、HLS/综合/实现或测正式性能；本次针对性软件核验另列。旧离线编译/板测结果属于原R3文件版本。
最终RAR/公开集合须等待C针对本版的回执及A决定。


## 2026-11-04状态补记

以上为原R3.1请求/修订时记录。C04已对原R3.1输入及旧六文件Skill给出精确版本结论，原P1/P2问题已关闭；A10已接受两份文档内容，不再等待旧overlay原件。C04未审阅本次Skill增补、报告和AI记录。当前新候选待C精确版本复核，独立真人试用未完成；最终发布由A决定。历史输入及C04身份见整包根README。
