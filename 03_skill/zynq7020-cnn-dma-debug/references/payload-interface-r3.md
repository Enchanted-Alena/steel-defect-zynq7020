# 八文件固件输入接口

状态：R3 已用3条合成接口用例完成生成、独立标量核对、实际固件C算法主机执行及ARM ELF编译；用户授权的此前模型3条输入已完成内部离线核对/编译，并在原R3打包后以既有兼容硬件完成三路径9条正确性补测PASS。C编号02已完成原R3首次独立复核，结论HOLD_FOR_DOCUMENT_FIXES；本修订仍需差分复核，不代表其他模型泛化或正式成绩重测。

## 默认270条离线模式的输入与固定合同

输入用户模型NPZ、对应JSON合同、270条量化输入及顺序CSV。INT8、NCHW、每条1×1×32×32，
两层1→4→8、3×3、stride1、pad1，权重OIHW，zero point和padding value均0。

Conv1 requant后ReLU作为Conv2输入，Conv2 requant后ReLU+2×2 MaxPool，C/H/W顺序展平2048项，
FC2048→6及argmax。INT32累加回绕、requant向偶数舍入后饱和INT8；FC最后回绕INT32，argmax并列取最小索引。
转换器复用C已确认的int8_reference和packet_v1，不增加训练/量化算法。

NPZ键：q_w1[4,1,3,3]、q_w2[8,4,3,3]、q_w3[6,2048]、bias_int_1/2、M1/2、shift1/2、b3_int[6]。
JSON与NPZ的bias/M/shift、FC bias与中间尺度必须一致，否则停止。CSV的idx0..269、label0..5；
标签不参与Golden计算，也不据此输出正式准确率。

NPZ是NumPy可读取的无pickle整数数组文件。bias_int_1/M1/shift1形状[4]，
bias_int_2/M2/shift2形状[8]，b3_int形状[6]；不得以浮点数组代替整数数组。
权重范围[-128,127]，bias为signed INT32，M为[0,2147483647]，shift为[0,62]。

JSON采用现有train_quantize_eval导出的结构，而不是另起一套配置格式：

- architecture是按顺序排列的7项：hconv、ps_relu、hconv、ps_relu、ps_maxpool2x2、ps_fc、ps_argmax。
- 两个hconv项需含shape=[1,ci,co,32,32,1,0]、K=3、stride=1、pad=1、bias_int/M/shift、
  weight_scale_per_channel[co]、正有限s_in/s_out；第二层s_in必须等于第一层s_out。
- ps_maxpool2x2项out_shape=[1,8,16,16]；ps_fc项shape=[2048,6]、bias_int与b3_int一致。
- integer_contract中的input_zero_point、weight_zero_points、padding_value、output_zero_point均为整数0。
- 此处描述适配器实际读取字段；其余历史元数据不会被当作已验证训练记录。

inputs_int8.bin为270×1024=276480字节，按CSV行位置连接，无头；CSV至少含idx,label列，
必须有270行、idx连续0..269、label为0..5。适配器绑定整份输入和CSV的SHA-256，
可选input_sha256列如提供则逐条校验；生成清单无论该列是否存在均记录每条输入SHA-256。来源ID和外观来源仍由用户负责，不根据哈希推断实体来源。
输出均直接位于命令的--out新目录，不建立隐含层级或覆盖输入；头文件是ASCII文本，长度随模型数值而变。

## 默认270条模式的精确输出

| 文件 | 固件内容/符号 | 布局或长度 |
|---|---|---|
| model_params.h | model_weights_0/1、model_bias_0/1、model_mult_0/1、model_shifts_0/1、fc_weights、fc_bias | 卷积OIHW及FC[输出类,2048]扁平数组 |
| board_vectors.h | payload_0/1、golden_0/1、Job、jobs[2] | 两层基线作业载荷与描述，不是文件名列表 |
| batch_data.h | batch_inputs[270][1024]、batch_logits[270][6]、batch_predictions[270] | BATCH_DATA_FORMAL0、USER_PAYLOAD_OFFLINE_ONLY1 |
| conv1_golden_int8.bin | batch_conv1_golden | 270×4096=1105920字节，requant后/ReLU前 |
| conv2_golden_int8.bin | batch_conv2_golden | 270×8192=2211840字节，requant后/ReLU前，输入为ReLU1 |
| fused_conv1_relu_golden_int8.bin | batch_fused_conv1_relu_golden | 270×4096=1105920字节 |
| fused_conv2_relu_pool_golden_int8.bin | batch_fused_conv2_relu_pool_golden | 270×2048=552960字节 |
| batch_fused_stage_fnv | batch_fused_stage_fnv | 270×3×4=3240字节，小端uint32，无扩展名 |

INT8二进制无头无分隔，按样本顺序连接。每条FNV记录依次覆盖ReLU1的4096字节、Pool的2048字节、
六个小端INT32 logits的24字节。FNV-1a32：初值0x811C9DC5、乘子0x01000193，每字节异或再乘且模2^32。
不是旧六阶段表，也不对数组文本求FNV。

Job字段保持dma_driver.inc顺序：n,ci,co,h,w,p,z,tx_bytes,rx_bytes,input_offset,input_bytes,parent,payload,golden。
parent为-1、0，流载荷沿用packet_v1的32bit对齐格式。Protocol2 POST_OP通过CSR配置：Conv1模式1、
Conv2模式2，legacy两层模式0。POST_OP不写进流载荷，不改变CSR地址。

## 锁及公开边界

额外输出user_input_manifest.json、user_payload_lock.json、user_baseline_lock.json和私有标记。
payload lock的Files精确覆盖八文件，SampleCount270、ProtocolVersion0x00020000、
PayloadPurpose=USER_MODEL_OFFLINE_DEMO、DoNotProgram=true。baseline lock覆盖三头文件和两份legacy Golden。
这是用户自己生成内容的绑定，不是原正式冻结锁或C批准记录。

builder默认拒绝用户演示锁；显式--demo-offline才用于离线编译，输出名称和横幅均区别正式套件。
原始main.c未改，只在树外构建副本替换横幅。演示ELF不据此直接上板。
所有输出均可能含受限模型、输入和派生数值，留在树外私有目录，不自动进入公开白名单。
不承诺任意网络/样本数、重新训练得到217/270或异机bit/hash一致。

## R3 小样本兼容性分支

显式 --compatibility 接受 N=1..16 条，输入 N×1024 字节；CSV必须有N行，idx连续0..N−1。
模型NPZ键、整数合同、权重布局、四Golden的阶段及三阶段FNV顺序完全相同。
不带该开关仍只接受270条，保留原离线限制。

| 内容 | 小样本分支 |
|---|---|
| batch_inputs / logits / predictions | [N][1024] / [N][6] / [N] |
| 四Golden长度 | N×4096、N×8192、N×4096、N×2048 B |
| FNV长度 | N×3×4 B，小端uint32 |
| batch_data标记 | BATCH_DATA_FORMAL=0、USER_PAYLOAD_OFFLINE_ONLY=0、USER_PAYLOAD_COMPATIBILITY=1 |
| 锁 | PayloadPurpose=USER_MODEL_COMPATIBILITY、SampleCount=N、FormalFrozenReplay=false、DoNotProgram=false、NeedsExplicitBoardSession=true |
| 专用编译 | build_user_firmware.py，不调用正式270 main.c |
| 专用固件 | user_model_compatibility.elf、独有USER_MODEL_COMPATIBILITY_NOT_FORMAL横幅 |
| 运行范围 | 三路径各N次正确性核对；无正式性能重复扫描、无217/270准确率声明 |

DoNotProgram=false 只表示该分支可由专用入口处理，不代表已获本次上板确认或已验证硬件。
独立 verify_user_payloads.py 用标量卷积、Python整数回绕/RNE、显式2×2窗口与独立包拼接核对八文件；
verify_user_cpu.py 编译并执行实际 software/model_ops.c，与四Golden及FNV逐项核对。
build_user_firmware.py 强制检查八文件锁/长度/标记及独立标量结果后才编译。

兼容分支的附加文件为 user_input_manifest.json、user_payload_lock.json、user_baseline_lock.json、PRIVATE_USER_PAYLOAD.txt。
清单记录NPZ/合同/原始输入/索引、参考源码、生成器及每条输入的哈希；锁绑定清单和八文件。
所有路径和生成数值保存在树外；公开源码仅含生成/核对方法及合成刺激创建脚本。
