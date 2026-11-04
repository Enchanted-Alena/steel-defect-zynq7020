# Skill 快速开始

适用范围：R3.1 源码中的 `zynq7020-cnn-dma-debug` Skill。以下步骤仅生成并核对三条合成接口载荷，不使用真实模型或测试图像，不编译、不连接板卡，也不产生分类准确率或正式成绩。

## 准备

- 使用匹配源码版本的完整工程目录，定位到 `01_source/steel-defect-zynq7020`。
- 使用源码锁文件规定的 Python 3.12 环境及依赖。
- 为合成夹具和载荷输出分别指定新的空目录，且都放在源码树之外。

## PowerShell 操作

```powershell
$repo = 'C:/path/to/01_source/steel-defect-zynq7020'
$work = 'C:/fpga-user-work/skill-fixture'
$python = 'C:/path/to/python.exe'

& $python "$repo/scripts/make_interface_fixture.py" --out "$work/fixture"
& $python "$repo/scripts/generate_user_payloads.py" `
  --compatibility `
  --model "$work/fixture/fixture_model.npz" `
  --contract "$work/fixture/fixture_contract.json" `
  --inputs "$work/fixture/inputs_int8.bin" `
  --index "$work/fixture/index.csv" `
  --out "$work/payload"
& $python "$repo/scripts/verify_user_payloads.py" --payload "$work/payload"
```

每条命令都应返回成功。最后一步应报告 `EIGHT_PAYLOADS_SCALAR_REFERENCE_PASS`、`SampleCount: 3`、`FourGoldenBytewise: true`、`StageFNVLittleEndian: true`；同时 `BoardExecuted` 和 `FormalResultReproduced` 均应为 `false`。

若任一步失败，保留终端输出和生成目录，不要修改 Golden、跳过检查或把测试输入替换成私有正式数据来取得 PASS。排错时按 Skill 的 payload 合同和故障表继续检查；超出离线核对范围时先停止。

## 结果边界

该流程验证合成输入下的载荷格式、整数参考计算和文件身份关系。它不验证训练模型、不代表真实分类、不重现 217/270，不包含 ARM 编译、板端运行、性能或时序验证。需要真实用户模型或板端检查时，另按 Skill 的兼容性流程准备合法输入，并逐项确认该次会话的授权与硬件身份。
