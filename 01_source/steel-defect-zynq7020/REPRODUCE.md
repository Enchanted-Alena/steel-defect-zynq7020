# 从源码到用户兼容性运行

## 目标及边界

复现固定模型接口下的工程流程，不承诺重新训练同一权重、相同 bit/hash 或正式 217/270。
正式结果仍属于原冻结工件及 2026-10-28 轮次。
本版没有重跑 HLS、综合、布局布线、正式时序或 270 样本板测。
完成情况见 docs/VALIDATION_STATUS_R3.md，不能把配方齐备写成已经端到端运行通过。

## 依赖

- Windows x64；完整脚本集要求Python3.12。B原R3验证使用Python3.12.14、NumPy2.3.5、Pillow12.3.0、pyserial3.5。
- 历史项目文档记录的3.12.7/1.26.4/10.4.0与45epochs命令不等于原机器环境导出，见docs/ENVIRONMENT_RECORD_STATUS.md。
- requirements-validation-win-py312.lock 固定版本及 wheel SHA-256；它是本轮验证锁，不是历史训练环境。
- Vivado/Vitis/Vitis HLS 2025.2，器件支持 xc7z020clg484-1，合法工具/IP许可。
- Cortex-A9 ARM GCC 13.3.0，Vitis SDT standalone BSP；可选主机 GCC 14.2.0 用于 C 交叉核对。
- 板卡为 Smart Zynq SL V1.3B。其他板卡的 DDR/MIO/引脚不得照搬。
- 用户合法自备板级参考归档或由供应商交付的同一版本；详见 BOARD_INPUT_ACQUISITION。
- 自备量化模型 NPZ、匹配 JSON 合同、INT8 输入和顺序 CSV；不自动下载私有模型或数据。

以下路径是用户自选示例；在源码根目录执行，所有输出在仓库外新目录。

```powershell
$work = 'C:/fpga-user-work'
py -3.12 -m venv "$work/venv"
$python = "$work/venv/Scripts/python.exe"
& $python -m pip install --require-hashes -r requirements-validation-win-py312.lock
# 将工具变量设为本机合法安装位置，不复制工具到仓库。
$vivado = 'C:/AMD/2025.2/Vivado/bin/vivado.bat'
$vitisRun = 'C:/AMD/2025.2/Vitis/bin/vitis-run.bat'
$gcc = 'C:/AMD/2025.2/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
```

## 1 板级输入本地生成

```powershell
& $python scripts/prepare_board_inputs.py --archive "$work/inputs/08_PS_UART_TEST.zip" --out "$work/board-inputs" --confirm-lawful-local-use
```

输入 ZIP 只按固定条目读取 JSON，不解压工程或执行其脚本；校验归档/BD SHA-256。
输出 vendor_ps_parameters.tsv、cnn_system_bd.tcl 和 board_input_lock.json。
新的 cnn_system_bd.tcl 是调用仓库团队连接脚本的本地入口，不复制历史工具导出框架。
规范化 vendor_2025_2_effective.tsv 在第 3 步由用户安装的 Vivado 本地生成；原三项均不随公开包分发。

## 2 新 HLS RTL

```powershell
& $python hardware/hls_source/rebuild_fused_hls.py --vitis-run $vitisRun --out "$work/hls"
```

输入为公开 int8_conv3x3.cpp/.h 及 test_fused_extended.cpp；运行 CSim、CSynth、RTL 协同仿真和 IP 导出。
输出 project/solution1/syn/verilog/*.v、IP ZIP、各阶段日志及哈希记录。
HLS 8 ns 综合目标与系统实际 FCLK100 MHz、后续实现分析周期是三个独立设置。
重建脚本只规范化本地新 HLS 工程的源文件路径，不改生成 RTL。

## 3 margin930 实现及独立恢复约束审计

```powershell
& $python scripts/rebuild_margin930.py --vivado $vivado --hls-rtl "$work/hls/project/solution1/syn/verilog" --board-inputs "$work/board-inputs" --out "$work/system"
```

入口不读取 C0 DCP、私人绝对路径或预先生成的大工程，先检查本地输入锁，再依次：

1. 用 Vivado 2025.2 导入 355 项 PS 参数，生成 local_ps/vendor_2025_2_effective.tsv。
2. 读取新 HLS RTL、源码 RTL、团队连接脚本、板级本地输入及 XDC，建立干净 BD。
3. 核对 DDR/MIO/QSPI/UART/crystal 关键配置，实际 FCLK0 保持 100 MHz；新源码综合使用原 10 ns。
4. 打开新综合设计，在 opt_design 前将分析目标临时改为 9.300 ns；同一时钟源、jitter 0.300 ns 保持。
5. opt Explore → place Explore → phys_opt Explore → route Explore → post-route phys_opt。
6. 恢复 10.000 ns 与 0/5 ns 波形，保存 implementation/restored_100mhz.dcp。
7. 新 Vivado 进程独立重开该 DCP，核对器件、唯一时钟源、周期、波形和 jitter。
8. 输出 min/max timing summary、前10条 setup/hold、资源、route、fanout、exceptions、check_timing、DRC。
9. 仅当 WNS≥+0.500 ns、WHS≥0、TNS/THS=0、setup/hold失败端点0、DRC Error=0，才导出 bit/XSA。

输出 audit_export/cnn_system_wrapper.bit、margin930_rebuilt_100mhz.xsa、完整日志及 build_record.json。
任何门槛失败均 STOP；不降低门槛、不叠加新优化、不覆盖失败目录。新结果可能与正式布局/时序不同。
本轮未执行此综合/实现/导出入口，以上是待运行配方，不是新时序报告。

可选仅 BD 校验入口（不综合、不布局布线；须先有本地规范化 TSV）：

```powershell
& $vivado -mode batch -source hardware/scripts/normalize_local_ps.tcl -tclargs "$work/board-inputs" "$work/ps-only"
& $vivado -mode batch -source hardware/scripts/margin930/validate_source.tcl -tclargs --hls-rtl "$work/hls/project/solution1/syn/verilog" --board-inputs "$work/board-inputs" --board-effective "$work/ps-only/vendor_2025_2_effective.tsv" --out "$work/bd-only"
```

## 4 XSA 到匹配 BSP

在已配置的 Vitis 2025.2 环境运行：

```powershell
vitis -s scripts/create_standalone_bsp.py --xsa "$work/system/audit_export/margin930_rebuilt_100mhz.xsa" --out "$work/sdk"
```

生成 Cortex-A9 32-bit standalone SDT 域、bsp/、同 XSA 的 ps7_init.tcl 与 bsp_record.json。
需 Xilinx.spec、xparameters.h、libxilstandalone.a、libxiltimer.a、libxil.a。
此新 BSP 入口本轮未执行；验证编译使用的是原正式固件实际采用的既有 BSP，不能写成新 BSP 生成成功。
已有兼容硬件用户可直接提供其原匹配 BSP，但须保留 XSA/BSP 来源记录，不能仅凭路径名匹配。

## 5 用户数据和模型到八文件

兼容性分支只接受 1～16 条；固定 Conv1→ReLU→Conv2→ReLU→Pool→FC→argmax，1→4→8，FC2048→6。
NPZ/JSON 键、布局、整数范围、样本序和输出定义详见 docs/PAYLOAD_INTERFACE.md。

```powershell
& $python scripts/generate_user_payloads.py --compatibility --model "$work/user/model.npz" --contract "$work/user/contract.json" --inputs "$work/user/inputs_int8.bin" --index "$work/user/index.csv" --out "$work/payload"
& $python scripts/verify_user_payloads.py --payload "$work/payload"
& $python scripts/build_user_firmware.py --gcc $gcc --bsp "$work/sdk/bsp" --payload "$work/payload" --out "$work/firmware"
```

输出 user_model_compatibility.elf、map、八文件锁、输入身份、源码/BSP哈希、编译命令和日志。
独立验证器不调用生成器的卷积参考，逐字节检查四Golden和三阶段FNV；编译前强制运行它。
固件仅做一次小样本三路径正确性比较，不跑正式270套件，不计算或替换正式准确率/延迟。
原 main.c、正式 builder 与旧离线270分支保留；新用户固件独立命名和横幅，不解除正式锁检查。

## 6 合成接口自检

```powershell
& $python scripts/make_interface_fixture.py --out "$work/fixture"
& $python scripts/generate_user_payloads.py --compatibility --model "$work/fixture/fixture_model.npz" --contract "$work/fixture/fixture_contract.json" --inputs "$work/fixture/inputs_int8.bin" --index "$work/fixture/index.csv" --out "$work/fixture-payload"
& $python scripts/verify_user_payloads.py --payload "$work/fixture-payload"
& $python scripts/verify_user_cpu.py --cc 'C:/mingw/bin/gcc.exe' --payload "$work/fixture-payload" --out "$work/cpu-check"
```

fixture 是非训练的数值接口刺激，含溢出、负值、移位0/62等分支。CSV标签仅满足接口格式，不是真实分类标签。
它用于工具链与接口核对，不能作为用户真实模型的验证、模型准确率或正式结果复现证据。

## 7 现有兼容硬件上板

条件：当前板卡连接/供电、独占JTAG/串口和本轮运行确认；已匹配 bit/XSA/PS init/BSP；Protocol2.0。
启动前固件读取0x88/0x8C/0x90，要求0x00020000/0x00030102/1；不匹配立即停止，不启动DMA。

```powershell
& $python scripts/lock_compatible_hardware.py --bit "$work/hw/system.bit" --xsa "$work/hw/system.xsa" --ps7-init "$work/hw/ps7_init.tcl" --bsp "$work/sdk/bsp" --out "$work/hardware-lock.json" --confirm-compatible-hardware
& $python scripts/run_user_compatibility.py --xsdb 'C:/AMD/2025.2/Vitis/bin/xsdb.bat' --hardware-lock "$work/hardware-lock.json" --build "$work/firmware" --payload "$work/payload" --port COM8 --out "$work/board-run" --confirm-current-board-session
```

锁工具校验 bit/PS init 与 XSA 内文件一致；BSP关联仍需原来源记录，不能用用户声明取代硬件证明。
运行工具检查八文件、ELF、硬件锁和BSP哈希后才接触板卡；仅易失JTAG下载，不写flash。
保存原始UART/JTAG日志、输入/工件哈希、每条预测/logits/FNV、DMA/guard及会话结论。
串口解析检查独有PASS、3N条无重无漏记录、原始数值与载荷一致；超时或错误立即保存现场并停核。
这些日志和 ELF 含用户数据，不自动进入公开源码。此入口在原R3打包后已完成原模型同序前三条的独立兼容性上板PASS；本修订不重新编译或板测，既有结果不自动证明其他模型或本次源码完整重建。

## 安全与尚未验证事项

所有生成/编译/工具输出必须是树外新目录，不覆盖冻结工件或旧失败目录。
不接受任意网络、图片尺寸、零点、非匹配BSP或超过16条的兼容性任务。
不运行正式270、性能测试或HLS/Vivado实现来完成用户小样本兼容性验证。
源码和命令齐备不等于完整流程已运行；原模型三条的载荷/编译/补充板测已有记录；其他模型泛化、干净源码新HLS到最终实现、新BSP生成和异机重建仍待验证。
