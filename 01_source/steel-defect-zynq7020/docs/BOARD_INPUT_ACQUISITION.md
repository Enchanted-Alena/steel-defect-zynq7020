# 板级输入来源及用户本地生成

A已决定：不能确认再分发条件的第三方/工具生成输入不随公开源码分发，改为合法取得步骤与用户本地生成。
本版据此去除了原三个文件；不是把它们改名、压缩、编码后重新发布。

## 逐项来源与处理

| 历史文件 | 具体来源 | 已确认的再分发许可 | R3替代/获取方法 |
|---|---|---|---|
| hardware/scripts/cnn_system_bd.tcl | 团队集成BD经Vivado2025.2 write_bd_tcl导出；含工具框架及本地板级配置调用 | 未取得覆盖整份历史导出文件的明确依据，未套用团队Apache | 本地prepare_board_inputs生成同名入口，调用公开团队create_cnn_connections.tcl；用户再运行Vivado从干净源建立BD |
| hardware/reference/vendor_ps_parameters.tsv | HelloFPGA Smart Zynq SL UART例程ZYNQ.bd的355项PS参数 | 原归档未发现项目级明确公开许可；未将公开下载等同于再分发授权 | 用户合法取得原归档，Python校验身份后本地读取该JSON条目生成TSV |
| hardware/reports/vendor_2025_2_effective.tsv | 旧迁移流程将上述参数导入Vivado2025.2后遍历CONFIG.*导出 | 原输入和工具条件均保留，未作独立再分发许可结论 | 用户用normalize_local_ps.tcl本地生成；无预生成TSV进入公开包 |

新 create_cnn_connections.tcl 是依据团队集成拓扑及公开API整理的连接源码，不复制历史BD导出框架。
AMD IP、PS7、工具和BSP由用户按其安装/授权条件取得；根Apache许可不扩张到这些工具或生成物。

## 原归档身份及获取步骤

1. 向开发板供应商取得 Smart Zynq SL V1.3B 对应PS UART参考例程，核对适用板卡修订及本地使用条件。
2. 历史官方板卡页：http://www.hellofpga.com/index.php/2023/05/10/smart-zynq-sl/ 。
3. 历史官方归档地址：http://www.hellofpga.com/wp-content/uploads/2023/04/08_PS_UART_TEST.zip 。
4. 如果网址不可用，从购买随附资料或向供应商索取同版归档及适用条件，不从不明镜像自动下载。
5. 确认有权在本地使用；若无法确认，应向供应商询问。脚本确认开关不是供应商授权，也不授予再分发权。
6. 归档SHA-256须为 db2d96bb8406bafb67f6b57b5b5b80dd476bf88a498105ac39d653c1a2323b15。
7. JSON BD条目为08_PS_UART_TEST/UART_TEST/UART_TEST.srcs/sources_1/bd/ZYNQ/ZYNQ.bd，SHA-256为f6dc792f2f3ecc58a5d73fe9f72146692cefe76f21986c7bb6b41e15ff836eeb。
8. 使用REPRODUCE.md第1步生成本地文件，再用已合法安装的Vivado2025.2规范化并重建BD。

2026-11-02检查时官方主页访问超时；公开来源链接的记录不等于保证此刻可下载，亦不等于许可证据。
归档本身、其BD/TSV和本机生成项目均未加入公开包。若供应商仅能提供不同版本，应另行核对板级配置和身份；
当前脚本会拒绝未知归档，不猜DDR时序、MIO、电压或引脚，不借用正式成绩。

## 已有本地生成核对

本轮按该路线读取现有原归档：355项请求参数与历史输入逐项一致。
Vivado2025.2实际本地导出879行有效配置；与历史有效表仅Component_Name因新设计名而不同。
DDR/MIO/QSPI/UART/crystal参数一致。团队新连接脚本加既有HLS RTL实际通过BD校验。
这不等于新HLS综合、系统综合或时序/板测已通过。

## 工具与API资料

- Vivado2025.2 write_bd_tcl：https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/write_bd_tcl
- AMD IP许可入口：https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/license.html
- 工具许可账户/协议查看：https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/licensing-faq.html

应以用户实际取得的工具/IP/板卡材料所附条款为准，本说明不根据另一AMD软件产品的EULA推断Vivado适用条款。
