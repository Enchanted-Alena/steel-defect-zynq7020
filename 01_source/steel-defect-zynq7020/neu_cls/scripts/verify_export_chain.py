r"""
verify_export_chain.py —— 只用 JSON 独立复算**整条模型链**
================================================================================

--------------------------------------------------------------------------------
为什么要再写一个（rev2 的教训）
--------------------------------------------------------------------------------
rev2 里我写了 `verify_export.py`，它复算了每个卷积层的 accum/golden，
**全部 0 不符** —— 但我没发现 conv2 的输入没有过 ReLU。

原因：那个校验器只检查"**层内**我的参数算出来的对不对"，
它默认"**层间**接线是对的"。而错恰恰在层间。

> 校验器检查什么、就只保护什么。层内核对通过，不代表链路正确。
> 所以这一版**把 PS 段和层间接线也纳入复算**，并且强制检查
> `conv2.inputs == max(conv1.golden, 0)`。

--------------------------------------------------------------------------------
复算的完整链路（只读 JSON，不 import 导出器）
--------------------------------------------------------------------------------
    q1, acc1 = conv(inputs1, W1, b1, M1, s1)      ← 与 JSON 的 accum1/golden1 比
    r1       = max(q1, 0)                          ← 必须 == conv2.inputs
    q2, acc2 = conv(r1, W2, b2, M2, s2)            ← 与 JSON 的 accum2/golden2 比
    r2       = max(q2, 0)
    pool     = 2x2 max over r2                     ← 与 ps_chain 的 golden 比
    flat     = C-major 展平
    logits   = flat @ W3.T + b3                    ← 与 ps_chain 的 logits 比
    pred     = argmax(logits)                      ← 与 ps_chain 的 prediction 比

用法
--------------------------------------------------------------------------------
    python verify_export_chain.py
"""

import argparse
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))
OUT = os.path.join(_DATA, "model_export_v2")


def wrap_i32(x):
    x = np.asarray(x, dtype=np.int64) & 0xFFFFFFFF
    return np.where(x >= 2**31, x - 2**32, x).astype(np.int64)


def round_shift_even(x, s):
    x = np.asarray(x, dtype=np.int64)
    s = np.asarray(s, dtype=np.int64)
    out = np.zeros_like(x)
    for u in np.unique(s):
        m = (s == u)
        if u == 0:
            out[m] = x[m]
            continue
        q = x[m] >> u
        r = x[m] & ((1 << int(u)) - 1)
        half = 1 << (int(u) - 1)
        out[m] = q + ((r > half) | ((r == half) & ((q & 1) == 1)))
    return out


def conv_corr(x, w, N, Cin, Cout, H, W, pad, K=3):
    xp = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)), mode="constant")
    Ho, Wo = H + 2 * pad - K + 1, W + 2 * pad - K + 1
    acc = np.zeros((N, Cout, Ho, Wo), dtype=np.int64)
    for oc in range(Cout):
        for ic in range(Cin):
            for ky in range(K):
                for kx in range(K):
                    acc[:, oc] += (xp[:, ic, ky:ky + Ho, kx:kx + Wo]
                                   .astype(np.int64) * int(w[oc, ic, ky, kx]))
    return acc


def main():
    ap = argparse.ArgumentParser(description="独立复算整条模型链")
    ap.add_argument("--dir", default=OUT)
    args = ap.parse_args()

    print("=" * 94)
    print("整链独立复算（只读 JSON，不 import 导出器）")
    print("=" * 94)
    D = args.dir
    man = json.load(open(os.path.join(D, "export_manifest_v2.json"),
                         encoding="utf-8"))
    ps = json.load(open(os.path.join(D, "ps_chain.json"), encoding="utf-8"))
    st = {s["stage"]: s for s in ps["stages"]}
    print(f"  目录 : {D}")
    print(f"  样本 : {man['sample']['file']}  split={man['sample']['split']}"
          f"  label={man['sample']['label']}")
    print()

    problems = []

    def chk(cond, msg):
        print(f"  [{'✔' if cond else '✘'}] {msg}")
        if not cond:
            problems.append(msg)

    # ---- conv1 ----
    c1 = json.load(open(os.path.join(D, "conv1.json"), encoding="utf-8"))
    N, Cin, Cout, H, W, pad, ozp = c1["shape"]
    x1 = np.asarray(c1["inputs"], dtype=np.int64).reshape(N, Cin, H, W)
    w1 = np.asarray(c1["weights"], dtype=np.int64).reshape(Cout, Cin, 3, 3)
    acc1 = wrap_i32(conv_corr(x1, w1, N, Cin, Cout, H, W, pad)
                    + np.asarray(c1["bias"], dtype=np.int64)
                    .reshape(1, Cout, 1, 1))
    chk(np.array_equal(acc1.reshape(-1),
                       np.asarray(c1["accum"], dtype=np.int64)),
        f"conv1.accum 复算一致（{acc1.size} 元素）")
    y1 = acc1 * np.asarray(c1["mult"], dtype=np.int64).reshape(1, Cout, 1, 1)
    q1 = np.clip(round_shift_even(
        y1, np.broadcast_to(np.asarray(c1["shifts"], dtype=np.int64)
                            .reshape(1, Cout, 1, 1), y1.shape)) + ozp,
        -128, 127).reshape(-1)
    chk(np.array_equal(q1, np.asarray(c1["golden"], dtype=np.int64)),
        f"conv1.golden 复算一致（{q1.size} 元素）")

    r1 = np.maximum(q1, 0)
    st_r1 = st["conv1_ps_relu"]
    chk(int((q1 < 0).sum()) == st_r1["negative_in_input"],
        f"conv1_ps_relu 夹掉的负值数 = {st_r1['negative_in_input']}")

    # ---- ★ 层间接线：必须过 ReLU ----
    c2 = json.load(open(os.path.join(D, "conv2.json"), encoding="utf-8"))
    in2 = np.asarray(c2["inputs"], dtype=np.int64)
    chk(np.array_equal(in2, r1),
        "★ conv2.inputs == max(conv1.golden, 0)（链路含 PS ReLU）")
    chk(not np.array_equal(in2, q1),
        "  conv2.inputs ≠ 原始 conv1.golden（rev2 的错，本版已不成立）")

    # ---- conv2 ----
    N2, Cin2, Cout2, H2, W2, pad2, ozp2 = c2["shape"]
    x2 = in2.reshape(N2, Cin2, H2, W2)
    w2 = np.asarray(c2["weights"], dtype=np.int64).reshape(Cout2, Cin2, 3, 3)
    acc2 = wrap_i32(conv_corr(x2, w2, N2, Cin2, Cout2, H2, W2, pad2)
                    + np.asarray(c2["bias"], dtype=np.int64)
                    .reshape(1, Cout2, 1, 1))
    chk(np.array_equal(acc2.reshape(-1),
                       np.asarray(c2["accum"], dtype=np.int64)),
        f"conv2.accum 复算一致（{acc2.size} 元素）")
    y2 = acc2 * np.asarray(c2["mult"], dtype=np.int64).reshape(1, Cout2, 1, 1)
    q2 = np.clip(round_shift_even(
        y2, np.broadcast_to(np.asarray(c2["shifts"], dtype=np.int64)
                            .reshape(1, Cout2, 1, 1), y2.shape)) + ozp2,
        -128, 127).reshape(-1)
    chk(np.array_equal(q2, np.asarray(c2["golden"], dtype=np.int64)),
        f"conv2.golden 复算一致（{q2.size} 元素）")

    r2 = np.maximum(q2, 0)
    chk(int((q2 < 0).sum()) == st["conv2_ps_relu"]["negative_in_input"],
        f"conv2_ps_relu 夹掉的负值数 = {st['conv2_ps_relu']['negative_in_input']}")

    # ---- Pool ----
    arr = r2.reshape(N2, Cout2, H2 + 2 * pad2 - 2, W2 + 2 * pad2 - 2)
    pool = arr.reshape(arr.shape[0], arr.shape[1], arr.shape[2] // 2, 2,
                       arr.shape[3] // 2, 2).max(axis=(3, 5))
    import hashlib
    chk(hashlib.sha256(pool.astype(np.int8).tobytes()).hexdigest()
        == st["ps_maxpool"]["golden_sha256"],
        f"ps_maxpool golden 一致  {pool.shape}")

    # ---- Flatten C-major ----
    flat = pool.reshape(1, -1).astype(np.int64)
    chk(hashlib.sha256(flat.astype(np.int32).tobytes()).hexdigest()
        == st["ps_flatten"]["golden_sha256"],
        f"ps_flatten golden 一致（C-major，长度 {flat.size}）")

    # ---- FC ----
    # 权重从 model_v1.npz 取（ps_chain 只存 logits 与 bias）
    npz_p = os.path.join(_DATA, "model", "model_v1.npz")
    q_w3 = np.load(npz_p)["q_w3"].astype(np.int64)
    b3 = np.asarray(st["ps_fc"]["bias_int"], dtype=np.int64)
    logits = flat @ q_w3.T + b3
    chk(np.array_equal(logits.reshape(-1).astype(np.int64),
                       np.asarray(st["ps_fc"]["logits"], dtype=np.int64)),
        f"ps_fc logits 复算一致  {logits.reshape(-1).tolist()}")

    # ---- Argmax ----
    pred = int(np.argmax(logits.reshape(-1)))
    chk(pred == st["ps_argmax"]["prediction"],
        f"ps_argmax prediction = {pred}")
    chk(pred == ps["sample"]["label"],
        f"prediction 与 label 一致（{pred} vs {ps['sample']['label']}）")

    print()
    print("=" * 94)
    if problems:
        print(f"✘ {len(problems)} 项不通过")
        return 1
    print("✔ 整条链复算全部通过 —— 层内、层间（含 PS ReLU）、Pool、Flatten、")
    print("  FC logits、argmax 每一步都能只凭 JSON/参数复现。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
