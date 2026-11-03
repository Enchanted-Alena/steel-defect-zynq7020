# 面向钢材缺陷分类的卷积加速器

版本：B_SOURCE_CLOSEOUT_R3_1_C02_REVIEW_RC_20261102。

完整脚本集要求Python3.12；历史环境记录与本机验证环境分别说明。

本仓库提供固定 1→4→8 INT8 模型接口、HLS/RTL、PS 驱动、固件和源码构建入口。
公开范围为完整工程源码；第三方板级输入由用户合法取得并本地生成，不分发原例程和受限配置。
私有权重、图像、载荷和硬件二进制不包含在源码包中。

- 从干净源码重建硬件、生成 BSP、构建用户固件：[REPRODUCE.md](REPRODUCE.md)。
- 八文件接口、模型范围和顺序：[docs/PAYLOAD_INTERFACE.md](docs/PAYLOAD_INTERFACE.md)。
- 第三方输入的来源和本地生成：[docs/BOARD_INPUT_ACQUISITION.md](docs/BOARD_INPUT_ACQUISITION.md)。
- 实际验证与尚未验证事项：[docs/VALIDATION_STATUS_R3.md](docs/VALIDATION_STATUS_R3.md)。
- 逐文件来源/许可及公开清单：SOURCE_PROVENANCE_LICENSE_REVIEW.csv、RELEASE_FILE_WHITELIST.csv。
- C编号02已完成原R3首次复核，本修订仍待差分复核：[docs/C_REVIEW_REQUEST_R3.md](docs/C_REVIEW_REQUEST_R3.md)。

已经验证：3 条合成接口用例的载荷生成、独立标量核对、固件 C 算法主机执行、ARM ELF 编译；
用户本地 PS 参数导入/规范化和基于既有 HLS RTL 的 BD 校验。
已在用户授权下用此前冻结模型和前3条输入完成内部载荷/C核对/ARM编译，四Golden和FNV与冻结前缀一致；私有载荷不公开。
原R3打包后已完成原模型前三条的独立上板补充验证：ARM/legacyPL/fusedPL共9条正确性记录PASS；不替换正式270成绩。
未验证：新HLS生成到完整margin930实现、新XSA到新BSP、异机重建及其他模型广泛兼容性。
C编号02结论HOLD_FOR_DOCUMENT_FIXES，尚待本修订差分及外部Skill复核、A确定公开集合；本ZIP不是最终发布RAR。
这些验证不能声称复现正式 217/270、5.917320 ms、+0.718 ns 或同一 bit/hash。
