# 工程复现说明静态核对

核对日期：2026-11-04。输入为120项候选`B_SOURCE_SKILL_REPORT_REVIEW_R2_20261104`，ZIP SHA-256：`1d81078efc34f32bd99cd726612957afd492aebbbff58ae140e4c43c160f6246`。本次只读取文档、脚本和已有记录，未执行下表命令，也未重新安装项目依赖、生成载荷、编译或连接板卡。

## 结论

依赖、受限板级输入取得/本地生成、固定量化模型接口、载荷核对、固件编译、兼容硬件运行、预期标记和失败停止均已有文档/脚本入口。已有硬件分支有原模型三样本的执行记录；新硬件全链路和异机完整重建仅有配方，未取得执行证明。合法板级归档能否由新使用者实际取得仍是外部条件，历史网址不是本次下载成功记录。

下面路径均以候选仓库根为准；命令在`01_source/steel-defect-zynq7020`中运行。路径是用户选择的示例，不是作者私人路径。原记录中的实测状态保留原版本归属。

## 前提与依赖

1. Windows x64；完整脚本集使用Python 3.12。B原R3环境为Python 3.12.14、NumPy 2.3.5、Pillow 12.3.0、pyserial 3.5，见`requirements-validation-win-py312.lock`与`TOOLCHAIN_VALIDATION_LOCK.json`。这些是验证环境，非原训练环境的完整导出。
2. 新硬件配方需要合法安装的Vivado/Vitis/Vitis HLS 2025.2及xc7z020支持；固件需要Cortex-A9 ARM GCC 13.3.0及匹配SDT standalone BSP。原记录的编译器可执行文件哈希保留在工具锁中，不按示例安装路径推断版本。
3. 板卡为Smart Zynq SL V1.3B。板级原归档须由用户合法取得，原归档和指定BD条目的SHA必须符合`docs/BOARD_INPUT_ACQUISITION.md`；未取得同版输入时本地准备脚本将拒绝，不能猜DDR/MIO配置。
4. 分类载荷不是任意FP32模型的直接导入：需要合法自备的固定1→4→8量化NPZ、匹配整数合同JSON、连续32×32 INT8输入及顺序CSV。仅有原始图片或其他网络时，须先完成相应数据/模型准备和适配，不能以接口存在声称所有模型自动兼容。
5. 所有输出须为源码树外的新空目录；源码、板级输入、HLS RTL、BSP、载荷、固件和运行目录按脚本要求保持分离。板测还须满足本轮会话授权、连接/供电及串口/JTAG独占条件。阅读本材料不构成新增运行授权。

```powershell
# 在源码目录中准备本次工作环境；本材料未执行这些命令。
$work = 'C:/fpga-user-work'
py -3.12 -m venv "$work/venv"
$python = "$work/venv/Scripts/python.exe"
& $python -m pip install --require-hashes -r requirements-validation-win-py312.lock
# 工具路径由使用者指向其合法安装位置。
$vivado = 'C:/AMD/2025.2/Vivado/bin/vivado.bat'
$vitisRun = 'C:/AMD/2025.2/Vitis/bin/vitis-run.bat'
$gcc = 'C:/AMD/2025.2/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
```

## 步骤、预期输出和执行证据

| 步骤 | 文档/脚本入口与输入 | 预期输出或检查 | 已实际执行的范围 | 尚未完成或失败处理 |
|---|---|---|---|---|
| 0. 依赖及文件身份 | REPRODUCE.md依赖节、requirements锁、根/内层SHA | 依赖安装按wheel哈希；脚本/输入身份可查 | 原R3安装及导入记录、历次完整性核对 | 本轮未重新安装；原训练机器完整环境与终端日志仍缺 |
| 1. 板级输入取得与本地生成 | docs/BOARD_INPUT_ACQUISITION.md；scripts/prepare_board_inputs.py；供应商同版ZIP | 本地cnn_system_bd.tcl、vendor_ps_parameters.tsv、board_input_lock.json；状态LOCAL_PS_PARAMETERS_AND_TEAM_BD_ENTRY_PREPARED_NO_IMPLEMENTATION | 原R3对既有合法原归档完成355项PS参数核对 | 未证明新用户能匿名下载；未知归档/BD哈希拒绝，先补合法同版输入 |
| 2. PS规范化与BD连接 | hardware/scripts/normalize_local_ps.tcl、margin930/validate_source.tcl | 本地vendor_2025_2_effective.tsv；关键DDR/MIO等参数核对；BD校验 | 既有HLS RTL下实际通过；不是新HLS全链路 | 工具退出失败保存日志；不把BD校验当作综合/实现通过 |
| 3. 重新生成HLS RTL | hardware/hls_source/rebuild_fused_hls.py；公开C++/头文件及合成测试平台 | CSim、CSynth、RTL协同仿真/IP导出日志，新project/solution1/syn/verilog和build_record.json | 当前便携入口从干净树运行的新记录未取得 | 配方；HLS失败停止，不拿历史RTL冒充本次新生成 |
| 4. 新系统margin930实现 | scripts/rebuild_margin930.py；新HLS RTL、本地板级锁和公开RTL/XDC | 10 ns综合、9.300 ns实现、恢复10.000 ns；独立进程setup/hold/DRC审计；门槛通过才导出bit/XSA | 有历史冻结工件的正式审计；不是本入口完整重建记录 | 配方；WNS≥0.500、WHS≥0、TNS/THS=0、失败端点0、DRC Error=0任一不满足则停止，不降门槛 |
| 5. 新XSA到BSP | scripts/create_standalone_bsp.py；新XSA | A9 32-bit standalone SDT域、BSP库/头、ps7_init.tcl、bsp_record.json | 原编译使用既有匹配BSP | 新BSP入口配方未执行；不能将旧BSP编译成功写成新BSP生成成功 |
| 6. 用户模型/载荷 | scripts/generate_user_payloads.py --compatibility；NPZ/JSON、INT8和index.csv | 三头文件、四Golden、stage FNV共八载荷，以及输入身份与锁 | 原R3合成三条、授权原模型同序前三条已有记录 | 整数合同/形状/顺序不符停止；默认270离线分支与兼容分支不混用 |
| 7. 独立核对与编译 | verify_user_payloads.py；build_user_firmware.py；可选verify_user_cpu.py | EIGHT_PAYLOADS_SCALAR_REFERENCE_PASS；匹配BSP下user_model_compatibility.elf及map、命令/版本/输入哈希 | 原R3合成/真实前三条标量、固件C核对及ARM编译记录；R3.1补锁字段的软件核验另列 | 本轮未重编译；独立verifier强制先于编译，FAIL不修改Golden绕过 |
| 8. 已有兼容硬件运行 | lock_compatible_hardware.py、run_user_compatibility.py；原匹配硬件和专用ELF | 专用PASS、3N条数值/状态记录及原UART/JTAG/会话锁；无正式性能声明 | 2026-11-02原模型输入0/1/2、三路径共9条正确性记录 | 不证明其他模型；输入身份/协议/超时/guard不符停止、保存现场及停核 |
| 9. 真人Skill离线试用 | 03_skill/README.md及QUICKSTART、independent-trial-form.md | 未编写者实际生成合成三条、保存日志并填写试用表 | A提供过一次合成摘要；C02有软件复核，二者均不能自动替代本Skill真人试用 | 当前独立试用未完成，表未代填；不能写成已完成或异机全链路重建 |

## 两条操作分支

### A. 已有兼容硬件的小样本流程

这条路线使用原匹配bit/XSA/PS init/BSP，不先运行HLS或新实现。合法模型与输入按接口准备后：

```powershell
& $python scripts/generate_user_payloads.py --compatibility --model "$work/user/model.npz" --contract "$work/user/contract.json" --inputs "$work/user/inputs_int8.bin" --index "$work/user/index.csv" --out "$work/payload"
& $python scripts/verify_user_payloads.py --payload "$work/payload"
& $python scripts/build_user_firmware.py --gcc $gcc --bsp "$work/sdk/bsp" --payload "$work/payload" --out "$work/firmware"
# 以下两条仅在当前硬件/输入范围授权及连接条件满足后执行。
& $python scripts/lock_compatible_hardware.py --bit "$work/hw/system.bit" --xsa "$work/hw/system.xsa" --ps7-init "$work/hw/ps7_init.tcl" --bsp "$work/sdk/bsp" --out "$work/hardware-lock.json" --confirm-compatible-hardware
& $python scripts/run_user_compatibility.py --xsdb 'C:/AMD/2025.2/Vitis/bin/xsdb.bat' --hardware-lock "$work/hardware-lock.json" --build "$work/firmware" --payload "$work/payload" --port COM8 --out "$work/board-run" --confirm-current-board-session
```

COM8仅为示例，应替换为当前实际枚举且可独占的板卡端口。只有1～16条受支持的兼容任务可用这条分支；输出是一次小样本正确性pass，不运行正式270套件。`BoardExecuted=false`是离线核对状态，不代表已上板；专用板测PASS也不代表正式准确率或性能复现。

### B. 从干净源码重建新硬件的配方

仅在取得新硬件构建授权后，从合法板级输入和公开源开始：

```powershell
& $python scripts/prepare_board_inputs.py --archive "$work/inputs/08_PS_UART_TEST.zip" --out "$work/board-inputs" --confirm-lawful-local-use
& $python hardware/hls_source/rebuild_fused_hls.py --vitis-run $vitisRun --out "$work/hls"
& $python scripts/rebuild_margin930.py --vivado $vivado --hls-rtl "$work/hls/project/solution1/syn/verilog" --board-inputs "$work/board-inputs" --out "$work/system"
# 需在Vitis 2025.2环境中运行；本轮未验证该新BSP步骤。
vitis -s scripts/create_standalone_bsp.py --xsa "$work/system/audit_export/margin930_rebuilt_100mhz.xsa" --out "$work/sdk"
```

随后才可用新匹配硬件/BSP继续分支A。HLS的8 ns综合目标、系统实际FCLK100 MHz、实现阶段9.300 ns分析目标是三个不同设置。新结果可能改变布局、时序和工件哈希，不能自动沿用正式成绩。以上串联是说明和脚本层面的连贯配方，不是已经执行的新硬件闭环或异机验证。

## 模型与八载荷接口的必要检查

- 模型键：q_w1[4,1,3,3]、q_w2[8,4,3,3]、q_w3[6,2048]，两层bias_int/M/shift，以及b3_int[6]。NPZ无pickle整数数组；JSON需与整数数组和逐层尺度一致。
- 输入：每条1024字节、NCHW单通道INT8，顺序CSV的idx连续且与二进制连接顺序一致；兼容分支样本数1～16。禁止以任意图片文件直接代替INT8张量。
- 八文件：model_params.h、board_vectors.h、batch_data.h、conv1_golden_int8.bin、conv2_golden_int8.bin、fused_conv1_relu_golden_int8.bin、fused_conv2_relu_pool_golden_int8.bin、batch_fused_stage_fnv。
- 四份Golden每样本长度分别4096、8192、4096、2048字节；FNV每样本为三项小端uint32，顺序ReLU1、Pool、六个小端INT32 logits。不能拿四份Golden的文件顺序替代三项FNV的阶段顺序。
- 整数语义：INT32模2^32累加、INT64重定量化乘积、向偶数舍入、INT8饱和及既定零点；分类头输出6项INT32，argmax并列取最小索引。Python参考的中间位宽与板端C实现可不同，但输出规则需相同。

## B提出的问题与本次处理

1. **必须修正，PUB_RESULTS第一段**：`The same bound Protocol 2.0 bit/XSA/ELF set was used for ISR smoke and the fixed 270-sample run.`与P2_BINDING中不同suite_elf、smoke_elf哈希矛盾。应改为：`ISR smoke and the fixed 270-sample run used the same bound Protocol 2.0 bit/XSA and PS initialization, with separate smoke and full-suite ELF files. Their identities are retained in the private artifact-binding record.`
2. **状态残留，PUB_PAYLOAD第3行**：仍以C02 HOLD及“本修订仍需差分复核”为当前状态。建议区分：原R3.1后由C04精确复核；当前120项R2为本次输入基线；本轮A侧助手接手核对并提供文档修订，尚待B封装新集合。载荷接口/历史执行结论不变，勿将其写成本轮重测。
3. **报告提交规则更新**：根README、AI Markdown及旧交接中的“官网与仓库须同版/同一内容文件”属于此前要求。A已明确允许不同结构和篇幅，后续统一改为“核心事实、成绩、统计口径和验证边界一致”，不要求字节相同或页数相同；旧归档中的历史版本记录保留。
4. **证据可访问性**：报告[7]提到的SOURCE_CATALOG.csv/SOURCE_INDEX.csv、[10]的02_uart_excerpts/LINE_SOURCE_MAP.csv不在当前120项候选；[8]所述旧协作文字也不是当前仓库的同名附件。后续要么由A/C将经过审查的公开汇总实际纳入，要么标为私有证据及身份索引，不能声称仓库已包含。Skill入口和当前report/ai_collaboration_log.md确实在候选中。
5. **取得条件仍未实证**：供应商历史归档的合法取得步骤已写明，但新用户能否取得指定哈希同版输入、Vitis新BSP入口及完整异机重建均未验证。不能只凭“源码范围完整”写成clean-clone全流程通过。

B原补充没有修改120项候选。A侧本次在增量中修正MARGIN930_RESULTS、PAYLOAD_INTERFACE、根README和既有AI摘要的当前说明，纳入来源索引及新Markdown主稿。原候选及旧归档保留。此索引的命令为B提供的操作配方；A侧未执行新增硬件、ARM编译或板测命令。最终整包及内外清单仍须由B更新。A侧本次18项软件检查另见[核对记录](validation/software_review_20261104.md)。

## 是否必须新增实验

完成本轮限定陈述无需新增实验。若未来要宣称“完整新硬件重建已通过”“异机复现已通过”“所有替代划分比较后最优”或“DDR已饱和”，则分别需要独立重建记录、异机完整执行、受控架构对照或DDR测量。本次未授权或执行这些验证，也未将相应结论写入合入稿。
