# 基于Zynq-7020的AXI-DMA与卷积引擎端到端调试指南

这份指南整理R3系列工程和已经完成的验证步骤，不新增构建、烧录或正式测量。命令在解压R3源码根目录运行；路径为用户自选示例。

## 1 先锁定适用范围和身份

Smart Zynq SL V1.3B；PL100MHz；Protocol 2.0；固定1→4→8 INT8模型、NCHW/C-major、32×32灰度输入；FC2048→6。
不是通用网络自动映射工具。用户必须合法持有模型/数据，其他开发板的DDR/MIO/电气配置不照搬。
依赖以R3的requirements-validation-win-py312.lock、TOOLCHAIN_VALIDATION_LOCK.json和REPRODUCE.md为准。验证环境与历史训练环境分开。

## 2 用户模型到八载荷

准备NPZ模型、JSON整数合同、连续INT8输入和同序index.csv；键、形状、布局、长度、样本顺序及四Golden对应关系见payload-interface-r3.md。
独立兼容性分支1～16条。生成器拒绝超出结构/范围的输入，不能用占位数据冒充正式模型。

```powershell
$work = 'C:/fpga-user-work'
$python = "$work/venv/Scripts/python.exe"
& $python scripts/generate_user_payloads.py --compatibility --model "$work/user/model.npz" --contract "$work/user/contract.json" --inputs "$work/user/inputs_int8.bin" --index "$work/user/index.csv" --out "$work/payload"
& $python scripts/verify_user_payloads.py --payload "$work/payload"
```

检查model_params.h、board_vectors.h、batch_data.h、四份独立Golden、batch_fused_stage_fnv及锁文件。保留生成输入身份；Golden不通过时先排查合同/布局/溢出/移位规则，不更换冻结参考来获得PASS。
已有GCC时可按源码REPRODUCE.md运行实际固件C算法的主机交叉核对；它不模拟PL、DMA或板测。

## 3 编译专用小样本固件

```powershell
$gcc = 'C:/AMD/2025.2/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
& $python scripts/build_user_firmware.py --gcc $gcc --bsp "$work/sdk/bsp" --payload "$work/payload" --out "$work/firmware"
```

使用对应XSA的Cortex-A9 standalone BSP；不按同名目录猜关联。检查build_record.json的编译返回值、ELF哈希、载荷锁与BSP文件哈希。
输出user_model_compatibility.elf，不替换正式270 ELF。该分支执行一次小样本正确性pass，不做正式性能扫描。
新XSA生成BSP的入口尚未实际验证；不要把使用既有匹配BSP的编译成功写成新BSP生成已通过。

## 4 板卡连接和运行

当前会话授权覆盖连接、易失下载和小样本运行后，识别板卡UART/JTAG，检查串口独占和hw_server端口占用。hw_server由本机合法安装提供，不分发工具。

```powershell
& $python scripts/lock_compatible_hardware.py --bit "$work/hw/system.bit" --xsa "$work/hw/system.xsa" --ps7-init "$work/hw/ps7_init.tcl" --bsp "$work/sdk/bsp" --out "$work/hardware-lock.json" --confirm-compatible-hardware
& $python scripts/run_user_compatibility.py --xsdb 'C:/AMD/2025.2/Vitis/bin/xsdb.bat' --hardware-lock "$work/hardware-lock.json" --build "$work/firmware" --payload "$work/payload" --port COM9 --out "$work/board-run" --confirm-current-board-session
```

COM9只是2026-11-02的实例，执行时以本次实际枚举为准。运行目录必须不存在，避免覆盖旧日志。
工具先核对锁再下载，固件先核对协议/能力再启动DMA。完整操作顺序、包长、POST_OP和Cache规则见interface-registers.md及源码software/dma_driver.inc，不用手工寄存器写入替代受控入口。

## 5 定位常见故障

| 现象 | 首先检查 | 处理边界 |
|---|---|---|
| 无板卡串口 | USB数据线、CH340驱动、实际COM号及供电 | 蓝牙COM不能代替板卡UART |
| JTAG目标为空 | 下载器自身USB、排线、目标供电、端口占用 | 先枚举，不盲目重烧 |
| 协议或能力不符 | bit/XSA/BSP身份与0x88/0x8C/0x90 | 停止，不启动DMA |
| stream lengths/post-op | 模式、维度、预期TX/RX长度、空闲写回 | 模式2输出为对应全尺寸输出的1/4，不把总TX包长当纯输入张量 |
| DMA错误/完成超时 | S2MM先准备、TLAST/TKEEP、包长、Cache、DMASR与CNN错误位 | 保存状态及guard，先停止再排查 |
| logits/FNV/Golden不符 | 同序输入、布局、整数合同、四Golden映射、模型/载荷锁 | 不改参考来掩盖不一致 |
| XSDB PL地址只读被阻止 | 调试器内存映射与目标状态 | 记录为未成功的可选诊断；不伪称寄存器读回成功 |

## 6 验证范围和复用边界

2026-11-02：原冻结模型前三条，ARM/legacyPL/fusedPL共9条正确性记录PASS；独立原始日志和回执另存。
此前已完成同样三条的载荷生成、独立标量、实际C代码和ARM编译。
未验证其他网络、其他板卡、广泛新模型数值、异机重建或新HLS到完整实现。完整源码到实现配方见source-reproduce-r3.md，不等于完整流程已运行。
此技能文档已静态核对、其所引用R3小样本流程已有本机运行记录；尚未以另一使用者/另一环境完成技能试用。

## R3.1文档与锁字段修订

本复核附件绑定R3.1 C02候选；元数据断言已有针对性软件核验。既有真实3条ARM编译/板测仍属于原R3，R3.1未重新编译或上板。C原编号02没有绑定这份外部Skill六文件，不把它解释成Skill缺失于所有材料或已复核通过。
