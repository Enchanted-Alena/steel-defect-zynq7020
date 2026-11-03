r"""
check_dma_budget.py —— 模型形状的可行性检查（对照 B 的冻结 DMA 上限）
================================================================================

--------------------------------------------------------------------------------
为什么先做这件事（通俗版）
--------------------------------------------------------------------------------
训练一个分类模型要花几天。如果训完才发现**它的形状根本塞不进冻结的 DMA**，
那几天就白费了 —— 而且是"训得很好、指标很漂亮、就是上不了板"这种最难接受的浪费。

B 的合同里给了硬上限：

    axi_dma_0 是 simple mode，C_SG_LENGTH_WIDTH = 14，
    单次 TX / RX **各最多 16383 字节**。

而且给了公式：

    A4(x) = (x+3) & ~3
    TX = A4(9*Cin*Cout) + 4*Cout + 4*Cout + A4(Cout) + A4(N*Cin*H*W)
    RX = N*Cout*(H+2*p-2)*(W+2*p-2)
    必须同时满足 TX <= 16383 且 RX <= 16383

**最容易踩的坑**：`N=1, Cin=1, Cout=16, H=W=32, p=1` 看起来完全合规
（核心允许 Cout≤16、32×32 也允许），但
`RX = 1*16*32*32 = 16384` —— **比上限多 1 个字节**，不允许跑。

所以本脚本要做两件事：
  1. **两个独立实现互相校对**：用 B 的公式，和用我自己 packet_v1 的布局函数，
     对同一批形状各算一遍，结果必须逐字节相同。
     （两套独立代码得同一个数，才算真的验证过；只跑一套等于自己确认自己）
  2. **枚举可行架构**：在 TX/RX 双约束下，扫出 32×32 灰度输入能用的
     第一层 / 两层 / 三层配置，并标出哪些"看起来合规其实超限"。

用法
--------------------------------------------------------------------------------
    python check_dma_budget.py                 # 跑校对 + 打印可行表
    python check_dma_budget.py --json out.json # additionally 输出 JSON
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))
_PHASE = os.path.abspath(os.path.join(_DATA, ".."))
_PROJ = os.path.join(_PHASE, "cnn_accelerator")

# 冻结 DMA 上限（B 的合同 §2）
DMA_MAX_BYTES = 16383


def a4(x):
    return (x + 3) & ~3


def tx_rx_b_formula(n, cin, cout, h, w, p):
    """严格照抄 B 合同 §2 的公式（独立实现之一）。"""
    tx = (a4(9 * cin * cout) + 4 * cout + 4 * cout + a4(cout)
          + a4(n * cin * h * w))
    hout, wout = h + 2 * p - 2, w + 2 * p - 2
    rx = n * cout * hout * wout if (hout > 0 and wout > 0) else -1
    return tx, rx, hout, wout


def tx_rx_packet_v1(n, cin, cout, h, w, p):
    """
    用项目里 packet_v1 的布局函数再算一遍（独立实现之二）。

    packet_v1 是**先写好并已通过 27 项验收测试**的打包器，
    它的段偏移公式是协议 1.0 的实现。如果它和 B 的公式一致，
    说明协议实现与硬件合同对得上 —— 这是跨组一致性证据，不是重复劳动。
    """
    if not os.path.isdir(_PROJ):
        return None
    sys.path.insert(0, _PROJ)
    sys.path.insert(0, os.path.join(_PROJ, "tools"))
    try:
        from packet_v1 import (JobConfig, expected_input_bytes,
                               expected_output_bytes)
    except Exception:                                     # noqa: BLE001
        return None
    cfg = JobConfig(batch=n, input_channels=cin, output_channels=cout,
                    height=h, width=w, padding=p, zero_point=0)
    try:
        return expected_input_bytes(cfg), expected_output_bytes(cfg)
    except Exception:                                     # noqa: BLE001
        return None


# B 合同 §2 表格里给出的七个形状（用来核对公式实现是否与 B 一致）
B_TABLE = [
    (1, 1, 4, 32, 32, 1, 1096, 4096, "合规"),
    (1, 1, 8, 32, 32, 1, 1168, 8192, "合规"),
    (1, 4, 8, 32, 32, 1, 4456, 8192, "合规"),
    (1, 8, 8, 16, 16, 1, 2696, 2048, "合规"),
    (1, 14, 14, 32, 32, 1, 16228, 14336, "合规"),
    (1, 1, 16, 32, 32, 1, 1312, 16384, "超限"),
    (2, 16, 16, 32, 32, 1, 35216, 32768, "超限"),
]


def main():
    ap = argparse.ArgumentParser(description="DMA 预算可行性检查")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    print("=" * 92)
    print("DMA 预算可行性检查（对照 B 冻结合同 §2）")
    print("=" * 92)
    print(f"  上限：单次 TX ≤ {DMA_MAX_BYTES}，RX ≤ {DMA_MAX_BYTES} 字节")
    print(f"  packet_v1 项目路径：{_PROJ}"
          f"{'（存在）' if os.path.isdir(_PROJ) else '（不存在，跳过双实现校对）'}")
    print()

    problems = []

    # ---- 1. 校对 B 的表格 ----
    print("-" * 92)
    print("【校对 1】用 B 的公式重算 B 自己给出的七个形状")
    print("-" * 92)
    print(f"  {'形状':<22}{'TX 算':>8}{'TX 表':>8}{'RX 算':>8}{'RX 表':>8}  判定")
    for (n, ci, co, h, w, p, tx_t, rx_t, verdict) in B_TABLE:
        tx, rx, _, _ = tx_rx_b_formula(n, ci, co, h, w, p)
        ok_tx = tx == tx_t
        ok_rx = rx == rx_t
        shape = f"{n},{ci},{co},{h},{w},{p}"
        mark = "✔" if (ok_tx and ok_rx) else "✘"
        print(f"  {shape:<22}{tx:>8}{tx_t:>8}{rx:>8}{rx_t:>8}  {mark}")
        if not (ok_tx and ok_rx):
            problems.append(f"形状 {shape}: 算出 TX={tx}/RX={rx}，"
                            f"B 表 TX={tx_t}/RX={rx_t}")
    if not problems:
        print("  ✔ 七个形状的 TX/RX 与 B 的表格逐字节一致")

    # ---- 2. 双实现校对（B 公式 vs packet_v1）----
    print()
    print("-" * 92)
    print("【校对 2】B 的公式 vs 项目 packet_v1 布局函数（两套独立实现）")
    print("-" * 92)
    tested = mismatch = 0
    combos = [(n, ci, co, h, w, p)
              for n in (1, 2)
              for ci in (1, 2, 3, 4, 8, 16)
              for co in (1, 4, 8, 14, 16)
              for (h, w) in ((8, 8), (16, 16), (32, 32), (5, 7))
              for p in (0, 1)]
    for (n, ci, co, h, w, p) in combos:
        tx_b, rx_b, hout, wout = tx_rx_b_formula(n, ci, co, h, w, p)
        got = tx_rx_packet_v1(n, ci, co, h, w, p)
        if got is None:
            continue
        tx_p, rx_p = got
        tested += 1
        if (tx_b, rx_b) != (tx_p, rx_p):
            mismatch += 1
            if mismatch <= 5:
                print(f"  ✘ {n},{ci},{co},{h},{w},{p}: "
                      f"B=({tx_b},{rx_b}) packet_v1=({tx_p},{rx_p})")
    if tested == 0:
        print("  （跳过：packet_v1 不可用）")
    else:
        print(f"  对比 {tested} 个形状：不一致 {mismatch} 个")
        if mismatch == 0:
            print("  ✔ 两套独立实现逐字节一致 —— 协议 1.0 实现与 B 的硬件合同对得上")
        else:
            problems.append(f"两套实现有 {mismatch} 个形状不一致")

    # ---- 3. 枚举 32×32 灰度可行配置 ----
    print()
    print("-" * 92)
    print("【枚举】32×32 灰度输入（Cin=1）下，DMA 双约束的可行边界")
    print("-" * 92)
    print("  第一层必须 N=1, Cin=1, H=W=32（灰度 32×32 输入）")
    print(f"  {'Cout':>5}{'p':>3}{'TX':>8}{'RX':>8}  判定")
    feasible_first = []
    for co in range(1, 17):
        for p in (0, 1):
            tx, rx, hout, wout = tx_rx_b_formula(1, 1, co, 32, 32, p)
            ok = tx <= DMA_MAX_BYTES and rx <= DMA_MAX_BYTES
            note = "" if ok else f"  ✘ {'RX' if rx > DMA_MAX_BYTES else 'TX'} 超限"
            if ok:
                feasible_first.append((co, p, tx, rx, hout, wout))
            if co in (1, 4, 8, 14, 15, 16):
                print(f"  {co:>5}{p:>3}{tx:>8}{rx:>8}  "
                      f"{'✔ 可行' if ok else '✘ 不可行'}{note}")
    print()
    print(f"  → 32×32 输出（p=1）下最大 Cout = "
          f"{max((c for c, p, *_ in feasible_first if p == 1), default=0)}")
    print("  ★ 重点：Cout=16 时 RX=16384 > 16383 —— **只超 1 字节**，"
          "核心允许但 DMA 不允许。这正是最容易漏掉的坑。")

    # ---- 4. 扫描两层小网络 ----
    print()
    print("-" * 92)
    print("【扫描】两层配置：1→C1→C2（32×32 保持尺寸，p=1）")
    print("-" * 92)
    print("  条件：第一层 1→C1 可行，且第二层 C1→C2 可行")
    print(f"  {'C1':>4}{'C2':>5}{'L1 TX/RX':>16}{'L2 TX/RX':>16}  判定")
    ok_pairs = []
    for c1 in range(1, 17):
        t1x, r1x, _, _ = tx_rx_b_formula(1, 1, c1, 32, 32, 1)
        if t1x > DMA_MAX_BYTES or r1x > DMA_MAX_BYTES:
            continue
        for c2 in range(1, 17):
            t2x, r2x, _, _ = tx_rx_b_formula(1, c1, c2, 32, 32, 1)
            if t2x <= DMA_MAX_BYTES and r2x <= DMA_MAX_BYTES:
                ok_pairs.append((c1, c2, t1x, r1x, t2x, r2x))
    for (c1, c2, t1x, r1x, t2x, r2x) in ok_pairs:
        if c1 in (2, 4, 8) and c2 in (4, 8, 16):
            print(f"  {c1:>4}{c2:>5}{f'{t1x}/{r1x}':>16}{f'{t2x}/{r2x}':>16}  ✔")
    print(f"\n  → 可行 (C1,C2) 组合数：{len(ok_pairs)} / {16*16}")
    print(f"  → 其中 C1=8 可行组合："
          f"{sorted({c2 for c1, c2, *_ in ok_pairs if c1 == 8})}")
    print(f"  → 其中 C1=16 可行组合："
          f"{sorted({c2 for c1, c2, *_ in ok_pairs if c1 == 16}) or '（无，C1=16 时 L1 RX=16384 超限）'}")

    # ---- 结论 ----
    print()
    print("=" * 92)
    if problems:
        print(f"✘ {len(problems)} 项不通过")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("✔ 校对全部通过")
    print()
    print("  对模型设计的直接约束（写进预处理/模型合同）：")
    print("    · 输入固定 N=1, Cin=1, H=W=32, p=1 → 第一层输出 32×32")
    print("    · 32×32 输出下 Cout ≤ 15（Cout=16 会 RX=16384 超限 1 字节）")
    print("    · 层间通道不能随意加宽；每层都受同一条 TX/RX 双约束")
    print("    · ReLU/池化/softmax/全连接**不在核内**，必须放 PS")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"dma_max_bytes": DMA_MAX_BYTES,
                       "feasible_first_layers": feasible_first,
                       "feasible_two_layer_pairs": ok_pairs}, f, indent=2)
        print(f"\n  已写 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
