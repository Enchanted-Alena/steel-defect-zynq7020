"""
int8_reference.py —— INT8 量化黄金模型（Golden Model）
=====================================================

**版本 v2.0（2026-10-10）—— 对齐 A 的协议 1.0 与冻结的 TM=2 HLS 实现**

这是整个项目的**唯一标准答案**。
Python、C++ 参考核、HLS 核、RTL —— 四个实现最终都必须和这个文件的结果
**逐元素 bit-exact（逐位完全相同）**。

----------------------------------------------------------------------
v1.0 → v2.0 变更（全部依据 A 冻结的 TM=2 实现）
----------------------------------------------------------------------
| # | 项目        | v1.0            | v2.0（本版）              | 依据                     |
|---|-------------|-----------------|---------------------------|--------------------------|
| 1 | 舍入        | half-up         | **half-to-even**          | `int8_conv3x3.cpp:3-31`  |
| 2 | 累加溢出    | 抛异常          | **模 2^32 回绕**          | `.h:37`、`.cpp:250`      |
| 3 | 累积器口径  | 不含 bias       | **含 bias**（bias=初值）  | `.cpp:223-224`           |
| 4 | 激活默认值  | `relu`          | **`none`**                | `.cpp:264`（核内无激活） |
| 5 | 累加顺序    | 任意            | `Cin → Ky → Kx`（等价）   | `.cpp:226-233`           |
----------------------------------------------------------------------

v1.0 原文备份在 `int8_reference.py.v1_backup`，仅供历史对照。

阅读顺序建议
------------
第 1 节  舍入与饱和       ← 四个必须绕开的坑都在这里
第 2 节  量化 / 反量化
第 3 节  BN 折叠
第 4 节  requant 参数生成
第 5 节  整数卷积（含累积器导出）
第 6 节  激活与池化的整数版
第 7 节  自检（直接跑 `python int8_reference.py`）

对应文档：docs/quantization.md、docs/spec.md
"""

from dataclasses import dataclass
import numpy as np

from tensor_utils import (extract_windows, conv_output_size,
                          to_ohwi, from_nhwc)

# INT32 / INT8 取值范围，全文件共用
INT32_MIN = -(2 ** 31)          # -2147483648
INT32_MAX = (2 ** 31) - 1       #  2147483647
UINT32_MASK = (1 << 32) - 1

INT8_MIN = -128
INT8_MAX = 127

MAX_SHIFT = 62                  # 协议 §2.1：per-channel shift 取值 0..62


# ============================================================================
# 第 1 节  舍入与饱和
# ============================================================================

def wrap_int32(x):
    """
    模 2³² 回绕 —— 把任意宽的整数解释成有符号 INT32。

    通俗理解
    --------
    像汽车的**里程表**：表盘只有固定的位数，跑过头就归零重来。
    累加器是一块 32 位的表盘，涨到超过 2³¹-1 就从 -2³¹ 继续。

    为什么本项目需要它
    ------------------
    A 的 HLS 里累加器是 `ap_int<32>`，每次加法都自然回绕：

        lane_accumulator[lane] = int32_value(
            lane_accumulator[lane] + int32_value(lane_product[lane]));

    所以**黄金模型必须同样回绕**，否则遇到故意构造的溢出用例
    （如 `int32_wrap_both_signs`，bias = ±2³¹）就会与硬件不一致。

    ★ v1.0 的做法是检测到溢出就抛异常 —— 那会直接拒绝 A 的**合法**测试用例，
      是错的。v2.0 改为回绕，并把"是否回绕"的诊断信息单独提供
      （见 `int32_overflow_report`），供报告使用。

    实现：先按无符号取低 32 位，再按有符号解释。
    """
    u = np.asarray(x, dtype=np.int64) & UINT32_MASK
    return np.where(u >= (1 << 31), u - (1 << 32), u).astype(np.int64)


def round_shift(x, s):
    """
    规则 R2：硬件的 requant 右移 —— **round half to even（向偶数舍入）**

    ⚠️ 这条规则与直觉相反，v1.0 曾把它写错，务必看清。

    定义
    ----
        q    = x >> s                       # 算术右移（对负数即 floor）
        r    = x & ((1 << s) - 1)           # 非负余数（对负数也正确）
        half = 1 << (s - 1)
        若 r > half，或（r == half 且 q 是奇数）→ q += 1

    `s == 0` 时必须单独分支 —— 因为 `1 << -1` 是未定义行为。

    为什么用"向偶数"而不是"四舍五入"
    ---------------------------------
    遇到 .5 这种半值时：
      · 一律进位 → 结果**系统性偏大**
      · 一律舍去 → 结果**系统性偏小**
      · **向偶数** → 偏差在两个方向交替抵消，统计上**无偏**
    这是数值计算的标准做法（IEEE 754 默认舍入模式、Python 的 `round()` 都是它）。

    ★ 三个常见但**错误**的写法
    --------------------------
    1. `(x + (1 << (s-1))) >> s`  —— 这是 **half-up**（朝 +∞ 取整）。
       x=10, s=2 时给 3，而正确的是 2。
    2. C/C++ 的 `x / (1 << s)`     —— 对负数**向零截断**，与硬件的 floor 不同。
    3. Python 的 `round(float)`    —— 虽然也是向偶数，但走浮点，
       大整数会丢精度，且无法表达 `s == 0` 的硬件行为。

    与 Verilog 的逐行对应
    ---------------------
        wire signed [63:0] q = product >>> shift;
        wire        [63:0] r = product & ((64'd1 << shift) - 1);
        if (r > half || (r == half && q[0])) q = q + 1;
    """
    x = np.asarray(x, dtype=np.int64)
    s = int(s)
    if s < 0:
        raise ValueError(f"shift 不能为负，收到 {s}")
    if s > MAX_SHIFT:
        raise ValueError(f"shift={s} 超过协议上限 {MAX_SHIFT}")
    if s == 0:
        return x.copy()

    q = x >> np.int64(s)                                    # 算术右移 = floor
    r = (x.astype(np.uint64) & np.uint64((1 << s) - 1)).astype(np.int64)
    half = 1 << (s - 1)

    increment = (r > half) | ((r == half) & ((q & 1) != 0))
    return q + increment.astype(np.int64)


def saturate_int8(x):
    """
    饱和（saturation）：把超出 [-128, 127] 的值夹到边界，而不是回绕。

    通俗理解
    --------
    像**音量限制器**：声音再大也只能到最大音量，不会"翻"成最小音量。

    为什么必须饱和而不是截断？
    硬件里 requant 之后的值可能落在 127 之外。如果直接丢弃高位，
    符号位会翻转 —— 一个很大的正数变成一个很负的数。
    这是最恶劣的一类 bug：不报错，只让精度莫名其妙地崩掉。

    ★ 顺序陷阱：饱和必须是**最后一步**，且在加 zero_point **之后**。
        正确：乘法 → 加 zero_point → 饱和
        错误：乘法 → 饱和 → 加 zero_point
      本项目 zero_point 固定为 0（对称量化），两种顺序看不出差别；
      一旦改用非对称量化，错误顺序立刻全错。
    """
    return np.clip(np.asarray(x, dtype=np.int64), INT8_MIN, INT8_MAX).astype(np.int8)


# ============================================================================
# 第 2 节  量化 / 反量化
# ============================================================================

def round_half_away_from_zero(x):
    """
    规则 R1：四舍五入，远离零（round half away from zero）。

        +2.5 → +3      -2.5 → -3

    **仅用于离线的浮点→整数转换**（bias 量化、乘子定点化）。

    ⚠️ 在线推理的 requant 用的是规则 R2（`round_shift`，向偶数）。
       **这两条规则不可混用** —— 这是 v1.0 最混乱的地方，v2.0 明确分开。
       与 A 的 `int8_conv._round_half_away_from_zero_float` 行为一致。

    对标量返回 float，对数组返回 ndarray。
    """
    x = np.asarray(x, dtype=np.float64)
    out = np.where(x >= 0.0, np.floor(x + 0.5), np.ceil(x - 0.5))
    if out.ndim == 0:
        return float(out)
    return out


def quantize_per_tensor(r, qmax=INT8_MAX):
    """
    对称 per-tensor 量化（对称 = 强制 zero_point 为 0）。

        s = max(|r|) / 127
        q = clamp(round(r / s), -128, 127)

    返回 (q, s)：q 是 int8 数组，s 是**一个标量**。

    通俗理解：整张图共用一把尺子。尺子的刻度 = 全图最大值 / 127。
    用途：激活（activation）的量化。
    """
    r = np.asarray(r, dtype=np.float64)
    amax = float(np.max(np.abs(r))) if r.size else 0.0
    if amax == 0.0:
        return np.zeros(r.shape, dtype=np.int8), 1.0
    s = amax / qmax
    q = round_half_away_from_zero(r / s)
    return np.clip(q, INT8_MIN, INT8_MAX).astype(np.int8), s


def quantize_weight_per_channel(w, qmax=INT8_MAX):
    """
    对称 **per-output-channel** 量化。这是协议对权重的要求。

    通俗理解：**每个输出通道各配一把尺子**。
    如果整个权重张量共用一把尺子，那些量级本来就很小的通道会被
    最大的通道"吃掉"有效位数 —— 等于白量化。

    参数
    ----
    w : (Cout, ...) 浮点权重。**不关心剩余布局**，
        因为只沿 Cout 轴（axis 0）取最大值，
        布局是 OHWI 还是 OIHW 对结果没有影响。
    """
    w = np.asarray(w, dtype=np.float64)
    Cout = w.shape[0]
    flat = w.reshape(Cout, -1)

    amax = np.max(np.abs(flat), axis=1)              # (Cout,)
    s = np.where(amax == 0.0, 1.0, amax / qmax)

    q = round_half_away_from_zero(flat / s[:, None])
    q = np.clip(q, INT8_MIN, INT8_MAX).astype(np.int8).reshape(w.shape)
    return q, s.astype(np.float64)


def quantize_with_scale(r, s):
    """
    用一个**给定的** scale 去量化。

    ★ 与 `quantize_per_tensor` 的关键区别：
      硬件里的 s_in 是一个**固定寄存器值**（离线校准出来的），
      不是每个输入样本现算的。所以：
        · 校准/导出时：用 `quantize_per_tensor` 从一批数据里算出 s
        · 推理时：用本函数，拿固定的 s 去量化
      如果推理时拿"当前样本自己的最大值"算 scale，那就成了动态量化，
      和硬件行为不一致，bit-exact 必然失败。
    """
    r = np.asarray(r, dtype=np.float64)
    q = round_half_away_from_zero(r / float(s))
    return np.clip(q, INT8_MIN, INT8_MAX).astype(np.int8)


def dequantize(q, s):
    """反量化：整数 → 实数。用于精度分析，硬件里不做这一步。"""
    return np.asarray(q, dtype=np.float64) * np.asarray(s, dtype=np.float64)


# ============================================================================
# 第 3 节  BN 折叠（BatchNorm Folding）
# ============================================================================

def fold_bn(w, conv_bias, gamma, beta, mean, var, eps=1e-5):
    """
    把 BatchNorm 折进卷积的权重和偏置。

    通俗理解
    --------
    BatchNorm 是一道"调色"工序：把卷积输出的每个通道
    减掉均值、除掉标准差、再乘个系数、加个偏移。

    因为推理阶段这四个数都是**常数**，整个"调色"就是一个线性变换
    `y = a*x + b`。既然是线性的，就可以**提前算进卷积的权重里** ——
    于是硬件上再也看不到 BN 了。

    推导
    ----
        y = gamma * (x - mean) / sqrt(var + eps) + beta
        令 a = gamma / sqrt(var + eps)
           b = beta - gamma * mean / sqrt(var + eps)
        则 y = a*x + b

    套到卷积 x = sum(W*I) + conv_bias 上：
        y = a * (sum(W*I) + conv_bias) + b
          = sum((a*W) * I) + (a*conv_bias + b)

    ⤳ W_folded    = a * W
    ⤳ bias_folded = a * conv_bias + b

    ★ 与 A 的 `int8_conv.fold_batch_norm` 等价性已核对：
      A 写的是 `folded_bias = beta + (conv_bias - mean) * bn_scale`，
      展开后与本文的 `a*conv_bias + b` 完全相同。

    ⚠️ 注意：**这是离线步骤**。折叠改变了权重分布，所以折叠后
      必须**重新计算 s_w**（`prepare_int8_layer` 会自动做）。

    返回 (w_folded, bias_folded, a, b)
    """
    gamma = np.asarray(gamma, dtype=np.float64)
    beta = np.asarray(beta, dtype=np.float64)
    mean = np.asarray(mean, dtype=np.float64)
    var = np.asarray(var, dtype=np.float64)

    a = gamma / np.sqrt(var + eps)                    # (Cout,)
    b = beta - gamma * mean / np.sqrt(var + eps)      # (Cout,)

    w_folded = np.asarray(w, dtype=np.float64) * a.reshape(-1, 1, 1, 1)
    bias_folded = a * np.asarray(conv_bias, dtype=np.float64) + b

    return w_folded, bias_folded, a, b


# ============================================================================
# 第 4 节  requant 参数生成
# ============================================================================

def quantize_multiplier(m_real):
    """
    把一个**实数乘子**表示成定点形式 M * 2^(-shift)。

    通俗理解
    --------
    硬件不会算浮点乘法，只能用"乘一个整数、再右移若干位"来近似。
    这个函数就是找出最合适的整数 M 和移位量 shift —— 相当于
    把一把没有刻度的尺子，硬塞进只有整数刻度的格子里，选最合适的那把。

    返回 (M, shift)：M 是 int32 整数，落于 [2³⁰, 2³¹)，shift 为非负整数。

    做法
    ----
      1. 把 m 反复乘 2 或除 2，归一化到 [0.5, 1)，记净乘 2 的次数为 e
      2. M = round(m_normalized * 2³¹)  → 落在 [2³⁰, 2³¹)，**用满 int32 正半轴**
      3. shift = 31 + e

    为什么归一化？若 M 只用了低几位，精度会白白损失。

    ⚠️ 与 A 的 `int8_conv.quantize_folded_conv` 的差异（**待团队确认项**）
    ---------------------------------------------------------------
    A 用**固定 shift = 31**：`M = round(m_real * 2³¹)`。
    当 m_real >= 1.0 时会溢出 INT32（A 的代码对此抛异常）。

    本实现用**归一化 + 可变 shift**，任何正数都能表示，
    且同样用满 31 位尾数，精度不劣于固定 shift。

    两者对同一个 m_real 会给出不同的 (M, shift) 组合，
    **但换算回实数后精度相同**。因为 M/shift 是发给硬件的输入参数，
    谁生成都可以 —— 但**同一批向量必须用同一套方法**，不能混。
    """
    m = float(m_real)
    if not np.isfinite(m) or m <= 0.0:
        raise ValueError(f"requant 乘子必须是有限正数，收到 {m_real}")

    e = 0
    while m < 0.5:
        m *= 2.0
        e += 1
    while m >= 1.0:
        m /= 2.0
        e -= 1

    M = int(round_half_away_from_zero(m * float(1 << 31)))
    if M > INT32_MAX:
        # 极端边界：m 无限接近 1.0 时可能舍入到 2³¹。夹一下，误差 1 LSB。
        M = INT32_MAX

    shift = 31 + e
    if not (0 <= shift <= MAX_SHIFT):
        raise ValueError(f"乘子 {m_real} 推出的 shift={shift} 超出 [0,{MAX_SHIFT}]")

    return M, shift


def quantize_multiplier_fixed_shift(m_real, requant_shift=31):
    """
    A 的 `int8_conv.quantize_folded_conv` 使用的定点化方式：**固定 shift**。

        M = round(m_real * 2^requant_shift),  shift = requant_shift

    保留此函数的用途：与 A 的参考实现做**逐参数对照**
    （见 `tests/regression/` 的对照测试），以及在需要与既有向量保持一致时使用。

    ⚠️ m_real >= 1.0 时会溢出 INT32 —— 此时抛异常，与 A 的行为一致。
    """
    m = float(m_real)
    if not np.isfinite(m) or m <= 0.0:
        raise ValueError(f"requant 乘子必须是有限正数，收到 {m_real}")
    if not (0 <= requant_shift <= MAX_SHIFT):
        raise ValueError(f"requant_shift 必须在 [0,{MAX_SHIFT}]")

    M = int(round_half_away_from_zero(m * float(1 << requant_shift)))
    if M > INT32_MAX:
        raise ValueError(
            f"乘子 {m_real} × 2^{requant_shift} 超过 INT32 —— "
            f"请降低 requant_shift 或增大 output_scale（与 A 的行为一致）")
    return M, requant_shift


@dataclass
class Int8ConvParams:
    """
    一层 INT8 卷积的**全部硬件参数**。这些值会被写进 AXI4-Lite 寄存器
    （成员 B 负责），或者作为 HLS 的编译期常量（成员 A 负责）。
    """
    name: str
    K: int
    stride: int
    pad: int
    Cin: int
    Cout: int
    activation: str            # 'none' | 'relu' | 'leaky_relu' —— 默认 'none'
    leaky_alpha: float
    zero_point: int            # 第一版固定 0（对称量化）
    s_in: float                # 输入激活 scale（per-tensor）
    s_out: float               # 输出激活 scale（per-tensor）
    s_w: np.ndarray            # (Cout,) 权重 scale（per-channel）
    bias_int: np.ndarray       # (Cout,) int32 —— **作为累加器初值**
    M: np.ndarray              # (Cout,) int32 requant 乘子
    shift: np.ndarray          # (Cout,) requant 右移量，范围 0..62

    def summary(self):
        return (f"{self.name}: K={self.K} S={self.stride} pad={self.pad} "
                f"Cin={self.Cin} Cout={self.Cout} act={self.activation} "
                f"s_in={self.s_in:.3e} s_out={self.s_out:.3e} "
                f"shift范围=[{self.shift.min()},{self.shift.max()}]")


def prepare_int8_layer(w_folded, bias_folded, s_in, s_out,
                       K, stride, pad, Cin, Cout,
                       name="layer", activation="none", leaky_alpha=0.1,
                       zero_point=0, multiplier_mode="normalized"):
    """
    由折叠后的浮点权重 + 校准好的 scale，算出全部硬件整数参数。

    通俗理解
    --------
    这一步是"翻译"：把浮点世界里的一份权重和一组刻度，
    翻译成硬件能直接装载的一堆整数（权重、偏置、乘子、移位量）。

    核心推导
    --------
      y_real = sum(W_folded * I_real) + bias_folded
             ≈ s_w[oc] * s_in * sum(q_w * q_i) + bias_folded
             = s_w[oc] * s_in * acc_partial + bias_folded

      令 bias_int[oc] = round(bias_folded[oc] / (s_w[oc] * s_in))
        ★ 分母是 s_w[oc] * s_in，**不是 s_out**！
          这里推错会导致"大部分元素对得上、但整体有系统性偏差"，极难 debug。
      则 bias_folded = s_w[oc] * s_in * bias_int[oc]

      于是 acc_int32 = wrap_int32(acc_partial + bias_int)   ← A 的口径
           y_real ≈ s_w[oc] * s_in * acc_int32

      q_out = round_half_to_even(y_real / s_out) + zero_point
            = round_half_to_even( acc_int32 * M_real[oc] ) + zero_point
        其中 M_real[oc] = s_w[oc] * s_in / s_out

    ★ v2.0 的重要变化：`bias_int` 不再在 requant 时相加，
      而是作为**累加器的初值**（与 A 的 `.cpp:223-224` 一致）。
      两者在实数意义下等价，但**模 2³² 回绕时不等价** —— 必须按 A 的口径。

    参数
    ----
    w_folded : (Cout, ...) 已折叠 BN 的浮点权重
    multiplier_mode : "normalized"（本实现的归一化方式，默认）
                    | "fixed31"（A 的固定 shift=31 方式）

    返回 (q_w, params)
    """
    q_w, s_w = quantize_weight_per_channel(w_folded)

    # bias 的整数表示。分母是 s_w * s_in。
    denom = s_w * float(s_in)
    bias_int_f = round_half_away_from_zero(np.asarray(bias_folded, dtype=np.float64) / denom)
    bias_int = np.rint(bias_int_f).astype(np.int64)

    if np.any(np.abs(bias_int) > INT32_MAX):
        raise OverflowError(
            f"{name}: bias_int 超出 INT32 范围，最大绝对值 {np.abs(bias_int).max():.3e}。"
            f"通常意味着 s_in 或 s_w 校准异常（比如某层激活几乎全为零）。")

    M = np.zeros(Cout, dtype=np.int64)
    shift = np.zeros(Cout, dtype=np.int64)
    for oc in range(Cout):
        m_real = float(s_w[oc]) * float(s_in) / float(s_out)
        if multiplier_mode == "fixed31":
            M[oc], shift[oc] = quantize_multiplier_fixed_shift(m_real, 31)
        elif multiplier_mode == "normalized":
            M[oc], shift[oc] = quantize_multiplier(m_real)
        else:
            raise ValueError(f"未知 multiplier_mode: {multiplier_mode}")

    params = Int8ConvParams(
        name=name, K=K, stride=stride, pad=pad, Cin=Cin, Cout=Cout,
        activation=activation, leaky_alpha=leaky_alpha,
        zero_point=zero_point,
        s_in=float(s_in), s_out=float(s_out),
        s_w=np.asarray(s_w, dtype=np.float64),
        bias_int=bias_int.astype(np.int64),
        M=M, shift=shift,
    )
    return q_w, params


# ============================================================================
# 第 5 节  整数卷积
# ============================================================================

def int32_worst_case_bound(Cin, K):
    """
    INT32 累加的理论最坏情况上界（docs/spec.md §3.1）：

        |acc| <= 127 * 127 * Cin * K * K

    通俗理解：估一条水管的**最大流量** —— 用来判断 32 位这个"桶"够不够装。

    这个数字要写进报告，用来论证"我们的层不会溢出"。
    但注意：**协议允许回绕**，所以即使超界也不是协议错误，
    只意味着这层需要更宽的累加器或分段累加。
    """
    return (INT8_MAX ** 2) * Cin * K * K


def int32_overflow_report(acc_partial, bias_int, Cin, K, name=""):
    """
    回绕诊断 —— 供报告使用，**不影响计算结果**。

    返回 dict：
        theoretical_bound : 理论最坏上界 |acc| <= 127² * Cin * K * K
        headroom_ratio    : 上界占 INT32 上限的比例
        actual_min/max    : 本批数据里"未回绕"的累加值范围
        wrapped           : 实际是否发生了回绕（bool）

    为什么要单独做这件事？
    协议 §2.3 规定累加是**模 2³² 回绕**，所以溢出不是错误、不能抛异常。
    但报告里需要说明"本项目的层在正常输入下不会回绕到影响结果的量级"。
    这两件事必须分开：不能因为"要能回绕"就丢掉诊断信息。
    """
    raw = np.asarray(acc_partial, dtype=np.int64) + np.asarray(bias_int, dtype=np.int64)
    bound = int32_worst_case_bound(Cin, K)
    return {
        "name": name,
        "theoretical_bound": int(bound),
        "headroom_ratio": bound / INT32_MAX,
        "actual_min": int(raw.min()),
        "actual_max": int(raw.max()),
        "wrapped": bool(np.any(raw < INT32_MIN) or np.any(raw > INT32_MAX)),
        "n_elements": int(raw.size),
    }


def requantize(acc_int32, M, shift, zero_point=0):
    """
    完整的 requant 步骤（硬件里的后处理单元）：

        q_out = saturate_int8( round_shift_half_to_even( acc_int32 × M, shift ) + zero_point )

    参数
    ----
    acc_int32 : (..., Cout) —— **已经包含 bias** 的 INT32 累加器
                （A 的 `.cpp:223` 把 bias 作为累加器初值）
    M, shift  : (Cout,)

    ★ v2.0 变化：本函数**不再加 bias_int**。bias 已在累加阶段并入。
      v1.0 的写法是 `(acc_partial + bias_int) * M`，
      实数意义下等价，但**模 2³² 回绕语义不同**，故必须改。

    实现说明：按输出通道循环，因为 shift **可能逐通道不同**
    （每个通道的 s_w 不同 → M_real 不同 → 归一化后的 shift 不同）。
    硬件里同样需要逐通道的 shift，通常做成一张小查找表。
    """
    acc_int32 = np.asarray(acc_int32, dtype=np.int64)
    Cout = acc_int32.shape[-1]

    out = np.empty(acc_int32.shape, dtype=np.int64)
    for oc in range(Cout):
        wide = acc_int32[..., oc] * np.int64(M[oc])
        # wide 最大约 2³¹ × 2³¹ = 2⁶²，int64 装得下（上限 2⁶³-1）
        out[..., oc] = round_shift(wide, int(shift[oc]))

    out = out + np.int64(zero_point)
    return saturate_int8(out)


def conv2d_int8(x_int, q_w, params, fuse_activation=True,
                return_accumulator=False, overflow_report=None,
                layout="NCHW", weight_layout="OIHW", output_layout=None):
    """
    整数卷积 —— 这就是 PE 阵列 + 后处理单元要干的全部事情。

    通俗理解
    --------
    想象一排计算工位（PE 阵列）：
      1. 从行缓存里取出一小块输入（滑窗）
      2. 每个工位拿自己那一片权重，做 INT8 × INT8 乘法
      3. 结果累加进一个 32 位的"存钱罐"（累加器）—— **存钱罐里先放好 bias**
      4. 全部输入通道累完之后，把总数按刻度缩回 8 位

    参数
    ----
    x_int  : 量化后的输入，布局由 `layout` 指定
             · `"NCHW"`（默认，**协议布局**）：`(N, Cin, H, W)`
             · `"NHWC"`（内部表示）：`(N, H, W, Cin)`
    q_w    : 量化后的权重，布局由 `weight_layout` 指定
             · `"OIHW"`（默认，**协议布局**）：`(Cout, Cin, K, K)`
             · `"OHWI"`（内部表示）：`(Cout, K, K, Cin)`
    params : Int8ConvParams
    fuse_activation : 是否把激活融合进来。
        设成 False 就是 **Unfused** 路径 —— 用来做"融合前后访存量对比"的基线。
        两个版本的最终**数值必须相同**。
        ⚠️ MVP 的 HLS 核**没有激活**，所以 params.activation 默认 'none'，
           此时该参数无实际作用。
    return_accumulator : 为 True 时额外返回 INT32 累积器数组
        （口径：**含 bias**，与 A 的 `accumulators[]` 输出一致）
    overflow_report : 传入一个 dict，函数会填入回绕诊断信息
    layout : 输入布局，默认 `"NCHW"`（协议要求）
    weight_layout : 权重布局，默认 `"OIHW"`（协议要求）
    output_layout : 输出布局；默认与 `layout` 相同

    返回
    ----
    (N, Cout, Hout, Wout) int8（NCHW 时）
    或 (outputs, accumulators) 当 return_accumulator=True

    数据流（与硬件一一对应）：
      1. 滑窗取出 (Cin, K, K) 个 int8
      2. 与 (Cout, K, K, Cin) 的权重做 INT8×INT8 乘加 → INT64 中间值
      3. **加 bias（作为初值）并模 2³² 回绕** → INT32 累加器
      4. 乘 M、向偶数舍入右移、加 zero_point、饱和 → int8
      5. 激活（若启用）—— MVP 中不启用

    ★ 累加顺序 Cin → Ky → Kx（A 的 `.cpp:226-233`）。
      整数加法满足结合律与交换律，**顺序不影响结果**，
      所以这里可以用 einsum 并行计算 —— 这正是并行加速器能成立的数学前提。
    """
    if output_layout is None:
        output_layout = layout

    x_int = np.asarray(x_int, dtype=np.int8)
    q_w = np.asarray(q_w, dtype=np.int8)
    q_w_ohwi = np.asarray(to_ohwi(q_w, weight_layout), dtype=np.int8)

    Cout, K, Kw, Cin = q_w_ohwi.shape
    if K != Kw:
        raise ValueError("只支持方形卷积核")
    if Cin != x_int.shape[-1 if layout == "NHWC" else 1]:
        raise ValueError(
            f"通道数不匹配: x 的 Cin={x_int.shape[-1 if layout == 'NHWC' else 1]}, "
            f"w 的 Cin={Cin}")

    win = extract_windows(x_int, K, params.stride, params.pad, layout=layout)
    # 用 int64 做中间计算，以便**检测**是否真的发生了回绕（诊断用）
    acc_partial = np.einsum('nhwikl,okli->nhwo',
                            win.astype(np.int64), q_w_ohwi.astype(np.int64),
                            optimize=True)

    bias = np.asarray(params.bias_int, dtype=np.int64).reshape(1, 1, 1, Cout)

    if overflow_report is not None:
        overflow_report.update(
            int32_overflow_report(acc_partial, bias, Cin, K, params.name))

    # ★ A 的口径：bias 是累加器初值，整体模 2³² 回绕
    acc_int32 = wrap_int32(acc_partial + bias)

    q = requantize(acc_int32, params.M, params.shift, params.zero_point)

    if fuse_activation:
        q = apply_activation_int8(q, params)

    if output_layout != "NHWC":
        q = from_nhwc(q, output_layout)
        acc_int32 = from_nhwc(acc_int32, output_layout)

    if return_accumulator:
        return q, acc_int32
    return q


# ============================================================================
# 第 6 节  激活与池化的整数版
# ============================================================================

def relu_int8(q):
    """
    整数域 ReLU。

    对称量化下，实数 0 精确映射为整数 0，所以整数 ReLU 就是 max(q, 0)。
    硬件里只需要一个符号位判断 + 一个多路选择器，几乎不花资源。

    ⚠️ MVP 的 HLS 核**没有**激活函数（`.cpp:264` 确认），本函数保留供扩展使用。
       如果将来改用非对称量化，这里必须改成 max(q, zero_point)。
    """
    return np.maximum(np.asarray(q, dtype=np.int64), 0).astype(np.int8)


def leaky_relu_int8(q, alpha=0.1):
    """
    整数域 LeakyReLU：负数乘以 alpha。
    硬件里需要一次乘法。常见做法是把 alpha 也定点化成 alpha_int / 2^k。
    """
    q = np.asarray(q, dtype=np.int64)
    scaled = round_half_away_from_zero(q.astype(np.float64) * float(alpha))
    out = np.where(q >= 0, q, np.rint(scaled).astype(np.int64))
    return saturate_int8(out)


def apply_activation_int8(q, params):
    """按 params.activation 指定的方式做激活。默认 'none'（MVP 行为）。"""
    if params.activation == "none":
        return np.asarray(q, dtype=np.int8)
    if params.activation == "relu":
        return relu_int8(q)
    if params.activation == "leaky_relu":
        return leaky_relu_int8(q, params.leaky_alpha)
    raise ValueError(f"未知激活类型: {params.activation}")


def maxpool2x2_int8(q, stride=2):
    """
    整数域 2x2 最大池化。

    池化**不改变 scale** —— 因为 max 只是选一个已有的值，不产生新的数值。
    所以 s_out_pool = s_in_pool，不需要新的量化参数。
    这一点让 Conv+Pool 融合在量化上是**免费**的。

    ⚠️ 协议 1.0 把 pooling 排除在 MVP 之外，本函数保留供扩展使用。
    """
    q = np.asarray(q, dtype=np.int8)
    win = extract_windows(q, 2, stride=stride, pad=0)
    return win.max(axis=(-1, -2)).astype(np.int8)


# ============================================================================
# 第 7 节  自检
# ============================================================================

def test_round_shift_semantics(verbose=True):
    """
    验证 round_shift 的行为符合"向偶数舍入"。
    ★ v2.0 的期望值全部重算过 —— 与 v1.0 的 half-up 表**不同**。
    """
    table = [
        # (x, shift, 期望结果, 说明)
        (10, 2,  2, "10/4=2.5 → 向偶数取整得 2（half-up 会给 3，最常见的错法）"),
        (-10, 2, -2, "-10/4=-2.5 → 得 -2（-2 是偶数）"),
        (-6, 2, -2, "-6/4=-1.5 → 得 -2（-2 是偶数；half-up 会给 -1）"),
        (-7, 2, -2, "-7/4=-1.75 → 最近的是 -2"),
        (6, 2,  2, "6/4=1.5 → 得 2（1 是奇数，进位）"),
        (-2, 2,  0, "-2/4=-0.5 → 得 0（0 是偶数）"),
        (2, 2,  0, "2/4=0.5 → 得 0（0 是偶数，舍去）"),
        (3, 2,  1, "3/4=0.75 → 最近的是 1"),
        (-3, 2, -1, "-3/4=-0.75 → 最近的是 -1"),
        (7, 0,  7, "shift=0 时原样返回（必须单独分支，因为 1<<-1 未定义）"),
        (-1, 0, -1, "shift=0 且负数"),
    ]
    ok = True
    for x, s, expect, note in table:
        got = int(round_shift(np.int64(x), s))
        good = (got == expect)
        ok &= good
        if verbose:
            flag = "OK  " if good else "FAIL"
            print(f"  [{flag}] round_shift({x:>4}, {s}) = {got:>4} 期望 {expect:>4}   {note}")
    return ok


def test_wrap_int32(verbose=True):
    """验证模 2³² 回绕的边界行为。"""
    cases = [
        (INT32_MAX,     INT32_MAX, "最大正值不回绕"),
        (INT32_MAX + 1, INT32_MIN, "最大值 +1 回绕到最小负值"),
        (INT32_MIN,     INT32_MIN, "最小负值不回绕"),
        (INT32_MIN - 1, INT32_MAX, "最小值 -1 回绕到最大正值"),
        (0,             0,         "零"),
        (2 ** 32,       0,         "整圈归零"),
        (2 ** 32 + 5,   5,         "整圈 +5"),
        (-(2 ** 32) - 5, -5,       "负整圈 -5"),
    ]
    ok = True
    for x, expect, note in cases:
        got = int(wrap_int32(np.array([x], dtype=np.int64))[0])
        good = (got == expect)
        ok &= good
        if verbose:
            flag = "OK  " if good else "FAIL"
            print(f"  [{flag}] wrap_int32({x:>14}) = {got:>12} 期望 {expect:>12}   {note}")
    return ok


def test_four_traps(verbose=True):
    """
    四个必须绕开的坑。**v2.0 全部重写** —— v1.0 在舍入规则上写反了。
    """
    ok = True

    # --- 坑 1：half-up 是错的，必须用 half-to-even ---
    import math
    x = np.int64(10)
    half_up = int((x + (1 << 1)) >> 2)          # 常见错误写法：(x + 2^(s-1)) >> s
    correct = int(round_shift(x, 2))
    if verbose:
        print(f"  坑1  (x + (1<<(s-1))) >> s  = {half_up:>4}   ← half-up，**错误**")
        print(f"       协议要求 half-to-even    = {correct:>4}   ← 正确")
        print(f"       x=10, s=2 时 10/4=2.5，向偶数取整应为 2")
    ok &= (half_up != correct)

    # --- 坑 2：C++ 的 / 与 Verilog 的 >>> 对负数行为不同 ---
    c_div = int(math.trunc(-7 / 4))                 # = -1，C/C++ 向零截断
    verilog = int(np.int64(-7) >> np.int64(2))      # = -2，算术右移 = floor
    if verbose:
        print(f"  坑2  C/C++  -7 / 4    = {c_div:>4}     ← 向零截断")
        print(f"       Verilog -7 >>> 2 = {verilog:>4}     ← 向下取整")
        print(f"       round_shift(-7, 2) = {int(round_shift(np.int64(-7), 2)):>4}  ← 与 Verilog 一致")
    ok &= (c_div != verilog)

    # --- 坑 3：饱和必须在加 zero_point 之后 ---
    acc = np.array([100], dtype=np.int64)
    m = np.array([1 << 30], dtype=np.int64)
    sh = 30
    zp = 50
    mid = int(round_shift(acc * m, sh)[0])
    correct_v = int(saturate_int8(np.array([mid + zp], dtype=np.int64))[0])
    wrong_v = int(saturate_int8(np.array([mid], dtype=np.int64))[0]) + zp
    if verbose:
        print(f"  坑3  中间值(requant 后) = {mid},  zero_point = {zp}")
        print(f"       正确顺序(先加 zp 后饱和) : {correct_v:>4}   ← 合法 int8")
        print(f"       错误顺序(先饱和后加 zp) : {wrong_v:>4}   ← 越界！不是合法 int8")
        print(f"       本项目 zero_point 固定为 0，此坑暂不触发；")
        print(f"       一旦改用非对称量化，错误顺序立刻全错")
    ok &= (correct_v != wrong_v)

    # --- 坑 4：累加器必须模 2³² 回绕，不能抛异常 ---
    wrapped = int(wrap_int32(np.array([INT32_MAX + 1], dtype=np.int64))[0])
    if verbose:
        print(f"  坑4  2³¹ = {2**31}，回绕后 = {wrapped}")
        print(f"       v1.0 在此抛异常，会直接拒绝 A 的合法用例 int32_wrap_both_signs")
        print(f"       协议 §2.3：accumulation is modulo 2^32")
    ok &= (wrapped == INT32_MIN)

    return ok


def test_requantize_matches_cpp(verbose=True):
    """
    逐元素验证 requant 与 A 的 HLS `.cpp:3-31` 完全一致。
    这里**重新独立实现一遍** A 的 C++ 逻辑作为 oracle，避免循环论证。
    """
    def cpp_oracle(acc, mult, sh, zp):
        acc, mult, sh, zp = int(acc), int(mult), int(sh), int(zp)
        prod = acc * mult
        rounded = prod
        if sh != 0:
            den = 1 << sh
            q = prod >> sh                       # Python 的 >> 对负数即 floor
            mask = den - 1
            r = prod & mask                      # 对负数也给出正确的非负余数
            half = den >> 1
            if r > half or (r == half and (q & 1)):
                q += 1
            rounded = q
        shifted = rounded + zp
        return max(-128, min(127, shifted))

    rng = np.random.default_rng(20261010)
    n_bad = 0
    n_total = 0
    for _ in range(20000):
        acc = int(rng.integers(-(2 ** 31), 2 ** 31))
        mult = int(rng.integers(-(2 ** 31), 2 ** 31))
        sh = int(rng.integers(0, 63))
        zp = int(rng.integers(-128, 128))
        expect = cpp_oracle(acc, mult, sh, zp)
        got = int(requantize(np.array([[acc]], dtype=np.int64),
                             [mult], [sh], zp)[0, 0])
        n_total += 1
        if got != expect:
            n_bad += 1
            if n_bad <= 3 and verbose:
                print(f"    不匹配: acc={acc} M={mult} shift={sh} zp={zp} "
                      f"cpp={expect} python={got}")
    if verbose:
        print(f"  20000 组随机 (acc, M, shift, zp) 与 C++ oracle 对比："
              f"{'全部一致' if n_bad == 0 else f'{n_bad} 处不一致'}")
    return n_bad == 0


def test_multiplier_accuracy(verbose=True):
    """验证 quantize_multiplier 的定点近似精度。"""
    rng = np.random.default_rng(7)
    worst = 0.0
    for _ in range(2000):
        m = float(10 ** rng.uniform(-4, 2))
        M, sh = quantize_multiplier(m)
        approx = M / (2.0 ** sh)
        rel = abs(approx - m) / m
        worst = max(worst, rel)
    if verbose:
        print(f"  2000 个随机乘子，最大相对误差 = {worst:.3e}   "
              f"（32 位定点理论极限约 2^-31 ≈ 4.7e-10）")
    return worst < 1e-9


def test_bias_derivation(verbose=True):
    """
    验证 bias_int 的推导：bias_folded ≈ s_w * s_in * bias_int。
    这一步推错会导致整体系统性偏差，所以单独测。
    """
    rng = np.random.default_rng(11)
    Cout, K, Cin = 6, 3, 4
    w = rng.standard_normal((Cout, K, K, Cin)) * 0.3
    conv_bias = rng.standard_normal(Cout) * 0.2
    gamma = np.abs(rng.standard_normal(Cout)) + 0.5
    beta = rng.standard_normal(Cout) * 0.1
    mean = rng.standard_normal(Cout) * 0.2
    var = np.abs(rng.standard_normal(Cout)) + 0.5

    w_f, b_f, _, _ = fold_bn(w, conv_bias, gamma, beta, mean, var)
    s_w = np.max(np.abs(w_f.reshape(Cout, -1)), axis=1) / 127.0
    s_in = 0.02

    bias_int = np.rint(round_half_away_from_zero(b_f / (s_w * s_in))).astype(np.int64)
    reconstructed = s_w * s_in * bias_int
    err = np.abs(reconstructed - b_f)
    lsb = s_w * s_in
    n_lsb = err / lsb

    if verbose:
        print(f"  bias_int 的一个 LSB = s_w * s_in，各通道范围 "
              f"[{lsb.min():.3e}, {lsb.max():.3e}]")
        print(f"  最大误差 = {n_lsb.max():.3f} 个 LSB  ← 应 <= 0.5（量化固有误差）")
    return bool(n_lsb.max() <= 0.5 + 1e-9)


def test_fold_bn_matches_a(verbose=True):
    """
    验证 fold_bn 与 A 的 `int8_conv.fold_batch_norm` 在**代数上等价**。

    A 写的是 `beta + (conv_bias - mean) * bn_scale`
    本文写的是 `a*conv_bias + b`，其中 b = beta - a*mean。
    展开后完全相同：a*conv_bias + beta - a*mean ≡ beta + (conv_bias-mean)*a

    ⚠️ 但**浮点结果不会逐位相同** —— 两条式子的计算顺序不同，
      舍入误差落在最后一位（约 1e-16，即机器精度 2.22e-16）。
      这不是 bug，而是浮点的固有性质。

    ★ 这正好演示了**我们为什么要量化成整数**：
      浮点加法不满足结合律，同一个数学式子的不同写法会给出不同结果，
      硬件因此无法自由重排运算顺序。而整数加法满足结合律与交换律，
      所以并行加速器才能成立。详见 docs/quantization.md 第 0 节。
    """
    rng = np.random.default_rng(3)
    Cout = 5
    w = rng.standard_normal((Cout, 3, 3, 4))
    conv_bias = rng.standard_normal(Cout)
    gamma = np.abs(rng.standard_normal(Cout)) + 0.5
    beta = rng.standard_normal(Cout)
    mean = rng.standard_normal(Cout)
    var = np.abs(rng.standard_normal(Cout)) + 0.5
    eps = 1e-5

    w_f, b_f, _, _ = fold_bn(w, conv_bias, gamma, beta, mean, var, eps)

    # A 的写法
    bn_scale = gamma / np.sqrt(var + eps)
    a_w = w * bn_scale.reshape(-1, 1, 1, 1)
    a_b = beta + (conv_bias - mean) * bn_scale

    dw = float(np.max(np.abs(w_f - a_w)))
    db = float(np.max(np.abs(b_f - a_b)))
    # 用相对容差判断"代数等价"，而非逐位相等
    w_ok = bool(np.allclose(w_f, a_w, rtol=1e-12, atol=1e-12))
    b_ok = bool(np.allclose(b_f, a_b, rtol=1e-12, atol=1e-12))

    if verbose:
        print(f"  权重最大差异 = {dw:.3e}    bias 最大差异 = {db:.3e}")
        print(f"  机器精度 eps ≈ {np.finfo(np.float64).eps:.3e}（差异应在此量级）")
        if w_ok and b_ok:
            print(f"  → 与 A 的 fold_batch_norm **代数等价**")
            print(f"     逐位不完全相同是浮点计算顺序所致，非实现差异；")
            print(f"     量化为整数后此差异消失（这正是量化的动机之一）")
        else:
            print(f"  → 差异超出浮点舍入量级，需排查")
    return w_ok and b_ok


def test_end_to_end_accuracy(verbose=True):
    """
    端到端：FP32 结果 vs INT8 结果（反量化后）的误差。
    用来确认量化损失在"1 个 LSB 量级"，而不是出现了实现 bug。
    """
    from fp32_reference import conv2d as conv2d_fp32, relu as relu_fp32

    rng = np.random.default_rng(2026)
    Cout, K, Cin, H, W = 8, 3, 4, 12, 12

    # ★ v2.0：全部改用协议布局 NCHW / OIHW
    x = (rng.standard_normal((1, Cin, H, W)).astype(np.float32) * 0.5)      # NCHW
    w = (rng.standard_normal((Cout, Cin, K, K)).astype(np.float32) * 0.3)   # OIHW
    b = rng.standard_normal(Cout).astype(np.float32) * 0.1

    y_fp32 = relu_fp32(conv2d_fp32(x, w, b, stride=1, pad=1))

    s_in = float(np.max(np.abs(x))) / 127.0
    s_out = float(np.max(np.abs(y_fp32))) / 127.0

    x_q = quantize_with_scale(x, s_in)
    q_w, params = prepare_int8_layer(w, b, s_in, s_out,
                                     K=K, stride=1, pad=1, Cin=Cin, Cout=Cout,
                                     activation="relu")
    q, acc = conv2d_int8(x_q, q_w, params, return_accumulator=True,
                         layout="NCHW", weight_layout="OIHW")
    y_deq = dequantize(q, s_out)

    err = np.abs(y_deq - y_fp32.astype(np.float64))
    lsb = s_out

    if verbose:
        print(f"  输出 scale (1 个 LSB) = {lsb:.4e}")
        print(f"  最大绝对误差          = {err.max():.4e}  ({err.max()/lsb:.2f} 个 LSB)")
        print(f"  平均绝对误差          = {err.mean():.4e}  ({err.mean()/lsb:.2f} 个 LSB)")
        print(f"  累积器口径            = 含 bias（与 A 的 accumulators[] 同口径）")

    return bool(err.max() < 3.0 * lsb)


def self_test(verbose=True):
    """跑全部自检。`python int8_reference.py` 会调用这个。"""
    tests = [
        ("舍入规则 R2 (round_shift, 向偶数)", test_round_shift_semantics),
        ("模 2³² 回绕 (wrap_int32)", test_wrap_int32),
        ("requant 与 C++ oracle 逐元素一致", test_requantize_matches_cpp),
        ("四个必须绕开的坑", test_four_traps),
        ("BN 折叠与 A 的实现等价", test_fold_bn_matches_a),
        ("requant 定点乘子精度", test_multiplier_accuracy),
        ("bias_int 推导正确性", test_bias_derivation),
        ("端到端 INT8 vs FP32 精度", test_end_to_end_accuracy),
    ]
    results = []
    for title, fn in tests:
        if verbose:
            print()
            print(f"--- {title} " + "-" * max(0, 60 - len(title)))
        try:
            ok = bool(fn(verbose=verbose))
        except Exception as exc:      # noqa: BLE001
            ok = False
            if verbose:
                print(f"  [FAIL] 抛异常: {type(exc).__name__}: {exc}")
        results.append((title, ok))
        if verbose:
            print(f"  => {'通过' if ok else '失败'}")

    if verbose:
        print()
        print("=" * 78)
        passed = sum(1 for _, ok in results if ok)
        print(f"自检结果: {passed}/{len(results)} 通过")
        for title, ok in results:
            print(f"  [{'OK  ' if ok else 'FAIL'}] {title}")
        print("=" * 78)

    return all(ok for _, ok in results)


if __name__ == "__main__":
    print("=" * 78)
    print("INT8 量化黄金模型自检  (v2.0 —— 对齐协议 1.0)")
    print("=" * 78)
    ok = self_test()
    raise SystemExit(0 if ok else 1)
