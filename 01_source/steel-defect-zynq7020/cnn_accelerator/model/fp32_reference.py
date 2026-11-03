"""
fp32_reference.py —— FP32 黄金模型
==================================

**版本 v2.0（2026-10-10）—— 布局对齐协议 1.0（NCHW / OIHW）**

作用
----
1. 提供"数学上正确"的卷积结果，作为量化精度的**基线**（baseline）。
2. 提供 BN 折叠之前的原始权重和 BN 参数。
3. **不参与硬件的 bit-exact 比对** —— 硬件算的是 INT8，
   和 FP32 天然不可能逐位相同。FP32 只用来回答"量化掉了多少精度"。

包含两个版本的卷积：
  - `conv2d_naive()`  ：七重循环，慢，但一眼能看懂，用来验证下面那个
  - `conv2d()`        ：向量化版本，快，日常使用

两者在浮点下**不会逐位相同**（原因见 `self_test` 末尾的说明），
但差值应该在 1e-5 量级。

布局（协议 §2.2）
-----------------
    输入激活  NCHW  `(N, Cin, H, W)`
    输出激活  NCHW  `(N, Cout, Hout, Wout)`
    权重      OIHW  `(Cout, Cin, Kh, Kw)`
"""

import numpy as np

from tensor_utils import (extract_windows, conv_output_size,
                          to_ohwi, from_nhwc)


# ----------------------------------------------------------------------------
# 1. 教学版：七重循环
# ----------------------------------------------------------------------------

def conv2d_naive(x, w, b=None, stride=1, pad=0):
    """
    教科书式卷积。故意写成最笨的形式，因为这样才能一眼看出"卷积在干什么"。

    参数
    ----
    x : (N, Cin, Hin, Win)   float32   —— 输入激活，**NCHW**（协议布局）
    w : (Cout, Cin, Kh, Kw)  float32   —— 权重，**OIHW**（协议布局）
    b : (Cout,)              float32   —— 偏置，可以传 None
    stride, pad : 见 docs/spec.md 第 2 节

    返回
    ----
    y : (N, Cout, Hout, Wout) float32

    循环顺序说明（★ 与 A 的 HLS `.cpp:226-233` 完全一致，建议记住）
    -------------------------------------------------------------
        n  →  oc → oh → ow        ← 这四个是"输出"的四个维度
                    └ ic → kh → kw ← 这三个是"累加"的三个维度

    硬件加速器做的事情，本质就是把最内层的 ic/kh/kw 三个循环
    **展开成并行的乘法器阵列**，让它们在一个时钟周期内同时算完。
    这就是 HLS 里 `TN` / `TM` 参数的来源。

    ⚠️ 累加顺序 `Cin → Ky → Kx` 是协议规定（§2.3）。
      对**整数**累加，顺序不影响结果；但对**浮点**累加，顺序会影响
      最后几位 —— 这正是我们量化成整数的动机之一。
    """
    N, Cin, Hin, Win = x.shape
    Cout, Cin_w, Kh, Kw = w.shape

    if Cin != Cin_w:
        raise ValueError(f"输入通道数不匹配: x 的 Cin={Cin}, w 的 Cin={Cin_w}")

    Hout = conv_output_size(Hin, Kh, stride, pad)
    Wout = conv_output_size(Win, Kw, stride, pad)

    # 先补零，得到 (N, Cin, Hin+2*pad, Win+2*pad)
    if pad:
        xp = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)),
                    mode='constant', constant_values=0)
    else:
        xp = x

    y = np.zeros((N, Cout, Hout, Wout), dtype=np.float32)

    for n in range(N):
        for oc in range(Cout):
            for oh in range(Hout):
                for ow in range(Wout):
                    acc = np.float32(0.0)
                    # ★ 协议规定的累加顺序：Cin → Ky → Kx
                    for ic in range(Cin):
                        for kh in range(Kh):
                            for kw in range(Kw):
                                acc += (xp[n, ic, oh * stride + kh, ow * stride + kw]
                                        * w[oc, ic, kh, kw])
                    if b is not None:
                        acc += np.float32(b[oc])
                    y[n, oc, oh, ow] = acc

    return y


# ----------------------------------------------------------------------------
# 2. 生产版：向量化
# ----------------------------------------------------------------------------

def conv2d(x, w, b=None, stride=1, pad=0,
           layout="NCHW", weight_layout="OIHW", output_layout=None):
    """
    向量化卷积。结果和 `conv2d_naive` 一致（浮点意义下），但快几百倍。

    参数
    ----
    x : 输入激活，布局由 `layout` 指定（默认 NCHW）
    w : 权重，布局由 `weight_layout` 指定（默认 OIHW）
    layout : `"NCHW"`（默认，协议）| `"NHWC"`
    weight_layout : `"OIHW"`（默认，协议）| `"OHWI"`
    output_layout : 输出布局；默认与 `layout` 相同

    核心是一行 einsum：
        'nhwikl,okli->nhwo'
         ↑         ↑
     输入窗口    权重

    下标含义：
        n = batch, h = 输出行, w = 输出列, o = 输出通道
        i = 输入通道(Cin), k = 核行, l = 核列
    左边缺少 o，右边缺少 n/h/w，所以 einsum 会在 i、k、l 三个维度上求和，
    并把 o 广播到每个 (n,h,w) 位置 —— 这正好就是卷积的定义。

    为什么要向量化？黄金模型要跑几百组测试向量和校准数据，
    纯 Python 循环太慢，慢到会拖垮整个团队的工作节奏。
    """
    if output_layout is None:
        output_layout = layout

    w_ohwi = to_ohwi(w, weight_layout)
    N, Cin = x.shape[0], x.shape[1 if layout == "NCHW" else 3]
    Cout, Kh, Kw, Cin_w = w_ohwi.shape
    if Cin != Cin_w:
        raise ValueError(f"输入通道数不匹配: x 的 Cin={Cin}, w 的 Cin={Cin_w}")

    win = extract_windows(x, Kh, stride, pad, layout=layout)   # (N,Hout,Wout,Cin,Kh,Kw)
    y = np.einsum('nhwikl,okli->nhwo', win, w_ohwi, optimize=True)
    y = np.asarray(y, dtype=np.float32)

    if b is not None:
        y = y + np.asarray(b, dtype=np.float32).reshape(1, 1, 1, Cout)

    if output_layout != "NHWC":
        y = from_nhwc(y, output_layout)

    return y


# ----------------------------------------------------------------------------
# 3. 激活函数与池化
# ----------------------------------------------------------------------------

def relu(x):
    """ReLU：负数归零。硬件里就是一个"看符号位"的比较器，几乎不花钱。"""
    return np.maximum(x, np.float32(0.0))


def leaky_relu(x, alpha=0.1):
    """
    LeakyReLU：负数不是归零，而是乘一个很小的系数 alpha。
    硬件里需要一次乘法，比 ReLU 贵一点。
    """
    x = np.asarray(x, dtype=np.float32)
    return np.where(x >= 0, x, (x * np.float32(alpha)).astype(np.float32))


def maxpool2x2(x, stride=2, layout="NCHW"):
    """
    2x2 最大池化：在每个 2x2 的小块里取最大值。

    参数
    ----
    x : (N, C, H, W)（NCHW）或 (N, H, W, C)（NHWC），任意 dtype

    硬件实现要点：它只需要一个比较器和一个行缓存，
    所以"Conv + Pooling 融合"是性价比很高的优化 —— 省掉一次
    完整的特征图写回和读回 DDR。

    ⚠️ 协议 1.0 把 pooling 排除在 MVP 之外，本函数保留供扩展使用。
    """
    win = extract_windows(x, 2, stride=stride, pad=0, layout=layout)
    out = win.max(axis=(-1, -2))            # (N, Hout, Wout, C)
    if layout != "NHWC":
        out = from_nhwc(out, layout)
    return out


# ----------------------------------------------------------------------------
# 4. 自检
# ----------------------------------------------------------------------------

def self_test(verbose=True):
    """
    验证向量化版本和循环版本结果一致。

    ★ 这里用 `np.allclose` 而不是逐位相等 —— 这不是偷懒，而是**必须**：
      浮点加法不满足结合律，两种实现把同样的数按不同顺序相加，
      结果必然有 1e-7 量级的差异。

      这正是我们用 INT8 的理由之一：
      **整数加法严格满足结合律和交换律，累加顺序可以任意重排**，
      硬件才有自由去做并行和流水线。详见 docs/quantization.md 第 0 节。
    """
    rng = np.random.default_rng(20261010)

    cases = [
        # (N, Cin, Cout, H, W, K, stride, pad, 说明)
        (1, 2, 3, 5, 5, 3, 1, 0, "无 padding 的小图"),
        (1, 3, 4, 8, 8, 3, 1, 1, "有 padding"),
        (1, 4, 5, 6, 6, 1, 1, 0, "1x1 卷积"),
        (1, 3, 2, 7, 9, 3, 1, 1, "奇数尺寸（非方形）"),
        (2, 2, 3, 4, 4, 3, 1, 1, "batch=2"),
    ]

    all_ok = True
    for (N, Cin, Cout, H, W, K, stride, pad, note) in cases:
        x = rng.standard_normal((N, Cin, H, W)).astype(np.float32)      # NCHW
        w = rng.standard_normal((Cout, Cin, K, K)).astype(np.float32)   # OIHW
        b = rng.standard_normal(Cout).astype(np.float32)

        y_naive = conv2d_naive(x, w, b, stride, pad)
        y_fast = conv2d(x, w, b, stride, pad)

        max_diff = float(np.max(np.abs(y_naive.astype(np.float64)
                                      - y_fast.astype(np.float64))))
        ok = np.allclose(y_naive, y_fast, rtol=1e-4, atol=1e-4)
        all_ok &= ok

        if verbose:
            flag = "OK  " if ok else "FAIL"
            print(f"  [{flag}] {note:<28} shape={str(y_fast.shape):<18} "
                  f"最大差异={max_diff:.3e}")

    # 顺带验证布局转换不改变数值
    x = rng.standard_normal((1, 3, 6, 6)).astype(np.float32)
    w = rng.standard_normal((4, 3, 3, 3)).astype(np.float32)
    y_nchw = conv2d(x, w, pad=1)
    y_nhwc = conv2d(np.transpose(x, (0, 2, 3, 1)), np.transpose(w, (0, 2, 3, 1)),
                    pad=1, layout="NHWC", weight_layout="OHWI")
    lay_ok = np.allclose(y_nchw, np.transpose(y_nhwc, (0, 3, 1, 2)),
                         rtol=1e-6, atol=1e-6)
    all_ok &= lay_ok
    if verbose:
        print(f"  [{'OK  ' if lay_ok else 'FAIL'}] NCHW 与 NHWC 路径结果一致")

    if verbose:
        print()
        print("  说明：这里的差异来自浮点加法顺序不同，是正常现象。")
        print("        硬件比对用的是 INT8，整数运算必须做到 0 差异。")

    return all_ok


if __name__ == "__main__":
    print("=" * 78)
    print("FP32 黄金模型自检  (v2.0 —— NCHW/OIHW)")
    print("=" * 78)
    ok = self_test()
    print()
    print("结果:", "全部通过" if ok else "有失败项")
    raise SystemExit(0 if ok else 1)
