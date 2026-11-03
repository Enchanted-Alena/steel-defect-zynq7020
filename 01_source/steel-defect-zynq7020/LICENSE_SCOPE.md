# 许可范围

团队既有Apache-2.0声明适用于有权授权的团队源码和文档；根LICENSE正文保持不变。
software/lscript.ld保留AMD版权及MIT标识，附third_party/MIT-AMD-LINKER.txt，不改成团队Apache。
新增连接/导入/用户载荷验证入口属于本轮团队工程源码整理，来源逐文件列于SOURCE_PROVENANCE_LICENSE_REVIEW.csv。

原cnn_system_bd.tcl与两份vendor PS TSV未随公开包分发，不能以根LICENSE替代其上游条件。
它们改由用户合法取得参考资料并本地生成，具体来源、身份、步骤和限制见docs/BOARD_INPUT_ACQUISITION.md。
本地生成物、第三方工具/IP/BSP、用户模型/数据、派生数值、原始UART及硬件二进制不自动取得公开许可。

仅分发源码和依赖声明，未捆绑AMD工具、BSP、IP生成RTL、NumPy/Pillow/pyserial实现或wheel。
NumPy wheel有BSD及其随附依赖声明；Pillow wheel标识MIT-CMU；pyserial标识BSD，使用者保留安装包自带条款。
完整精确公开集合见RELEASE_FILE_WHITELIST.csv及RC_SHA256SUMS.txt。
