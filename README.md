# 面向钢材缺陷分类的卷积加速器：完整源码与Skill最终交付集合

版本B_SOURCE_AND_SKILL_FINAL_20261103。C04已针对精确R3.1源码与Skill集合回执：PASS_FOR_FINAL_PACKAGING_WITH_VERSION_GUARD。

## 入口

- 工程源码：01_source/steel-defect-zynq7020/（100文件，逐字节对应R3.1候选输入）。进入该目录后按REPRODUCE.md使用构建、载荷和固件入口。
- Skill：03_skill/zynq7020-cnn-dma-debug/SKILL.md（六文件）；路径与报告R3g引用一致。它不在原源码100文件内，已明确加入本整包根白名单和来源表。
- 工程源输入归档SHA-256：338f5a4272b5a3fc266976be402c16b80572c5123d502fcb06d1102860c65ea1。此值标识原输入ZIP，不是本整包ZIP哈希；解压后的100文件逐项与其一致，不保证重新压缩成同一哈希。

Skill继续绑定这份源码输入身份；本整包由根SHA256SUMS及外层最终RAR单独绑定。所有嵌套清单均纳入根清单。
根FILE_INDEX仅排除其自身与根SHA，根SHA仅排除其自身；来源表仅对四个根完整性元文件留空哈希避免循环，其他文件均列实际哈希，包括嵌套源码的三个完整性文件。


## 许可与公开边界

团队有权授权的源码及说明按Apache-2.0范围处理；原来源表、AMD链接脚本MIT声明和第三方说明原样保留。
工具、IP、BSP、板级参考由使用者合法取得并本地生成；不捆绑私有模型/输入/Golden/逐样本日志或bit/XSA/ELF/DCP。
报告图件、内部追溯ZIP、C原始视频、internal_audit及旧候选不属于这套源码+Skill集合。
目标仓库由A提供并管理：https://github.com/Enchanted-Alena/steel-defect-zynq7020 。





