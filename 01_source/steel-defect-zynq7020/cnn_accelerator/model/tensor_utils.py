"""
tensor_utils.py —— 张量布局工具
================================

**版本 v2.0（2026-10-10）—— 外部布局对齐协议 1.0（NCHW / OIHW）**

本模块是全项目唯一处理"张量怎么摆放"的地方。
FP32 模型和 INT8 模型共用同一套滑窗逻辑，
避免"两个模型各自实现一遍，结果差一点点"这种最难查的 bug。

----------------------------------------------------------------------
布局约定（依据 docs/interface.md §2.2，A 冻结）
----------------------------------------------------------------------
| 张量        | 布局       | 索引公式                                        |
|-------------|------------|-------------------------------------------------|
| 输入激活    | **NCHW**   | `((n*Cin  + ic)*H    + y)*W    + x`             |
| 输出激活    | **NCHW**   | `((n*Cout + oc)*Hout + y)*Wout + x`             |
| 权重        | **OIHW**   | `((oc*Cin + ic)*3 + ky)*3 + kx`                 |

★ v1.0 用的是 NHWC / OHWI，**已被协议否决**。
  原因：协议 1.0 的 MVP 架构是"整包缓冲 → 计算 → 整包输出"，
  数据按通道整块搬运（NCHW）最自然；
  而 v1.0 论证 NHWC 的前提是"像素级流式行缓存"，那是**另一种架构**。
  架构决策变了，布局的理由也跟着反转 —— 这是很好的报告素材。

⚠️ 内部实现仍在必要时转成 NHWC（`np.transpose` 是**视图**，不拷贝数据），
   因为 NumPy 的滑窗在通道末位时最直观。**外部接口一律 NCHW/OIHW。**
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def conv_output_size(size, K, stride, pad):
    """
    卷积输出尺寸公式（协议 §2.1）：

        Hout = floor((H + 2*pad - K) / stride) + 1

    K=3、stride=1 时退化为协议里写的 `H + 2*padding - 2`。

    通俗理解：用 K 宽的取景框在补过边的图上滑，能停几次。
    """
    return (size + 2 * pad - K) // stride + 1


def to_nhwc(x, layout="NCHW"):
    """
    把输入转成 NHWC 视图。

    NCHW `(N,C,H,W)` → NHWC `(N,H,W,C)`：只是重排轴顺序。
    `np.transpose` 返回**视图**，不复制数据、几乎不花时间。
    """
    if layout == "NCHW":
        if x.ndim != 4:
            raise ValueError(f"NCHW 输入必须是 4 维，收到 {x.ndim} 维")
        return np.transpose(x, (0, 2, 3, 1))
    if layout == "NHWC":
        return x
    raise ValueError(f"未知布局: {layout}（支持 'NCHW' | 'NHWC'）")


def to_ohwi(w, weight_layout="OIHW"):
    """
    把权重转成 OHWI 视图。

    OIHW `(Cout,Cin,K,K)` → OHWI `(Cout,K,K,Cin)`。
    """
    if weight_layout == "OIHW":
        if w.ndim != 4:
            raise ValueError(f"OIHW 权重必须是 4 维，收到 {w.ndim} 维")
        return np.transpose(w, (0, 2, 3, 1))
    if weight_layout == "OHWI":
        return w
    raise ValueError(f"未知权重布局: {weight_layout}（支持 'OIHW' | 'OHWI'）")


def from_nhwc(y, layout="NCHW"):
    """把 NHWC 输出转回目标布局。"""
    if layout == "NCHW":
        return np.transpose(y, (0, 3, 1, 2))
    if layout == "NHWC":
        return y
    raise ValueError(f"未知布局: {layout}")


def extract_windows(x, K, stride=1, pad=0, layout="NCHW"):
    """
    把输入张量切成一个个 K x K 的滑窗。

    参数
    ----
    x : ndarray，形状按 `layout`
        · `"NCHW"`（默认，**协议布局**）：`(N, C, H, W)`
        · `"NHWC"`（内部表示）：`(N, H, W, C)`
    K : 卷积核尺寸
    stride : 步长（协议固定 1）
    pad : 边缘补零圈数（协议允许 0 或 1）
    layout : 输入布局

    返回
    ----
    ndarray，形状 **(N, Hout, Wout, C, K, K)**

    ★ 无论输入是 NCHW 还是 NHWC，**返回值形状都一样** ——
      这样上层代码不需要关心输入是什么布局。

    怎么理解返回形状：对每一个输出位置 (oh, ow)，我们都拿到了一个
    (C, K, K) 的小立方体，也就是"这个输出点要看的输入窗口"。
    后面只要拿它和 (Cout, K, K, C) 的权重做乘加，就得到这一点的输出。

    通俗理解：像用一张 K×K 的**取景框**在图上从左到右、从上到下扫一遍，
    每停一次就把框里的内容"复印"一份。
    `sliding_window_view` 返回的是**视图**，所以复印是零成本的
    （不占内存、不费时间）—— 这是 NumPy 里做滑窗的标准技巧。
    """
    x = to_nhwc(x, layout)                    # → (N, H, W, C)

    if pad:
        # 在 H 和 W 两个轴上各补 pad 圈 0，N 和 C 轴不补
        x = np.pad(x, ((0, 0), (pad, pad), (pad, pad), (0, 0)),
                   mode='constant', constant_values=0)

    # axis=(1, 2) 表示在 H、W 两个轴上开窗
    win = sliding_window_view(x, (K, K), axis=(1, 2))

    if stride != 1:
        # 步长大于 1 时，在输出位置上每隔 stride 取一个
        win = win[:, ::stride, ::stride]

    return win


def describe(name, arr):
    """打印一个张量的形状和取值范围 —— 排查问题时最快的第一个动作。"""
    a = np.asarray(arr)
    print(f"  {name:<16} shape={str(a.shape):<20} dtype={str(a.dtype):<8} "
          f"min={a.min():>12} max={a.max():>12}")
