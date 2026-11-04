# 合成接口示例与验证记录

本示例复用源码中的 `scripts/make_interface_fixture.py`，不包含真实模型、图像、标签或 Golden 数据。夹具标记为 `FixtureOnly`，标签不是真值；不得将输出用于准确率或模型质量结论。

## 执行步骤

按 [快速开始](../QUICKSTART.md) 依次调用：

1. `make_interface_fixture.py` 创建三条合成输入和合成整数模型合同。
2. `generate_user_payloads.py --compatibility` 生成小样本载荷。
3. `verify_user_payloads.py` 用独立标量参考核对载荷及 Golden。

## A提供的离线试跑记录（随更新候选转交）

- 日期：2026-11-04
- 输入：固定种子的三条合成接口刺激；非训练模型、非NEU-CLS样本。
- 结果：`SYNTHETIC_INTERFACE_FIXTURE_CREATED_NO_CLASSIFICATION_CLAIM`；`USER_PAYLOADS_GENERATED_NOT_FORMAL_OR_BOARD_VALIDATED`；验证器返回 `EIGHT_PAYLOADS_SCALAR_REFERENCE_PASS`。
- 核对项：3条样本、四份Golden逐字节一致、阶段FNV小端记录一致、头文件和Job包一致、输入顺序身份一致。
- 明确未做：ARM固件编译、HLS/Vivado、板端执行、正式270样本测试、性能测试。
- 记录性质：这是A提供的候选文档所记载的一次离线软件检查；B本轮仅静态整合，未重复执行，原始命令及输出由C进一步核对。它不是第三方Skill试用，也不证明其他环境或其他模型兼容。

复现前应使用源码锁定的依赖，并为 `--out` 提供新的空目录。复现者应自行保存命令、Python版本、脚本哈希和完整输出；不得将本记录冒充他人独立复核。
