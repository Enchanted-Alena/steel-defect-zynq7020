# 面向钢材缺陷分类的卷积加速器

工程基础版本：B_SOURCE_CLOSEOUT_R3_1_C02_REVIEW_RC_20261102。
当前文档整合候选：B_FULL_REPOSITORY_CANDIDATE_R3_20261104（2026-11-04，仅状态与清单修订）。

完整脚本集要求Python3.12；历史环境记录与本机验证环境分别说明。

本仓库提供固定 1→4→8 INT8 模型接口、HLS/RTL、PS 驱动、固件和源码构建入口。
公开范围为完整工程源码；第三方板级输入由用户合法取得并本地生成，不分发原例程和受限配置。
私有权重、图像、载荷和硬件二进制不包含在源码包中。

- 从干净源码重建硬件、生成 BSP、构建用户固件：[REPRODUCE.md](REPRODUCE.md)。
- 八文件接口、模型范围和顺序：[docs/PAYLOAD_INTERFACE.md](docs/PAYLOAD_INTERFACE.md)。
- 第三方输入的来源和本地生成：[docs/BOARD_INPUT_ACQUISITION.md](docs/BOARD_INPUT_ACQUISITION.md)。
- 实际验证与尚未验证事项：[docs/VALIDATION_STATUS_R3.md](docs/VALIDATION_STATUS_R3.md)。
- 逐文件来源/许可及公开清单：SOURCE_PROVENANCE_LICENSE_REVIEW.csv、RELEASE_FILE_WHITELIST.csv。
- C编号02为历史首次复核；C04已完成原R3.1及旧Skill精确复核，本轮由A授权助手接手补充核对，原请求作历史保留：[docs/C_REVIEW_REQUEST_R3.md](docs/C_REVIEW_REQUEST_R3.md)。

已经验证：3 条合成接口用例的载荷生成、独立标量核对、固件 C 算法主机执行、ARM ELF 编译；
用户本地 PS 参数导入/规范化和基于既有 HLS RTL 的 BD 校验。
已在用户授权下用此前冻结模型和前3条输入完成内部载荷/C核对/ARM编译，四Golden和FNV与冻结前缀一致；私有载荷不公开。
原R3打包后已完成原模型前三条的独立上板补充验证：ARM/legacyPL/fusedPL共9条正确性记录PASS；不替换正式270成绩。
未验证：新HLS生成到完整margin930实现、新XSA到新BSP、异机重建及其他模型广泛兼容性。
C编号02历史结论为HOLD_FOR_DOCUMENT_FIXES；C04随后对原R3.1及旧Skill给出PASS_FOR_FINAL_PACKAGING_WITH_VERSION_GUARD。旧Skill技术复核为PASS_STATIC_AND_TECHNICAL_REVIEW，仅绑定旧SKILL.md哈希804f2c39b60866934bc66ecab5f0cf25fcfd354b78dc7f48410522520dacb55f。当前2026-11-04整合包已接收A授权助手的软件核对、由B完成静态封装，待A确认发布；不冒充C本人签认，独立真人试用未完成，不继承旧版批准；见[根发布状态](../../PUBLIC_RELEASE_STATUS.json)。
这些验证不能声称复现正式 217/270、5.917320 ms、+0.718 ns 或同一 bit/hash。


## 2026-11-04 A授权接手后的当前整合状态

当前完整候选：`B_FULL_REPOSITORY_CANDIDATE_R3_20261104`。A明确授权A侧Codex助手接手C尚未完成的报告补充与软件核对，已收到绑定B120输入的25项Python文件语法和18项运行检查记录；结果及范围见[软件核对说明](../../report/validation/software_review_20261104.md)。这些不是C本人独立签认，B本轮也未重新运行项目代码。

原C02/C04和“待C差分”等保留为历史版本记录，不作为本轮等待C本人的唯一条件。B已更新内外清单并封装，最终由A确认发布；真人Skill独立试用、新HLS完整系统、新BSP和异机重建仍未完成。完整集合身份及当前状态以仓库根文件为准。
