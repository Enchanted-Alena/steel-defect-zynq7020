# Zynq-7020 卷积与 AXI-DMA 调试 Skill

本目录提供本项目的可复用调试方法。首次使用从[技能入口](zynq7020-cnn-dma-debug/SKILL.md)开始；首次离线操作按[快速开始](zynq7020-cnn-dma-debug/QUICKSTART.md)生成并核对三条合成接口载荷。它不需要板卡，不编译ARM固件，不验证模型准确率。

## 适用范围

- 平台：Smart Zynq SL V1.3B，xc7z020clg484-1，Protocol 2.0，PL 100 MHz。
- 完整分类接口：离线生成的单通道32×32 INT8输入，两层3×3卷积、通道1→4→8，ReLU、2×2最大池化，PS侧2048→6整数分类头。
- 两层顺序复用同一PL核心，层间经DDR。分离路径两层POST_OP=0；融合路径Conv1=1、Conv2=2。
- 用户模型、输入和第三方工具须合法取得。更换板卡、网络结构、算子或量化合同，需要重新评估适配范围，不能直接沿用本项目成绩。

## 使用方法

1. **阅读与准备**：在同一仓库定位[源码README](../01_source/steel-defect-zynq7020/README.md)及[复现说明](../01_source/steel-defect-zynq7020/REPRODUCE.md)。按源码依赖锁准备Python 3.12环境；输出写入源码树外的新空目录。
2. **首次离线试用**：按[QUICKSTART](zynq7020-cnn-dma-debug/QUICKSTART.md)依次创建夹具、生成兼容性载荷、运行独立标量核对。命令和预期字段以该文档为准，最后应为`EIGHT_PAYLOADS_SCALAR_REFERENCE_PASS`，且`BoardExecuted=false`、`FormalResultReproduced=false`。
3. **用户模型与硬件调试**：先阅读[八载荷合同](zynq7020-cnn-dma-debug/references/payload-interface-r3.md)、[调试指南](zynq7020-cnn-dma-debug/references/debug-guide.md)和[寄存器表](zynq7020-cnn-dma-debug/references/interface-registers.md)。兼容性分支仅1～16条；编译和上板需要匹配的硬件/BSP/ELF及涵盖当前输入和操作范围的授权。本README本身不授予这些操作权限。
4. **留存试用证据**：保存实际命令、环境、输入与脚本哈希、完整输出。未编写此Skill的真人可按[独立试用表](zynq7020-cnn-dma-debug/references/independent-trial-form.md)记录离线试用；整理者不得代填结果。

## 失效条件与停止方式

出现下列情况时，不能套用已有PASS或继续宣称已验证，应停止当前流程、保留日志并核对原因：

- **适用范围失效**：板型、协议、网络形状、整数数值合同、零点或池化尺寸不符合入口及载荷合同。不得用修改Golden、忽略溢出规则或占位数据绕过检查。
- **身份关联失效**：模型、样本顺序、载荷、bit/XSA、PS初始化、BSP或ELF无法对应；不能仅凭相似文件名推断兼容。
- **接口或运行检查失败**：协议/能力寄存器不符、POST_OP回读不符、DMA包长/状态、guard、数值核对失败或超时。保存上下文后排查，不自动重试正式270样本，也不强制访问被工具阻止的地址。
- **权限或证据范围失效**：没有相应会话授权，或打算从离线试用扩大到编译、烧录、重建实现。先明确范围；历史授权及某次合成PASS不能替代当前缺失的授权或实测证据。

## 验证状态与结论边界

2026-10-28正式270样本记录、2026-11-02原模型前三条三路径补充记录、A提供的2026-11-04合成离线摘要是不同轮次。合成夹具不产生真实准确率，不复现217/270或5.917320 ms，不证明板端运行、DDR饱和或其他模型兼容。

A已授权A侧助手完成所列软件核对与后续文档收尾，B提供工程材料并完成增量整合；本包完成静态完整性核对。这些记录不代表C本人对新包独立签认。另一名真人的Skill独立试用未完成，试用表仍为空。C04只通过旧哈希版本，不能沿用为本次通过结论。最新集合身份和状态见[根README](../README.md)、[发布状态](../PUBLIC_RELEASE_STATUS.json)及根SHA-256清单。

本目录新增README仅汇总入口与范围，详细步骤以SKILL.md和references为准；原Skill LICENSE及第三方声明保留。
