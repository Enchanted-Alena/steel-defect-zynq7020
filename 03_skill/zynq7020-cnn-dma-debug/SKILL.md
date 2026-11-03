---
name: zynq7020-cnn-dma-debug
description: Audit or debug the Smart Zynq SL Protocol 2.0 INT8 CNN AXI-DMA workflow, from lawful user payloads and firmware to existing compatible hardware. Use for this project's register, cache, DMA, payload and evidence workflow; other boards or model structures require a new compatibility assessment.
---

# Zynq-7020 AXI-DMA与卷积引擎端到端调试

## 适用范围

用于Smart Zynq SL V1.3B、xc7z020clg484-1、Protocol 2.0的团队工程。输入为离线32×32 INT8，结构固定1→4→8，两层卷积、ReLU、2×2池化和PS上的2048→6分类头。
同一个PL卷积核顺序复用；层间仍经DDR。不要把本技能描述为任意算法、任意板卡或相机链路即插即用。

先定位用户指定的R3.1源码根目录；其源码输入候选归档的SHA-256为
`338f5a4272b5a3fc266976be402c16b80572c5123d502fcb06d1102860c65ea1`。
本技能不属于该100文件源码集合。若整包交付的是解压后的源码目录，以根来源表核对100文件对应关系；上述归档哈希不代表源码与Skill整包哈希。

## 根据任务选择流程

- 只读审阅、报告整理：检查源码、锁和已有日志，不连接硬件或启动构建。
- 用户模型兼容性：阅读[载荷合同](references/payload-interface-r3.md)和[操作指南](references/debug-guide.md)，使用R3系列现有生成、独立核对、编译、身份锁和小样本运行入口。
- 新硬件构建：阅读[源码构建配方](references/source-reproduce-r3.md)。该入口涉及HLS/综合/实现；仅在当前任务确有相应授权时执行。

沿用用户在本轮给出的授权，不为已经授权的同一操作重复询问。执行前核对该授权是否涵盖当前板卡、输入和操作范围；缺少必要范围时先说明具体缺项。

## 必须保持的工程条件

1. bit、XSA、PS初始化、BSP、ELF及载荷身份须能对应；文件名相似不能代替哈希关联。输出在仓库外新目录。
2. CNN不是HLS默认ap_ctrl窗口；CSR及DMA含义见[接口表](references/interface-registers.md)。CONTROL接受命令值0/1/2/4/8/12，不是任意按位OR的掩码。
3. 启动前检查0x88/0x8C/0x90为0x00020000/0x00030102/1。POST_OP仅空闲时写并读回：legacy两层0；fused Conv1=1、Conv2=2。模式2仅接受适用的偶数尺寸/零点条件。
4. 先建立接收S2MM，再启动CNN和MM2S。维持DMA前Flush、DMA后Invalidate、64字节对齐/guard及超时；不通过删掉检查来取得更好延迟。
5. 长度寄存器0x2C/0x30有流水计算/握手条件；不能用固定短轮询次数替代超时。POST_OP不属于输入数据包字段。
6. 兼容性分支仅1～16条；当前已验证的是原模型同序0/1/2三条。合成fixture只检验数值接口，不是分类准确率或训练模型证据。
7. 新增实现必须保持实际100MHz；9.300ns为实现分析目标，结束恢复10.000ns后新进程独立检查WNS≥+0.500ns、WHS≥0、TNS/THS=0、DRC Error=0。配方存在不等于这条完整重建流程已执行。

## 板测与故障处理

按当前枚举选择板卡UART，不照搬旧COM号。确认可独占，核对JTAG目标后再下载；已有本轮授权及连接确认时直接继续。
使用R3系列现有`run_user_compatibility.py`，保留原始UART/JTAG、会话范围和工件哈希。仅易失下载，不写Flash。
解析专用`PASS: USER_MODEL_COMPATIBILITY_NOT_FORMAL`及3N条记录，核对预测、logits、规定中间结果/FNV、guard和DMA状态。
FAIL、超时、身份不符或数值不符即保存现场并停止；先排查原因，源码/固件或实现修改超出当前范围时再报告，不自动重跑正式270。
结束确认停核和串口释放。若XSDB只读PL地址被内存映射阻止，如实记录；它不能被写成成功的寄存器快照，也不自动授权强制访问或重新实现。

## 交付结论

分别列出“说明齐备”“已离线运行”“已上板”“未验证”。报告包含输入/模型范围、样本数、路径、原始日志SHA-256和适用工件。
正式270结果属于2026-10-28；2026-11-02的3样本属于独立兼容性补充验证。旧R3原包中的未上板是打包时状态，后续回执仅更新这项事实。
不得把三路径一致写成100%任务准确率，或把小样本PASS写成复现217/270。独立Profiling的嵌套窗口不可饼图相加，也不证明DDR饱和。

本次R3.1补锁字段断言并完成软件核验，未重新编译/上板；实际三样本板测归属原R3。当前Skill本身仍待C技术复核，不以结构校验代替其结论。
