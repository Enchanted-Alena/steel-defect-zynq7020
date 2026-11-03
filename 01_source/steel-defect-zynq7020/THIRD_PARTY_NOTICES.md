# 第三方来源与依赖

- AMD Vivado/Vitis/HLS、PS7、AXI DMA、其他IP及standalone BSP由用户按适用条款自行安装/生成，不随源码包分发。
- 原cnn_system_bd.tcl和两份vendor PS TSV来源见docs/BOARD_INPUT_ACQUISITION.md；原件不分发，用户合法取得并本地生成。
- 新create_cnn_connections.tcl是团队连接源码，不声明PS芯片、IP、开发板PCB或下载器为团队原创。
- software/lscript.ld保留AMD版权及SPDX MIT；分发时附third_party/MIT-AMD-LINKER.txt。
  来源：https://github.com/Xilinx/embeddedsw/blob/xilinx_v2025.2/scripts/linker_files/lscript_a9.ld.in 。
- NumPy、Pillow、pyserial仅列依赖和wheel哈希，未捆绑其代码或wheel。NumPy自带BSD及其附属声明，Pillow wheel标识MIT-CMU，pyserial为BSD；安装包附带条款继续适用。
- NEU-CLS来源和数据边界见data/README.md，不因根Apache而取得数据/模型再分发权。
- 私有模型、输入、Golden、载荷、原UART及bit/XSA/ELF/DCP均不进入公开源码。

完整源码范围是可获得合法依赖后的工程源流程；其第三方工具/板级输入不被重新许可为团队Apache。
