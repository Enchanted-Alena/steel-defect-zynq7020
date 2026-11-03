# 构建与用户验证入口

完整命令和依赖见../REPRODUCE.md；实际状态见../docs/VALIDATION_STATUS_R3.md。

- prepare_board_inputs.py：合法原归档到用户本地PS参数及团队BD入口。
- rebuild_margin930.py：新HLS RTL、外部本地PS输入到完整margin930候选，最后独立100MHz审计导出。
- create_standalone_bsp.py：用户XSA到匹配standalone BSP，待首次执行。
- generate_user_payloads.py：默认270离线；显式--compatibility为1..16条独立正确性载荷。
- verify_user_payloads.py / verify_user_cpu.py：独立标量和实际固件C代码核对。
- build_user_firmware.py：小样本专用ARM ELF编译，不运行正式270。
- lock_compatible_hardware.py / run_user_compatibility.py：本地身份锁及需当前会话确认的上板入口；原R3后续已有原模型3条补测PASS，本修订未重跑板测。
- build_fused_firmware.py：保留私有正式重放/原离线分支的锁检查，不用于新用户小样本运行。

不把载荷生成、编译或合成解析日志写成新的板测或正式成绩。
