"""
packet_v1.py —— 协议 1.0 输入包打包机 / 输出包解码器
====================================================

**成员 C 交付物**（依据 `C_HANDOFF.md` §4-5）

----------------------------------------------------------------------
它是什么（通俗版）
----------------------------------------------------------------------
协议 1.0 规定：PS 要算一层卷积，就把这一层需要的一切
—— 权重、bias、requant 乘子、移位量、输入激活 ——
**按固定顺序装进一个 32 位的 AXI-Stream 数据包**，
一次性 DMA 送进 PL。

这个模块就是那台**打包机**：
    · `pack_job()`      把 Python 数组压成一个字节流（"装箱"）
    · `unpack_output()` 把硬件吐回来的字节流还原成数组（"拆箱"）
    · `expected_*()`    算准长度，让软件能在开 DMA **之前**就校验缓冲区够不够

> 为什么长度要提前算？
> AXI DMA 是"按字节数收"的。如果软件把接收长度设错了，
> 要么丢数据、要么把上一次的残留当成结果。
> 协议 §5.2 因此要求 wrapper 把 `payload_bytes` / `output_bytes`
> 通过只读寄存器暴露出来，让软件**先检查再启动**。

----------------------------------------------------------------------
包的布局（协议 §5，**顺序固定，不可更改**）
----------------------------------------------------------------------
    align4(x) = (x + 3) & ~3

    weight_bytes = Cout * Cin * 3 * 3
    bias_bytes   = Cout * 4
    mult_bytes   = Cout * 4
    shift_bytes  = Cout
    input_bytes  = N * Cin * H * W

    weight_offset = 0
    bias_offset   = align4(weight_bytes)
    mult_offset   = bias_offset + bias_bytes
    shift_offset  = mult_offset + mult_bytes
    input_offset  = shift_offset + align4(shift_bytes)
    payload_bytes = input_offset + align4(input_bytes)

**所有由 `align4` 插入的空隙必须填 0**（协议 §5 末句）。
因此 `payload_bytes` 永远是 4 的倍数，**每一个输入 beat 的 TKEEP 都是 `1111`**。

以 smoke 用例（N=2, Cin=3, Cout=4, H=5, W=7, pad=1）为例：

    weight 108 → align4 108  (无空隙)
    bias          16   @108
    mult          16   @124
    shift          4 → align4 4   @140  (无空隙)
    input        210 → align4 212 @144  ← 末尾 2 字节空隙，填 0
    payload = 144 + 212 = 356 字节  ✔ 与协议文档一致

----------------------------------------------------------------------
段内编码（协议 §5.1）
----------------------------------------------------------------------
| 段          | 元素编码              | 流编码                                    |
|-------------|-----------------------|-------------------------------------------|
| Weights     | 有符号 INT8，OIHW     | 每 beat 四个连续权重                      |
| Bias        | 每输出通道有符号 INT32| 每 beat 一个完整小端 32 位值              |
| Multipliers | 每输出通道有符号 INT32| 每 beat 一个完整小端 32 位值              |
| Shifts      | 每输出通道无符号字节  | 低 6 位为移位量，高 2 位必须为 0；每 beat 四通道 |
| Input       | 有符号 INT8，NCHW     | 每 beat 四个连续激活                      |

INT32 的字节序：`TDATA[7:0]` 是最低字节，`TDATA[31:24]` 是最高字节
—— 与 ARM 的小端内存表示一致（协议 §5.1 末段）。

----------------------------------------------------------------------
输出包（协议 §4.2 与 §5.2）
----------------------------------------------------------------------
    output_bytes = N * Cout * Hout * Wout
    output_beats = ceil(output_bytes / 4)

末拍 TKEEP 由剩余字节数决定：剩 1/2/3/4 字节 → `0001`/`0011`/`0111`/`1111`。
末拍中无效的字节**驱动为 0**。

----------------------------------------------------------------------
用法
--------------------------------------------------------------------
    from packet_v1 import JobConfig, pack_job, unpack_output

    cfg = JobConfig(batch=2, input_channels=3, output_channels=4,
                    height=5, width=7, padding=1, zero_point=0)
    payload = pack_job(cfg, weights, bias, multipliers, shifts, inputs)
    assert len(payload) == expected_input_bytes(cfg)   # 356

命令行自检：

    python packet_v1.py
"""

from dataclasses import dataclass
import struct

import numpy as np

# ---------------------------------------------------------------------------
# 协议常量（来自 docs/interface.md §2.1 与 int8_conv3x3.h）
# ---------------------------------------------------------------------------

KERNEL_SIZE = 3
STRIDE = 1

MAX_BATCH = 2
MAX_INPUT_CHANNELS = 16
MAX_OUTPUT_CHANNELS = 16
MAX_HEIGHT = 32
MAX_WIDTH = 32
MAX_SHIFT = 62                      # 协议 §2.1：per-channel shift 0..62

MAX_INPUT_VALUES = MAX_BATCH * MAX_INPUT_CHANNELS * MAX_HEIGHT * MAX_WIDTH   # 32768
MAX_WEIGHT_VALUES = MAX_OUTPUT_CHANNELS * MAX_INPUT_CHANNELS * 9             # 2304
MAX_OUTPUT_VALUES = MAX_BATCH * MAX_OUTPUT_CHANNELS * MAX_HEIGHT * MAX_WIDTH  # 32768

INT8_MIN, INT8_MAX = -128, 127
INT32_MIN, INT32_MAX = -(2 ** 31), (2 ** 31) - 1

# 末拍 TKEEP 查表：剩余 n 字节 → tkeep
TKEEP_FOR_REMAINDER = {1: 0b0001, 2: 0b0011, 3: 0b0111, 4: 0b1111,
                       0: 0b1111}     # 0 表示刚好整拍


class PacketError(ValueError):
    """包构造阶段的校验失败。协议 §6.4 里对应 ERR_BAD_CONFIG 一类。"""


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JobConfig:
    """
    一次 job 的全部配置。对应 AXI4-Lite 的七个配置寄存器
    （协议 §6.1：0x10 BATCH、0x14 INPUT_CHANNELS、0x18 OUTPUT_CHANNELS、
     0x1C HEIGHT、0x20 WIDTH、0x24 PADDING、0x28 ZERO_POINT）。

    frozen=True：配置一旦定下就不该被随手改。要改就新建一个。
    """
    batch: int
    input_channels: int
    output_channels: int
    height: int
    width: int
    padding: int
    zero_point: int = 0

    # ---- 派生量 ----------------------------------------------------------
    @property
    def output_height(self):
        """协议 §2.1：Hout = H + 2*padding - 2（K=3 固定）。"""
        return self.height + 2 * self.padding - 2

    @property
    def output_width(self):
        return self.width + 2 * self.padding - 2

    @property
    def weight_elements(self):
        return self.output_channels * self.input_channels * KERNEL_SIZE * KERNEL_SIZE

    @property
    def input_elements(self):
        return self.batch * self.input_channels * self.height * self.width

    @property
    def output_elements(self):
        return (self.batch * self.output_channels
                * self.output_height * self.output_width)


def align4(x):
    """协议 §5：`align4(x) = (x + 3) & ~3`。"""
    return (x + 3) & ~3


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate_config(config):
    """
    在**产生任何字节之前**校验配置。协议 §6.4 的 `ERR_BAD_CONFIG`。

    返回 None；不合法时抛 `PacketError`。
    """
    if not isinstance(config, JobConfig):
        raise PacketError(f"config 必须是 JobConfig，收到 {type(config).__name__}")

    checks = [
        ("batch", config.batch, 1, MAX_BATCH, "N"),
        ("input_channels", config.input_channels, 1, MAX_INPUT_CHANNELS, "Cin"),
        ("output_channels", config.output_channels, 1, MAX_OUTPUT_CHANNELS, "Cout"),
        ("height", config.height, 1, MAX_HEIGHT, "H"),
        ("width", config.width, 1, MAX_WIDTH, "W"),
    ]
    for _name, value, lo, hi, label in checks:
        if not isinstance(value, (int, np.integer)):
            raise PacketError(f"{label} 必须是整数，收到 {type(value).__name__}")
        if not (lo <= int(value) <= hi):
            raise PacketError(f"{label}={value} 超出协议范围 [{lo}, {hi}]")

    if config.padding not in (0, 1):
        raise PacketError(f"padding={config.padding}，协议只允许 0 或 1")

    if not isinstance(config.zero_point, (int, np.integer)):
        raise PacketError("zero_point 必须是整数")
    if not (INT8_MIN <= int(config.zero_point) <= INT8_MAX):
        raise PacketError(
            f"zero_point={config.zero_point} 超出有符号 INT8 范围 "
            f"[{INT8_MIN}, {INT8_MAX}]")

    if config.output_height < 1 or config.output_width < 1:
        raise PacketError(
            f"输出尺寸非法：Hout={config.output_height}, Wout={config.output_width} "
            f"（必须 >= 1）")

    if config.input_elements > MAX_INPUT_VALUES:
        raise PacketError(
            f"输入元素数 {config.input_elements} 超过 MAX_INPUT_VALUES "
            f"({MAX_INPUT_VALUES})")
    if config.weight_elements > MAX_WEIGHT_VALUES:
        raise PacketError(
            f"权重元素数 {config.weight_elements} 超过 MAX_WEIGHT_VALUES "
            f"({MAX_WEIGHT_VALUES})")
    if config.output_elements > MAX_OUTPUT_VALUES:
        raise PacketError(
            f"输出元素数 {config.output_elements} 超过 MAX_OUTPUT_VALUES "
            f"({MAX_OUTPUT_VALUES})")


def validate_shifts(shifts):
    """协议 §6.4 的 `ERR_SHIFT_RANGE`：移位量必须落在 0..62。"""
    s = np.asarray(shifts)
    if s.size == 0:
        raise PacketError("shifts 不能为空")
    if np.any(s < 0) or np.any(s > MAX_SHIFT):
        bad = int(np.max(np.abs(s)))
        raise PacketError(
            f"shift 超出 [0, {MAX_SHIFT}]（收到极值 {bad}）；"
            f"协议规定 shift > 62 为配置错误，核不得启动")


# ---------------------------------------------------------------------------
# 长度计算（协议 §5 / §5.2）
# ---------------------------------------------------------------------------

def describe_layout(config):
    """
    返回包的段布局。**A 要求报告里记录"协议包流量与对齐开销"** ——
    这个函数就是那个数据来源。
    """
    wb = config.weight_elements                       # 权重：1 字节/元素
    bb = config.output_channels * 4                   # bias：4 字节/通道
    mb = config.output_channels * 4                   # 乘子：4 字节/通道
    sb = config.output_channels * 1                   # 移位：1 字节/通道
    ib = config.input_elements                        # 输入：1 字节/元素

    weight_offset = 0
    bias_offset = align4(wb)
    mult_offset = bias_offset + bb
    shift_offset = mult_offset + mb
    input_offset = shift_offset + align4(sb)

    return {
        "weight_offset": weight_offset, "weight_bytes": wb,
        "bias_offset": bias_offset, "bias_bytes": bb,
        "mult_offset": mult_offset, "mult_bytes": mb,
        "shift_offset": shift_offset, "shift_bytes": sb,
        "input_offset": input_offset, "input_bytes": ib,
        "weight_pad": bias_offset - (weight_offset + wb),
        "shift_pad": input_offset - (shift_offset + sb),
        "input_pad": align4(ib) - ib,
        "payload_bytes": input_offset + align4(ib),
        "data_bytes": wb + bb + mb + sb + ib,
    }


def expected_input_bytes(config):
    """完整输入 job 包的字节数（协议 §5 的 `payload_bytes`）。"""
    validate_config(config)
    return describe_layout(config)["payload_bytes"]


def expected_output_bytes(config):
    """结果包的有效字节数 = N * Cout * Hout * Wout（协议 §5.2）。"""
    validate_config(config)
    return config.output_elements


def expected_output_beats(config):
    """结果包的 beat 数 = ceil(output_bytes / 4)。"""
    return -(-expected_output_bytes(config) // 4)


def expected_final_tkeep(config):
    """
    结果包**末拍**的 TKEEP（协议 §4.2）。

    剩 1/2/3/4 字节 → `0001`/`0011`/`0111`/`1111`。
    输出字节数是 4 的倍数时，末拍也是完整的 `1111`。
    """
    n = expected_output_bytes(config)
    rem = n % 4
    return TKEEP_FOR_REMAINDER[rem]


def traffic_report(config):
    """
    协议包流量统计 —— 直接服务于 A 在 `C_FEEDBACK_RESOLUTION` §3
    要求的第 1 类流量：

    > 协议包流量：每 job 的权重/bias/multiplier/shift/input/output
    > 字节数**和对齐开销**。

    返回 dict，单位字节。**这是 `result_source = calculated` 的数据。**
    """
    lay = describe_layout(config)
    out = expected_output_bytes(config)
    total_padding = lay["weight_pad"] + lay["shift_pad"] + lay["input_pad"]
    return {
        "weight_bytes": lay["weight_bytes"],
        "bias_bytes": lay["bias_bytes"],
        "multiplier_bytes": lay["mult_bytes"],
        "shift_bytes": lay["shift_bytes"],
        "input_bytes": lay["input_bytes"],
        "output_bytes": out,
        "alignment_padding_bytes": total_padding,
        "total_in_bytes": lay["payload_bytes"],
        "total_out_bytes": align4(out),      # 最后一拍按 4 字节整拍传出
        "total_bytes": lay["payload_bytes"] + align4(out),
        "in_beats": lay["payload_bytes"] // 4,
        "out_beats": expected_output_beats(config),
        "final_tkeep": expected_final_tkeep(config),
        "payload_bytes": lay["payload_bytes"],
        "data_bytes": lay["data_bytes"],
    }


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------

def _as_int8(arr, name, count):
    a = np.asarray(arr)
    if a.dtype != np.int8:
        if not np.issubdtype(a.dtype, np.integer):
            raise PacketError(f"{name} 必须是整数数组，收到 dtype={a.dtype}")
        if a.size and (a.min() < INT8_MIN or a.max() > INT8_MAX):
            raise PacketError(
                f"{name} 取值超出 INT8 范围 [{INT8_MIN},{INT8_MAX}]："
                f"实际 [{a.min()}, {a.max()}]")
        a = a.astype(np.int8)
    if a.size != count:
        raise PacketError(f"{name} 元素数 {a.size} 与期望 {count} 不符")
    return np.ascontiguousarray(a).ravel()


def _as_int32(arr, name, count):
    a = np.asarray(arr)
    if not np.issubdtype(a.dtype, np.integer):
        raise PacketError(f"{name} 必须是整数数组，收到 dtype={a.dtype}")
    if a.size and (int(a.min()) < INT32_MIN or int(a.max()) > INT32_MAX):
        raise PacketError(
            f"{name} 取值超出 INT32 范围：实际 [{int(a.min())}, {int(a.max())}]")
    if a.size != count:
        raise PacketError(f"{name} 元素数 {a.size} 与期望 {count} 不符")
    return np.ascontiguousarray(a.astype(np.int32)).ravel()


def pack_job(config, weights, bias, multipliers, shifts, inputs):
    """
    把一次 job 的全部数据打包成协议 1.0 的输入字节流。

    参数
    ----
    config      : JobConfig
    weights     : OIHW 权重，`(Cout, Cin, 3, 3)`，有符号 INT8
                  —— 会按 **OIHW 扁平顺序**写入（协议 §5.1）
    bias        : `(Cout,)`，有符号 INT32
    multipliers : `(Cout,)`，有符号 INT32
    shifts      : `(Cout,)`，无符号字节，取值 0..62
    inputs      : NCHW 激活，`(N, Cin, H, W)`，有符号 INT8
                  —— 会按 **NCHW 扁平顺序**写入（协议 §5.1）

    返回
    ----
    `bytes`，长度恒为 `expected_input_bytes(config)`

    校验（全部在产生字节**之前**完成）
    ----------------------------------
    · 维度、padding、输出尺寸（`validate_config`）
    · shift 范围（`validate_shifts`）
    · 各张量的元素数、形状、取值范围
    · zero_point 编码
    """
    validate_config(config)
    shifts_arr = np.asarray(shifts)
    validate_shifts(shifts_arr)

    if shifts_arr.size != config.output_channels:
        raise PacketError(
            f"shifts 元素数 {shifts_arr.size} 与 Cout={config.output_channels} 不符")

    w = _as_int8(weights, "weights", config.weight_elements)
    b = _as_int32(bias, "bias", config.output_channels)
    m = _as_int32(multipliers, "multipliers", config.output_channels)

    s = shifts_arr.astype(np.int64).ravel()
    if np.any(s > MAX_SHIFT):
        raise PacketError(f"shift 超过 {MAX_SHIFT}")

    x = _as_int8(inputs, "inputs", config.input_elements)

    lay = describe_layout(config)
    payload = bytearray(lay["payload_bytes"])

    # --- 各段小端写入 ---
    payload[lay["weight_offset"]:lay["weight_offset"] + w.size] = \
        w.astype("<i1").tobytes()

    payload[lay["bias_offset"]:lay["bias_offset"] + b.size * 4] = \
        b.astype("<i4").tobytes()

    payload[lay["mult_offset"]:lay["mult_offset"] + m.size * 4] = \
        m.astype("<i4").tobytes()

    # 移位量存成"低 6 位有效、高 2 位为 0"的无符号字节
    shift_bytes = (s & 0x3F).astype(np.uint8)
    payload[lay["shift_offset"]:lay["shift_offset"] + shift_bytes.size] = \
        shift_bytes.tobytes()

    payload[lay["input_offset"]:lay["input_offset"] + x.size] = \
        x.astype("<i1").tobytes()

    # 空隙在 bytearray 初始化时已是 0 —— 协议 §5："All gaps inserted by
    # align4 are zero-filled."。这里断言一下，防止将来改动引入非零。
    for start, length in ((bias_offset_pad(lay), lay["weight_pad"]),
                          (shift_offset_pad(lay), lay["shift_pad"]),
                          (input_offset_pad(lay), lay["input_pad"])):
        if length and any(payload[start:start + length]):
            raise PacketError("对齐空隙必须为 0（协议 §5）—— 内部错误")

    return bytes(payload)


def bias_offset_pad(lay):
    return lay["weight_offset"] + lay["weight_bytes"]


def shift_offset_pad(lay):
    return lay["shift_offset"] + lay["shift_bytes"]


def input_offset_pad(lay):
    return lay["input_offset"] + lay["input_bytes"]


def payload_to_beats(config, payload):
    """
    把字节流切成 32 位 AXI-Stream beat 列表（**给 B 的 RTL testbench 用**）。

    返回 `[(tdata:int, tkeep:int, tlast:int, tuser:int), ...]`

    协议 §4.1：字节通道 `i` 是 `TDATA[8*i +: 8]`，**通道 0 是最低张量地址**。
    因为 `payload_bytes` 恒为 4 的倍数，所以**每个 beat 的 TKEEP 都是 `1111`**，
    且只有最后一个 beat 的 `TLAST=1`。
    """
    n = expected_input_bytes(config)
    if len(payload) != n:
        raise PacketError(f"payload 长度 {len(payload)} 与期望 {n} 不符")

    beats = []
    total_beats = n // 4
    for i in range(total_beats):
        chunk = payload[i * 4:(i + 1) * 4]
        tdata = struct.unpack("<I", chunk)[0]     # 小端组装成 32 位
        beats.append((tdata, 0b1111, 1 if i == total_beats - 1 else 0, 0))
    return beats


def beats_to_payload(beats):
    """`payload_to_beats` 的逆运算（供 B 的 testbench 回读校验）。"""
    out = bytearray()
    for tdata, tkeep, _tlast, _tuser in beats:
        if tkeep != 0b1111:
            raise PacketError(f"输入 beat 的 TKEEP 必须是 1111，收到 {tkeep:04b}")
        out += struct.pack("<I", tdata)
    return bytes(out)


# ---------------------------------------------------------------------------
# 解码
# ---------------------------------------------------------------------------

def decode_input_packet(config, payload):
    """
    把输入包拆回五段（**验证用**，B 的 testbench 也会需要）。

    返回 dict：weights(OIHW) / bias / multipliers / shifts / inputs(NCHW)
    """
    validate_config(config)
    n = expected_input_bytes(config)
    if len(payload) != n:
        raise PacketError(f"payload 长度 {len(payload)} 与期望 {n} 不符")

    lay = describe_layout(config)

    w = np.frombuffer(payload, dtype="<i1", count=lay["weight_bytes"],
                      offset=lay["weight_offset"]).reshape(
        config.output_channels, config.input_channels, KERNEL_SIZE, KERNEL_SIZE)

    b = np.frombuffer(payload, dtype="<i4", count=config.output_channels,
                      offset=lay["bias_offset"]).astype(np.int64)

    m = np.frombuffer(payload, dtype="<i4", count=config.output_channels,
                      offset=lay["mult_offset"]).astype(np.int64)

    s_raw = np.frombuffer(payload, dtype=np.uint8, count=config.output_channels,
                          offset=lay["shift_offset"])
    if np.any(s_raw & 0xC0):
        raise PacketError("shift 字节的高 2 位必须为 0（协议 §5.1）")
    s = (s_raw & 0x3F).astype(np.int64)

    x = np.frombuffer(payload, dtype="<i1", count=lay["input_bytes"],
                      offset=lay["input_offset"]).reshape(
        config.batch, config.input_channels, config.height, config.width)

    return {"weights": w, "bias": b, "multipliers": m, "shifts": s, "inputs": x}


def unpack_output(config, payload):
    """
    把硬件吐回来的结果字节流还原成 INT8 张量（协议 §4.2 / §5.2）。

    参数
    ----
    payload : bytes 或 bytearray，长度可以是
              · `expected_output_bytes(config)`（有效数据）
              · `align4(expected_output_bytes(config))`（含末拍填充零）

    返回
    ----
    `(N, Cout, Hout, Wout)` int8 ndarray —— **NCHW**，与协议一致

    规则（协议 §4.2）
    -----------------
    · 结果按 4 个一组打包，**通道 0 是最早的输出元素**
    · 末拍无效字节被驱动为 0，解码时丢弃
    """
    validate_config(config)

    n_out = expected_output_bytes(config)
    n_padded = align4(n_out)

    if not isinstance(payload, (bytes, bytearray)):
        raise PacketError(f"payload 必须是 bytes/bytearray，收到 {type(payload).__name__}")
    if len(payload) not in (n_out, n_padded):
        raise PacketError(
            f"payload 长度 {len(payload)} 既不等于输出字节数 {n_out}，"
            f"也不等于对齐后 {n_padded}")

    raw = np.frombuffer(payload, dtype="<i1", count=n_out)
    return raw.reshape(config.batch, config.output_channels,
                       config.output_height, config.output_width).copy()


def pack_output(config, outputs):
    """
    `unpack_output` 的逆运算：把 NCHW INT8 张量打成结果字节流。

    主要给**测试与 B 的 testbench** 用：可以拿黄金输出生成"标准答案包"，
    喂给 RTL 做逐字节比对。

    末拍不足 4 字节时**补零**（协议 §4.2：invalid bytes driven to zero）。
    """
    validate_config(config)
    a = _as_int8(outputs, "outputs", config.output_elements)
    body = a.astype("<i1").tobytes()
    pad = align4(len(body)) - len(body)
    return body + b"\x00" * pad


def output_beats(config, payload):
    """
    把结果字节流切成 beat 列表（给 B 的 RTL testbench 用）。

    返回 `[(tdata, tkeep, tlast, tuser), ...]`；**只有末拍的 TKEEP 可能不是 1111**。
    """
    n_out = expected_output_bytes(config)
    n_padded = align4(n_out)
    if len(payload) not in (n_out, n_padded):
        raise PacketError("payload 长度不符")
    if len(payload) == n_out and n_padded != n_out:
        payload = payload + b"\x00" * (n_padded - n_out)

    beats = []
    n_beats = n_padded // 4
    for i in range(n_beats):
        chunk = payload[i * 4:(i + 1) * 4]
        tdata = struct.unpack("<I", chunk)[0]
        if i == n_beats - 1:
            rem = n_out - i * 4
            tkeep = TKEEP_FOR_REMAINDER[rem] if rem < 4 else 0b1111
        else:
            tkeep = 0b1111
        beats.append((tdata, tkeep, 1 if i == n_beats - 1 else 0, 0))
    return beats


def decode_output_beats(config, beats):
    """`output_beats` 的逆运算：从 beat 列表还原 INT8 张量。"""
    n_beats = expected_output_beats(config)
    if len(beats) != n_beats:
        raise PacketError(f"beat 数 {len(beats)} 与期望 {n_beats} 不符")
    buf = bytearray()
    for i, (tdata, tkeep, tlast, _tuser) in enumerate(beats):
        chunk = struct.pack("<I", tdata)
        if i == n_beats - 1:
            rem = expected_output_bytes(config) - i * 4
            expected_keep = TKEEP_FOR_REMAINDER[rem] if rem < 4 else 0b1111
            if tkeep != expected_keep:
                raise PacketError(
                    f"末拍 TKEEP={tkeep:04b} 与期望 {expected_keep:04b} 不符")
            buf += chunk[:rem] if rem < 4 else chunk
            if tlast != 1:
                raise PacketError("末拍必须 TLAST=1")
        else:
            if tkeep != 0b1111:
                raise PacketError(f"第 {i} 拍 TKEEP 必须是 1111")
            if tlast != 0:
                raise PacketError(f"第 {i} 拍不应有 TLAST")
            buf += chunk
    return np.frombuffer(bytes(buf), dtype="<i1").reshape(
        config.batch, config.output_channels,
        config.output_height, config.output_width).copy()


# ---------------------------------------------------------------------------
# smoke 用例
# ---------------------------------------------------------------------------

SMOKE_CONFIG = JobConfig(batch=2, input_channels=3, output_channels=4,
                         height=5, width=7, padding=1, zero_point=0)


def smoke_arrays(config=SMOKE_CONFIG, seed=20261010):
    """
    为 smoke 用例生成一组**确定性**数据（固定种子 → 可复现）。

    用固定种子是硬要求（`C_HANDOFF.md` §5 第 10 条）：
    "Fixed random seeds make generated vectors reproducible."
    """
    rng = np.random.default_rng(seed)
    weights = rng.integers(INT8_MIN, INT8_MAX + 1,
                           (config.output_channels, config.input_channels,
                            KERNEL_SIZE, KERNEL_SIZE), dtype=np.int8)
    bias = rng.integers(INT32_MIN, INT32_MAX + 1,
                        config.output_channels, dtype=np.int64).astype(np.int32)
    multipliers = rng.integers(1, 128, config.output_channels, dtype=np.int64).astype(np.int32)
    shifts = rng.integers(25, 34, config.output_channels, dtype=np.int64)
    inputs = rng.integers(INT8_MIN, INT8_MAX + 1,
                          (config.batch, config.input_channels,
                           config.height, config.width), dtype=np.int8)
    return weights, bias, multipliers, shifts, inputs


def self_test():
    """命令行快速自检：打印 smoke 用例的布局与统计。"""
    cfg = SMOKE_CONFIG
    lay = describe_layout(cfg)
    tr = traffic_report(cfg)

    print("=" * 84)
    print("packet_v1 自检 —— smoke 用例（协议文档里引用的那个）")
    print("=" * 84)
    print(f"  配置: N={cfg.batch} Cin={cfg.input_channels} Cout={cfg.output_channels} "
          f"H={cfg.height} W={cfg.width} pad={cfg.padding} zp={cfg.zero_point}")
    print(f"  输出: Hout={cfg.output_height} Wout={cfg.output_width}")
    print()
    print("  段布局（协议 §5）：")
    print(f"    {'段':<12}{'偏移':>8}{'字节':>8}{'对齐填充':>10}")
    print(f"    {'weights':<12}{lay['weight_offset']:>8}{lay['weight_bytes']:>8}"
          f"{lay['weight_pad']:>10}")
    print(f"    {'bias':<12}{lay['bias_offset']:>8}{lay['bias_bytes']:>8}{'-':>10}")
    print(f"    {'multipliers':<12}{lay['mult_offset']:>8}{lay['mult_bytes']:>8}{'-':>10}")
    print(f"    {'shifts':<12}{lay['shift_offset']:>8}{lay['shift_bytes']:>8}"
          f"{lay['shift_pad']:>10}")
    print(f"    {'inputs':<12}{lay['input_offset']:>8}{lay['input_bytes']:>8}"
          f"{lay['input_pad']:>10}")
    print()
    print(f"  输入包总字节    : {tr['payload_bytes']}   "
          f"（协议文档声明 356）{' ✔' if tr['payload_bytes'] == 356 else ' ✘'}")
    print(f"  输入包 beat 数  : {tr['in_beats']}   每拍 TKEEP=1111")
    print(f"  输出有效字节    : {tr['output_bytes']}   "
          f"（协议文档声明 280）{' ✔' if tr['output_bytes'] == 280 else ' ✘'}")
    print(f"  输出 beat 数    : {tr['out_beats']}   "
          f"（协议文档声明 70）{' ✔' if tr['out_beats'] == 70 else ' ✘'}")
    print(f"  末拍 TKEEP      : {tr['final_tkeep']:04b}  "
          f"（期望 1111）{' ✔' if tr['final_tkeep'] == 0b1111 else ' ✘'}")
    print(f"  对齐填充合计    : {tr['alignment_padding_bytes']} 字节")

    # 实际打包一次
    w, b, m, s, x = smoke_arrays()
    payload = pack_job(cfg, w, b, m, s, x)
    print()
    print(f"  实际打包结果    : {len(payload)} 字节  "
          f"{'✔ 与计算一致' if len(payload) == tr['payload_bytes'] else '✘ 不一致'}")
    print(f"  SHA-256         : ", end="")

    import hashlib
    print(hashlib.sha256(payload).hexdigest()[:32] + "…")

    # 往返一致性
    back = decode_input_packet(cfg, payload)
    ok = (np.array_equal(back["weights"], w) and np.array_equal(back["bias"], b)
          and np.array_equal(back["multipliers"], m)
          and np.array_equal(back["shifts"], s) and np.array_equal(back["inputs"], x))
    print(f"  打包→解码往返   : {'✔ 五段全部一致' if ok else '✘ 有差异'}")

    beats = payload_to_beats(cfg, payload)
    print(f"  beat 化往返     : "
          f"{'✔ 一致' if beats_to_payload(beats) == payload else '✘ 有差异'}")

    # 末拍 TKEEP 表
    print()
    print("  末拍 TKEEP 表（协议 §4.2）：")
    for rem, keep in ((0, 0b1111), (1, 0b0001), (2, 0b0011), (3, 0b0111)):
        label = "整拍" if rem == 0 else f"剩 {rem} 字节"
        print(f"    输出字节数 mod 4 = {rem}  ({label:<8}) → TKEEP = {keep:04b}")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
