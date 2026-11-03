r"""
train_quantize_eval.py —— 训练 / 量化 / 整数评估（纯 numpy，无框架依赖）
================================================================================

--------------------------------------------------------------------------------
这个脚本在做什么
--------------------------------------------------------------------------------
硬件结构被 B 的冻结基线锁死（且已在 10/19 实测通过）：

    HConv1 1→4, 3×3, stride=1, p=1, 32×32
    HConv2 4→8, 3×3, stride=1, p=1, 32×32
    PS: ReLU → MaxPool2×2 → FC(2048→6) → argmax

所以**网络形状不是我挑的**，是硬件能力推出来的。我能决定的只有权重。

关键设计（为什么层间不需要在 PS 重定标）：

    conv1 的输出 scale  = conv2 的输入 scale  = s1
    两层 output zero-point 都冻结为 0（A 的决定）
    ⇒ conv1 输出的 signed INT8 可以**直接**喂给 conv2，
      中间只需要 ReLU（整数 max(q,0)），不需要任何乘除。

这也是 B 在 10/19 板测里验证过的那条通路（4096 字节 RX 经 ARM 回灌到 4→8）。

--------------------------------------------------------------------------------
最重要的一点：报告的成绩来自**整数管线**，不是浮点
--------------------------------------------------------------------------------
常见做法是训练完报浮点准确率，然后"假设"量化后差不多。**那不成立** ——
量化误差可能让准确率掉好几个点，而报告里看不出来。

所以本脚本的最后一步是：丢掉浮点权重，**只用 INT8 权重 + INT32 累加 +
向偶数舍入的定点乘子**跑一遍测试集，报告那个成绩。浮点的只作对照。

--------------------------------------------------------------------------------
训练为什么能在 numpy 上做
--------------------------------------------------------------------------------
网络很小：conv1 36 个权重、conv2 288 个、FC 12,288 个。样本 1260 张 32×32。
用 im2col + 矩阵乘做前向/反向，纯 numpy 完全够用，且**每一步都能审计** ——
与这个项目「黄金模型 + 可复现」的路线一致。

用法
--------------------------------------------------------------------------------
    python train_quantize_eval.py --epochs 30
    python train_quantize_eval.py --epochs 30 --seed 1
"""

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_DATA, "..", "cnn_accelerator", "model"))

import neu_cls_paths as ncp                                        # noqa: E402
from int8_reference import (Int8ConvParams, conv2d_int8,           # noqa: E402
                            prepare_int8_layer, round_shift)

MANIFESTS = os.path.join(_DATA, "manifests")
OUT_DIR = os.path.join(_DATA, "model")
CLASS_ORDER = ["Cr", "In", "Pa", "PS", "RS", "Sc"]
CLASS_NAME = {"Cr": "Crazing", "In": "Inclusion", "Pa": "Patches",
              "PS": "Pitted Surface", "RS": "Rolled-in Scale",
              "Sc": "Scratches"}
K, PAD = 3, 1


# ===========================================================================
# 1. 数据
# ===========================================================================

def load_split():
    from PIL import Image
    img_dir = ncp.image_dir()
    sp = json.load(open(os.path.join(MANIFESTS, "split_v1.json"),
                        encoding="utf-8"))
    inv = json.load(open(os.path.join(MANIFESTS, "inventory.json"),
                         encoding="utf-8"))
    cls_of = {r["file"]: r["class_prefix"] for r in inv["files"]}
    calib = json.load(open(os.path.join(OUT_DIR, "input_calibration_v1.json"),
                           encoding="utf-8"))
    scale = float(calib["input_scale"])

    def build(files):
        X = np.zeros((len(files), 32, 32), dtype=np.uint8)
        y = np.zeros(len(files), dtype=np.int64)
        for i, fn in enumerate(files):
            a = np.asarray(Image.open(os.path.join(img_dir, fn)).convert("L"),
                           dtype=np.uint8)
            X[i] = np.asarray(Image.fromarray(a).resize((32, 32),
                                                       Image.BILINEAR),
                              dtype=np.uint8)
            y[i] = CLASS_ORDER.index(cls_of[fn])
        return X, y

    out = {}
    for name in ("train", "val", "test"):
        out[name] = build(sp["assignment"][name])
    return out, scale, sp


def to_q(u8, scale):
    """按 A 的公式量化：q = clip(round_ties_to_even(x/scale), -128, 127)。"""
    x = u8.astype(np.float64) / 255.0
    return np.clip(np.rint(x / scale), -128, 127).astype(np.int8)


# ===========================================================================
# 2. numpy 前向/反向
# ===========================================================================

def im2col(x, k=K, pad=PAD):
    """x: (N,C,H,W) -> (N*H*W, C*k*k)，stride=1、same padding。"""
    N, C, H, W = x.shape
    if pad:
        x = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)), mode="constant")
    cols = np.zeros((N, H, W, C, k, k), dtype=x.dtype)
    for dy in range(k):
        for dx in range(k):
            cols[:, :, :, :, dy, dx] = x[:, :, dy:dy + H, dx:dx + W].transpose(
                0, 2, 3, 1)
    return cols.reshape(N * H * W, C * k * k)


def col2im(dcols, shape, k=K, pad=PAD):
    N, C, H, W = shape
    d = dcols.reshape(N, H, W, C, k, k)
    dx = np.zeros((N, C, H + 2 * pad, W + 2 * pad), dtype=d.dtype)
    for dy in range(k):
        for dx_ in range(k):
            dx[:, :, dy:dy + H, dx_:dx_ + W] += d[:, :, :, :, dy, dx_].transpose(
                0, 3, 1, 2)
    if pad:
        dx = dx[:, :, pad:-pad, pad:-pad]
    return dx


def conv_forward(x, w, b):
    """x (N,Cin,H,W), w (Cout,Cin,k,k), b (Cout,) -> y (N,Cout,H,W)。"""
    N, Cin, H, W = x.shape
    Cout = w.shape[0]
    cols = im2col(x)                                   # (N*H*W, Cin*k*k)
    Wm = w.reshape(Cout, -1)                           # (Cout, Cin*k*k)
    y = cols @ Wm.T + b                                # (N*H*W, Cout)
    return y.reshape(N, H, W, Cout).transpose(0, 3, 1, 2), cols


def conv_backward(dy, cols, x_shape, w):
    N, Cin, H, W = x_shape
    Cout = w.shape[0]
    dyf = dy.transpose(0, 2, 3, 1).reshape(-1, Cout)   # (N*H*W, Cout)
    dW = (dyf.T @ cols).reshape(w.shape)
    db = dyf.sum(axis=0)
    dcols = dyf @ w.reshape(Cout, -1)
    dx = col2im(dcols, x_shape)
    return dx, dW, db


def pool2_forward(x):
    """2×2 最大池化。同时记住 argmax 位置，供反向正确路由梯度。"""
    N, C, H, W = x.shape
    xr = x.reshape(N, C, H // 2, 2, W // 2, 2).transpose(0, 1, 2, 4, 3, 5)
    flat = xr.reshape(N, C, H // 2, W // 2, 4)
    idx = flat.argmax(axis=-1)                       # (N,C,H/2,W/2)
    out = np.take_along_axis(flat, idx[..., None], axis=-1)[..., 0]
    return out, idx


def pool2_backward(dout, x_shape, idx):
    """
    最大池化的反向：梯度**只**回传给当年取到最大值的那一个位置。

    ★ 不能用「均摊到 4 个位置」—— 那不是最大池化的梯度，等于假装是平均池化。
      虽然也能"训练起来"（loss 会降），但学到的特征和真实前向不一致，
      属于隐蔽的错误实现，最终准确率会无谓地低。
    """
    N, C, H, W = x_shape
    flat = np.zeros((N, C, H // 2, W // 2, 4), dtype=dout.dtype)
    np.put_along_axis(flat, idx[..., None], dout[..., None], axis=-1)
    return flat.reshape(N, C, H // 2, W // 2, 2, 2).transpose(
        0, 1, 2, 4, 3, 5).reshape(N, C, H, W)


class Net:
    """Conv1(1→4) → ReLU → Conv2(4→8) → ReLU → MaxPool2 → FC(→6)。"""

    def __init__(self, rng):
        self.w1 = rng.normal(0, np.sqrt(2.0 / (1 * K * K)), (4, 1, K, K))
        self.b1 = np.zeros(4)
        self.w2 = rng.normal(0, np.sqrt(2.0 / (4 * K * K)), (8, 4, K, K))
        self.b2 = np.zeros(8)
        self.w3 = rng.normal(0, np.sqrt(2.0 / (8 * 16 * 16)), (6, 8 * 16 * 16))
        self.b3 = np.zeros(6)

    def params(self):
        return [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]

    def forward(self, x, cache=False):
        y1, cols1 = conv_forward(x, self.w1, self.b1)
        r1 = np.maximum(y1, 0)
        y2, cols2 = conv_forward(r1, self.w2, self.b2)
        r2 = np.maximum(y2, 0)
        p, pidx = pool2_forward(r2)
        f = p.reshape(p.shape[0], -1)
        logits = f @ self.w3.T + self.b3
        if cache:
            self.c = dict(x=x, cols1=cols1, y1=y1, r1=r1, cols2=cols2,
                          y2=y2, r2=r2, p=p, pidx=pidx, f=f)
        return logits

    def backward(self, dlogits):
        c = self.c
        n = dlogits.shape[0]
        dW3 = dlogits.T @ c["f"] / n
        db3 = dlogits.sum(axis=0) / n
        dp = (dlogits @ self.w3).reshape(c["p"].shape)
        dr2 = pool2_backward(dp, c["r2"].shape, c["pidx"])
        dy2 = dr2 * (c["y2"] > 0)
        dr1, dW2, db2 = conv_backward(dy2, c["cols2"], c["r1"].shape, self.w2)
        dy1 = dr1 * (c["y1"] > 0)
        _, dW1, db1 = conv_backward(dy1, c["cols1"], c["x"].shape, self.w1)
        return [dW1, db1, dW2, db2, dW3, db3]


def softmax_ce(logits, y):
    z = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(z)
    p = e / e.sum(axis=1, keepdims=True)
    n = len(y)
    loss = -np.log(p[np.arange(n), y] + 1e-12).mean()
    d = p.copy()
    d[np.arange(n), y] -= 1.0
    return loss, d / n


def accuracy(logits, y):
    return float((logits.argmax(axis=1) == y).mean())


# ===========================================================================
# 3. 量化
# ===========================================================================

def calibrate_scale(a, n=127, lo=0.0):
    """对称 per-tensor scale = max|a| / 127；加极小下限防全零。"""
    m = float(np.abs(a).max())
    if m < 1e-8:
        m = 1e-8
    return m / n


def main():
    ap = argparse.ArgumentParser(description="训练 + 量化 + 整数评估")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--out-tag", default="v1")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 94)
    print("NEU-CLS 六分类：训练 → 量化 → 整数评估（纯 numpy）")
    print("=" * 94)
    print(f"  架构 : HConv1 1→4(K3S1P1) → ReLU → HConv2 4→8(K3S1P1) → ReLU"
          f" → MaxPool2 → FC(2048→6) → argmax")

    data, scale, sp = load_split()
    print(f"  scale: {scale:.12f}（A 冻结，来自 train）")
    print(f"  样本 : train {len(data['train'][1])} / val "
          f"{len(data['val'][1])} / test {len(data['test'][1])}")

    # ★ 用**量化后**的输入训练（反量化回浮点），让训练分布与推理一致
    Xtr = to_q(data["train"][0], scale).astype(np.float64) * scale
    ytr = data["train"][1]
    Xva = to_q(data["val"][0], scale).astype(np.float64) * scale
    yva = data["val"][1]
    Xte = to_q(data["test"][0], scale).astype(np.float64) * scale
    yte = data["test"][1]
    Xtr = Xtr[:, None, :, :]
    Xva = Xva[:, None, :, :]
    Xte = Xte[:, None, :, :]

    rng = np.random.default_rng(args.seed)
    net = Net(rng)
    ms = [np.zeros_like(p) for p in net.params()]
    vs = [np.zeros_like(p) for p in net.params()]
    b1, b2, eps = 0.9, 0.999, 1e-8
    step = 0

    print()
    print(f"  开始训练（{args.epochs} epoch，batch {args.batch}，lr {args.lr}，"
          f"seed {args.seed}）")
    print(f"    {'ep':>3}{'loss':>9}{'train acc':>11}{'val acc':>9}")
    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        idx = rng.permutation(len(ytr))
        tot = 0.0
        for i in range(0, len(idx), args.batch):
            sel = idx[i:i + args.batch]
            logits = net.forward(Xtr[sel], cache=True)
            loss, dl = softmax_ce(logits, ytr[sel])
            grads = net.backward(dl)
            tot += loss * len(sel)
            step += 1
            for j, (p, g) in enumerate(zip(net.params(), grads)):
                ms[j] = b1 * ms[j] + (1 - b1) * g
                vs[j] = b2 * vs[j] + (1 - b2) * g * g
                mh = ms[j] / (1 - b1 ** step)
                vh = vs[j] / (1 - b2 ** step)
                p -= args.lr * mh / (np.sqrt(vh) + eps)
        if ep % max(1, args.epochs // 10) == 0 or ep == 1:
            tr = accuracy(net.forward(Xtr), ytr)
            va = accuracy(net.forward(Xva), yva)
            print(f"    {ep:>3}{tot/len(ytr):>9.4f}{tr:>11.4f}{va:>9.4f}")
    print(f"  训练用时 {time.time()-t0:.1f}s")

    float_test = accuracy(net.forward(Xte), yte)
    print(f"\n  浮点（对照，不作为最终成绩）: test acc = {float_test:.4f}")

    # ---------------- 量化 ----------------
    print()
    print("-" * 94)
    print("【量化】per-channel 权重 scale + per-tensor 激活 scale，A 的方案 B")
    print("-" * 94)

    # 用 train 的量化输入跑一遍浮点前向，拿中间激活做校准
    z1 = net.forward(Xtr, cache=True)
    a1 = np.maximum(net.c["y1"], 0)
    a2 = np.maximum(net.c["y2"], 0)
    s_in_1 = scale
    s_out_1 = calibrate_scale(a1)          # = s_in_2（层间直接交接，无需 PS 重定标）
    s_in_2 = s_out_1
    s_out_2 = calibrate_scale(a2)
    print(f"  s_in_1  = {s_in_1:.10f}   (冻结)")
    print(f"  s_out_1 = s_in_2 = {s_out_1:.10f}")
    print(f"  s_out_2 = {s_out_2:.10f}")

    # prepare_int8_layer 返回 (q_w, params) —— 注意是元组
    q_w1_lib, p1 = prepare_int8_layer(net.w1, net.b1, s_in_1, s_out_1, K, 1,
                                      PAD, 1, 4, name="conv1",
                                      activation="none", zero_point=0)
    q_w2_lib, p2 = prepare_int8_layer(net.w2, net.b2, s_in_2, s_out_2, K, 1,
                                      PAD, 4, 8, name="conv2",
                                      activation="none", zero_point=0)
    print(f"  conv1: 权重scale {p1.s_w.round(6).tolist()}")
    print(f"         shift {p1.shift.tolist()}  M {p1.M.tolist()}")
    print(f"  conv2: 权重scale {p2.s_w.round(6).tolist()}")
    print(f"         shift {p2.shift.tolist()}  M {p2.M.tolist()}")

    # 独立取整（按 s_w per-channel、±127 对称），与库返回的 q_w 交叉核对
    q_w1 = np.clip(np.rint(net.w1 / p1.s_w[:, None, None, None]), -127, 127
                   ).astype(np.int8)
    q_w2 = np.clip(np.rint(net.w2 / p2.s_w[:, None, None, None]), -127, 127
                   ).astype(np.int8)
    m1 = np.array_equal(q_w1, np.asarray(q_w1_lib, dtype=np.int8))
    m2 = np.array_equal(q_w2, np.asarray(q_w2_lib, dtype=np.int8))
    print(f"  交叉核对：我算的 q_w 与 prepare_int8_layer 返回 "
          f"{'一致 ✔' if (m1 and m2) else '不一致 ✘'}"
          f"  (conv1 {m1}, conv2 {m2})")
    if not (m1 and m2):
        print("    ⚠ 不一致说明两边的取整/裁剪口径不同 —— 以库为准，并排查原因")
        q_w1 = np.asarray(q_w1_lib, dtype=np.int8)
        q_w2 = np.asarray(q_w2_lib, dtype=np.int8)

    # FC：per-tensor 权重 scale，使 6 个类的输出共享同一尺度 → argmax 可直接比
    s_fc = calibrate_scale(net.w3)
    q_w3 = np.clip(np.rint(net.w3 / s_fc), -127, 127).astype(np.int8)
    # 输出 scale 只用来说明 logit 的物理含义；argmax 不需要它
    s_logit = s_fc * s_out_2

    print(f"  fc   : per-tensor 权重 scale = {s_fc:.10f}（6 类共享 → argmax 可直接比）")

    # ---------------- 整数推理 ----------------
    print()
    print("-" * 94)
    print("【整数推理】只用 INT8 权重 + INT32 累加 + 定点乘子（这才是要报的成绩）")
    print("-" * 94)

    def int_infer(u8_batch):
        q0 = to_q(u8_batch, s_in_1)[:, None, :, :]
        # ★ conv2d_int8 返回 (requant 后的 int8 输出, INT32 累加器) —— 顺序别写反
        q1, _acc1 = conv2d_int8(q0, q_w1, p1, fuse_activation=False,
                                return_accumulator=True)
        r1 = np.maximum(q1, 0)                               # PS: 整数 ReLU
        q2, _acc2 = conv2d_int8(r1, q_w2, p2, fuse_activation=False,
                                return_accumulator=True)
        r2 = np.maximum(q2, 0)                               # PS: 整数 ReLU
        # PS: 整数 2×2 maxpool（max 保序，无需重定标）
        N, C, H, W = r2.shape
        p = r2.reshape(N, C, H // 2, 2, W // 2, 2).max(axis=(3, 5))
        f = p.reshape(N, -1).astype(np.int64)
        # PS: 整数 FC（INT32 累加 + 整数 bias），bias 按 s_fc*s_out_2 折算
        b3_int = np.rint(net.b3 / s_logit).astype(np.int64)
        logits = f @ q_w3.T.astype(np.int64) + b3_int
        return logits, q1, q2

    def eval_int(u8_batch, y, name):
        lg, _, _ = int_infer(u8_batch)
        pred = lg.argmax(axis=1)
        acc = float((pred == y).mean())
        cm = np.zeros((6, 6), dtype=int)
        for t, p_ in zip(y, pred):
            cm[t, p_] += 1
        rec = [cm[i, i] / max(1, cm[i].sum()) for i in range(6)]
        print(f"\n  {name}: accuracy = {acc:.4f}  ({int((pred==y).sum())}/{len(y)})")
        print(f"    {'类':<4}{'名称':<17}{'样本':>5}{'召回':>8}")
        for i, c in enumerate(CLASS_ORDER):
            print(f"    {c:<4}{CLASS_NAME[c]:<17}{cm[i].sum():>5}{rec[i]:>8.4f}")
        print(f"    宏平均召回 = {np.mean(rec):.4f}")
        return acc, cm, rec, pred, lg

    acc_te, cm_te, rec_te, pred_te, lg_te = eval_int(data["test"][0], yte, "test")
    acc_va, cm_va, rec_va, pred_va, _ = eval_int(data["val"][0], yva, "val")

    print()
    print(f"  混淆矩阵（行=真值，列=预测，顺序 {CLASS_ORDER}）：")
    print("           " + "".join(f"{c:>6}" for c in CLASS_ORDER))
    for i, c in enumerate(CLASS_ORDER):
        print(f"    {c:<6}" + "".join(f"{v:>6}" for v in cm_te[i]))

    print()
    print(f"  ★ 浮点 {float_test:.4f} → 整数 {acc_te:.4f}"
          f"  (差 {(float_test-acc_te)*100:+.2f} 个百分点)")

    # ---------------- 保存 ----------------
    tag = args.out_tag
    npz = os.path.join(OUT_DIR, f"model_{tag}.npz")
    np.savez_compressed(
        npz,
        q_w1=q_w1, q_w2=q_w2, q_w3=q_w3,
        bias_int_1=p1.bias_int.astype(np.int32),
        bias_int_2=p2.bias_int.astype(np.int32),
        b3_int=np.rint(net.b3 / s_logit).astype(np.int32),
        M1=p1.M.astype(np.int32), shift1=p1.shift.astype(np.int32),
        M2=p2.M.astype(np.int32), shift2=p2.shift.astype(np.int32),
        w1=net.w1, b1=net.b1, w2=net.w2, b2=net.b2, w3=net.w3, b3=net.b3)
    h_npz = hashlib.sha256(open(npz, "rb").read()).hexdigest()

    contract = {
        "version": f"NEU_CLS_MODEL_V1_{tag}",
        "preprocess_version": "NEU_CLS_PREPROCESS_V1",
        "split": "split_v1",
        "architecture": [
            {"op": "hconv", "name": "conv1", "shape": [1, 1, 4, 32, 32, 1, 0],
             "K": 3, "stride": 1, "pad": 1,
             "s_in": s_in_1, "s_out": s_out_1, "output_zero_point": 0,
             "weight_scale_per_channel": p1.s_w.tolist(),
             "M": p1.M.astype(int).tolist(),
             "shift": p1.shift.astype(int).tolist(),
             "bias_int": p1.bias_int.astype(int).tolist()},
            {"op": "ps_relu", "input_zero_point": 0, "rule": "max(q,0)"},
            {"op": "hconv", "name": "conv2", "shape": [1, 4, 8, 32, 32, 1, 0],
             "K": 3, "stride": 1, "pad": 1,
             "s_in": s_in_2, "s_out": s_out_2, "output_zero_point": 0,
             "weight_scale_per_channel": p2.s_w.tolist(),
             "M": p2.M.astype(int).tolist(),
             "shift": p2.shift.astype(int).tolist(),
             "bias_int": p2.bias_int.astype(int).tolist()},
            {"op": "ps_relu", "input_zero_point": 0, "rule": "max(q,0)"},
            {"op": "ps_maxpool2x2", "rule": "max 保序，不重定标",
             "out_shape": [1, 8, 16, 16]},
            {"op": "ps_fc", "shape": [2048, 6], "weight_scale": s_fc,
             "output_scale": s_logit, "accumulate": "int32",
             "bias_int": np.rint(net.b3 / s_logit).astype(int).tolist(),
             "rounding": "输出不 requant，直接 argmax（6 类共享同一 scale）"},
            {"op": "ps_argmax"},
        ],
        "integer_contract": {
            "input_zero_point": 0, "weight_zero_points": 0,
            "padding_value": 0, "accumulate": "int32 wrap (two's complement)",
            "requant": "round_to_nearest_ties_to_even, then clip to int8",
            "output_zero_point": 0,
            "ps_rules": "全部整数运算，无浮点；位宽与舍入如上",
        },
        "training": {"epochs": args.epochs, "batch": args.batch,
                     "lr": args.lr, "seed": args.seed, "optimizer": "Adam",
                     "backend": "pure numpy (no framework)"},
        "metrics": {
            "float_test_accuracy": round(float_test, 6),
            "integer_test_accuracy": round(acc_te, 6),
            "integer_val_accuracy": round(acc_va, 6),
            "per_class_recall_test": {c: round(r, 6)
                                      for c, r in zip(CLASS_ORDER, rec_te)},
            "macro_recall_test": round(float(np.mean(rec_te)), 6),
            "confusion_matrix_test": cm_te.tolist(),
            "class_order": CLASS_ORDER,
        },
        "artifacts": {"model_npz": os.path.basename(npz),
                      "model_npz_sha256": h_npz,
                      "input_calibration_sha256": hashlib.sha256(
                          open(os.path.join(OUT_DIR, "input_calibration_v1.json"),
                               "rb").read()).hexdigest()},
    }
    cp = os.path.join(OUT_DIR, f"model_contract_{tag}.json")
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
    h_cp = hashlib.sha256(open(cp, "rb").read()).hexdigest()

    print()
    print("=" * 94)
    print("✔ 已保存")
    print(f"  模型     : {npz}")
    print(f"             SHA-256 {h_npz}")
    print(f"  合同     : {cp}")
    print(f"             SHA-256 {h_cp}")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
