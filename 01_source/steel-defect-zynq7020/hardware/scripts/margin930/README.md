# margin930 源码构建入口

scripts/rebuild_margin930.py接收Vivado2025.2、新HLS syn/verilog、外部board-inputs及新输出目录。
create_source_project.tcl加载用户本地入口和团队连接脚本，读取本地规范化有效PS表。
系统流程仍为新源码10ns综合、9.300ns临时分析目标实现、恢复10.000ns并独立进程检查setup/hold/TNS/THS/DRC。
audit_restored.tcl只有门槛全部通过才导出bit/XSA，clock_helpers.tcl不改真实FCLK100MHz。

validate_source.tcl可只做BD验证，不综合或布局布线；本轮该层已使用既有HLS RTL实际通过。
完整新HLS到实现/时序入口本轮未运行，不能声称重现原+0.718ns或同一bit/hash。
完整命令和依赖见根REPRODUCE.md；实际状态见docs/VALIDATION_STATUS_R3.md。
