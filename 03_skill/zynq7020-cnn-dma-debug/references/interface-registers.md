# Protocol 2.0简明接口与寄存器表

依据已锁定RTL axi_lite_ctrl.v、cnn_wrapper_dma_bridge.v、正式dma_driver.inc与BD；本轮未执行硬件访问。

## 系统接口

| 接口 | 连接/用途 |
|---|---|
| PS GP0→axi_smc | AXI-Lite控制DMA与CNN寄存器 |
| DMA MM2S | DDR经PS HP0/axi_mem_intercon读出作业包，送入wrapper的s_axis_job |
| DMA S2MM | wrapper的m_axis_result经DMA/axi_mem_intercon_1/PS HP1写回DDR |
| 作业/结果AXI-Stream | TDATA32位，TKEEP4位，TVALID/TREADY背压，TLAST标记包尾 |
| CNN AXI-Lite | 数据32位、WSTRB4位、地址窗口4KiB；基址0x40000000 |
| AXI DMA控制 | 基址0x40400000，64KiB窗口；Simple DMA（SG=0） |
| 时钟/复位 | FCLK0=100 MHz；proc_sys_reset外设复位，复位分发见原BD |
| IRQ | CNN done/error与DMA两路IRQ经xlconcat到PS；正式270性能套件使用轮询，独立ISR套件单独验证IRQ |
| UART | UART0 EMIO，软件基址0xE0000000，115200波特 |

控制器不是HLS默认ap_ctrl寄存器窗口。下面偏移均相对CNN基址0x40000000，4字节对齐。

## CNN寄存器

| 偏移 | 名称 | 访问 | 简明含义 |
|---|---|---|---|
| 0x00 | CONTROL | WO | 命令值：0无操作、1 START、2 ABORT、4清done、8清error、12同时清done/error；其他非零组合返回SLVERR |
| 0x04 | STATUS | RO | bit0 IDLE，bit1 ARMED，bit2 LOADING，bit3 CORE_START/CORE_BUSY，bit4 DRAINING，bit5 done sticky，bit6任意error，bit7 IRQ |
| 0x08 | ERROR_STATUS | RO/W1C | 13位错误状态；W1C仅在IDLE/ERROR允许，受WSTRB掩码影响 |
| 0x0C | IRQ_ENABLE | RW | bit0使能done IRQ，bit1使能error IRQ |
| 0x10 | BATCH/N | RW | 批次N |
| 0x14 | INPUT_CHANNELS | RW | 输入通道Ci |
| 0x18 | OUTPUT_CHANNELS | RW | 输出通道Co |
| 0x1C / 0x20 | HEIGHT / WIDTH | RW | 输入H/W |
| 0x24 / 0x28 | PADDING / ZERO_POINT | RW | padding及零点配置；本冻结模型为pad1、zero point0 |
| 0x2C / 0x30 | EXPECTED_INPUT/OUTPUT_BYTES | RO | 作业包/结果预期字节数；长度流水计算未就绪时可暂缓AR握手，不应固定轮询次数代替超时机制 |
| 0x34 | WATCHDOG_LIMIT | RW | 活跃作业周期看门狗阈值；正式驱动写200000000 |
| 0x38 | CORE_RETURN | RO | HLS核返回码，成功应为0 |
| 0x3C | STATE | RO | 当前内部状态低4位 |
| 0x40–0x6C | 六组64位事件计数 | RO | start、first_in、last_in、core_done、first_out、last_out；每组低32位在前，高32位在后 |
| 0x70/0x74 | INPUT_STALL_CYCLES | RO | 低/高32位 |
| 0x78/0x7C | OUTPUT_STALL_CYCLES | RO | 低/高32位 |
| 0x80/0x84 | ACTIVE_CYCLES | RO | 低/高32位 |
| 0x88 | PROTOCOL_VERSION | RO | 0x00020000 |
| 0x8C | CAPABILITIES | RO | 0x00030102；正式软件按该值核对能力 |
| 0x90 | BUILD_ID | RO | 0x00000001 |
| 0x94 | POST_OP | RW | 0卷积，1卷积+ReLU，2卷积+ReLU+2×2 MaxPool |

0x10–0x28、POST_OP及WATCHDOG配置只在非busy接收；busy写会记录配置写错误，不应边运行边切模式。
两层共用一个核心及控制窗口，Conv1模式1、Conv2模式2；每层仍是独立DMA作业，层间结果经DDR/PS管理。
没有声称两层形成不落DDR的流式直连。

## DMA在正式驱动中使用的偏移

| 偏移 | 寄存器 | 用途 |
|---|---|---|
| 0x00 / 0x04 | MM2S_DMACR / DMASR | 复位、运行与状态检查 |
| 0x18 / 0x28 | MM2S_SA / LENGTH | TX地址及发送字节数 |
| 0x30 / 0x34 | S2MM_DMACR / DMASR | RX运行与状态检查 |
| 0x48 / 0x58 | S2MM_DA / LENGTH | RX地址及预期接收字节数 |

正式操作次序概述：准备TX/RX及guard→Flush→DMA复位/清状态→清CNN状态→配置形状与POST_OP并回读长度→
先准备S2MM→CNN START→MM2S发送→轮询DMA/CNN完成及错误→Invalidate→检查状态/guard/长度/返回码。
该表用于报告理解，不替代完整驱动的超时、错误恢复、AXI包格式和CSR合法性条件。
