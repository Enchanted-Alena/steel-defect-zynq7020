r"""
freeze_input_scale.py —— 按 A 冻结的方案 B 计算并冻结输入量化 scale
================================================================================

--------------------------------------------------------------------------------
A 冻结的规则（`C_NEU_CLS_AND_CORRECTION_V3_AUDIT_2026-10-19.md`）
--------------------------------------------------------------------------------
> 双线性缩放后的 uint8 像素 `x = u8/255.0`，**仅用 train split** 求
> `a = max(abs(x))`，全数据固定 `input_scale = a/127.0`，不按样本动态改 scale；
> `q = clip(round_ties_to_even(x/input_scale), -128, 127)`，input zp=0。
> `a` 和具体 scale 由 C 从冻结 train 清单计算后随配置哈希交付，
> **val/test 不参与校准**。

--------------------------------------------------------------------------------
为什么这件事必须"冻结"而不是每张图各算
--------------------------------------------------------------------------------
per-sample 动态 scale 看起来很聪明（每张图都吃满 INT8 范围），但板测时**没法复现**：
FPGA 只收到一串 INT8，它不知道原始像素的最大值。要还原就必须把每张图的 scale
一起搬过去，而协议 1.0 的包里**没有放 scale 的字段**（zero-point 是层间共享标量，
且冻结为 0）。

所以 scale 必须是一个**训练时算好的常数**，写进模型配置、随配置一起哈希。
这样板端和软件端用的是同一个数 —— 这就是"可复现"的全部含义。

--------------------------------------------------------------------------------
一个必须说明的后果（不藏）
--------------------------------------------------------------------------------
像素 x ∈ [0,1] 恒非负，而 `input zp = 0` 是对称量化 →
量化后 `q ∈ [0, 127]`，**只用到 INT8 正半区**，负半区 -128..-1 全部闲置。

这是 A 冻结 `input zp = 0` 的**直接数学后果**，不是 bug。
好处：层间可以直接按 signed INT8 交接，零点为 0 时"重置标"最省事。
代价：有效动态范围减半 —— 本脚本把"实际用到的码值区间"如实报出来，供 A 判断。

用法
--------------------------------------------------------------------------------
    python freeze_input_scale.py
    python freeze_input_scale.py --dry-run
"""

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))            # 8/data/neu_cls
_PHASE = os.path.abspath(os.path.join(_DATA, ".."))     # 8/
MANIFESTS = os.path.join(_DATA, "manifests")
OUT_DIR = os.path.join(_DATA, "model")

import neu_cls_paths as ncp

VERSION = "NEU_CLS_PREPROCESS_V1"


def round_ties_to_even(x):
    """numpy.rint 就是 ties-to-even（银行家舍入），与协议 1.0 的 requant 一致。"""
    return np.rint(x)


def main():
    ap = argparse.ArgumentParser(description="冻结输入量化 scale（A 方案 B）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=" * 92)
    print(f"冻结输入量化 scale —— {VERSION}（A 冻结的方案 B）")
    print("=" * 92)

    sp = json.load(open(os.path.join(MANIFESTS, "split_v1.json"),
                        encoding="utf-8"))
    inv = json.load(open(os.path.join(MANIFESTS, "inventory.json"),
                         encoding="utf-8"))
    cls_of = {r["file"]: r["class_prefix"] for r in inv["files"]}
    train = sp["assignment"]["train"]
    val = sp["assignment"]["val"]
    test = sp["assignment"]["test"]
    print(f"  split     : train {len(train)} / val {len(val)} / test {len(test)}")
    IMAGE_DIR = ncp.image_dir()
    print(f"  图像目录  : {IMAGE_DIR}")
    print()

    from PIL import Image

    def load32(fn):
        a = np.asarray(Image.open(os.path.join(IMAGE_DIR, fn)).convert("L"),
                       dtype=np.uint8)
        return np.asarray(Image.fromarray(a).resize((32, 32), Image.BILINEAR),
                          dtype=np.uint8)

    # ---- 只在 train 上校准 ----
    t0 = time.time()
    amax_u8 = 0
    u8_min_train = 255
    for fn in train:
        t = load32(fn)
        amax_u8 = max(amax_u8, int(t.max()))
        u8_min_train = min(u8_min_train, int(t.min()))
    print(f"  train 上 u8 最大值 = {amax_u8}，最小值 = {u8_min_train}"
          f"   （用时 {time.time()-t0:.1f}s）")

    a = amax_u8 / 255.0
    scale = a / 127.0
    print(f"  a = max(abs(x)) = {amax_u8}/255 = {a:.10f}")
    print(f"  input_scale = a/127 = {scale:.12f}")
    print()

    # ---- 量化函数（严格按 A 的公式）----
    def quant(u8):
        x = u8.astype(np.float64) / 255.0
        q = round_ties_to_even(x / scale)
        return np.clip(q, -128, 127).astype(np.int64)

    # ---- 诊断：三个 split 的量化码值区间与饱和率 ----
    print("  诊断（scale 已冻结在上面，以下只统计、不改 scale）：")
    print(f"    {'split':<7}{'张数':>5}{'q 最小':>8}{'q 最大':>8}"
          f"{'被截断像素':>11}{'等于127的%':>11}{'用到码值数':>11}")
    stats = {}
    for name, files in (("train", train), ("val", val), ("test", test)):
        qmin, qmax, clipped, at_max, total = 127, -128, 0, 0, 0
        used = set()
        for fn in files:
            u8 = load32(fn)
            x = u8.astype(np.float64) / 255.0
            raw = x / scale
            # ★ 精确区分两种"127"：
            #   截断 = raw 超过 127.5（四舍五入后 >127，真的丢了信息）
            #   等于127 = raw 恰好 127（u8=255 的精确表示，不是损失）
            clipped += int(np.sum(raw > 127.5))
            at_max += int(np.sum(raw >= 127.0))
            q = quant(u8)
            qmin = min(qmin, int(q.min()))
            qmax = max(qmax, int(q.max()))
            total += raw.size
            used.update(np.unique(q).tolist())
        stats[name] = {"n_images": len(files), "q_min": qmin, "q_max": qmax,
                       "clipped_pixels": clipped,
                       "clipped_ratio": round(clipped / total, 9),
                       "at_max_127_ratio": round(at_max / total, 6),
                       "distinct_codes": len(used)}
        print(f"    {name:<7}{len(files):>5}{qmin:>8}{qmax:>8}"
              f"{clipped:>11}{at_max/total*100:>10.3f}%{len(used):>11}")

    print()
    tot_clip = sum(v["clipped_pixels"] for v in stats.values())
    print(f"  截断检查：三个 split 合计被截断像素 = {tot_clip}"
          f"  ({'✔ 零截断，scale 精确覆盖 [0,255]' if tot_clip == 0 else '✘ 有截断'})")
    print(f"  ⚠ 码值区间 [{stats['train']['q_min']}, {stats['train']['q_max']}]：")
    print("     像素恒非负 + input zp=0 ⇒ 只用到 INT8 正半区（0..127），")
    print("     负半区 -128..-1 闲置。这是 A 冻结 zp=0 的直接后果，如实记录。")

    # ---- 写冻结产物 ----
    calib = {
        "version": VERSION,
        # ★ 不要写墙上时间！我在阶段 5 刚批评过 A 的 summary.json 里
        #   带 timestamp_utc 导致"什么都不改、重跑也变哈希"。这里用一个
        #   **决策日期常量**：既保留信息，又保证同样输入永远得到同样字节。
        "frozen_on": "2026-10-19",
        "authority": "A 冻结：C_NEU_CLS_AND_CORRECTION_V3_AUDIT_2026-10-19",
        "scheme": "B (fixed per-tensor scale calibrated on train split only)",
        "pipeline": [
            "读 8-bit 灰度 BMP（原图 200x200，未改原件）",
            "PIL Image.BILINEAR 缩放至 32x32（不做纵横比变形：原图本就正方形）",
            "x = u8 / 255.0  → x ∈ [0, 1]",
            f"input_scale = a / 127.0，其中 a = max(abs(x)) 仅在 train 上统计",
            "q = clip(round_ties_to_even(x / input_scale), -128, 127)",
            "input_zero_point = 0（冻结）",
        ],
        "calibration_split": "train",
        "calibration_n_images": len(train),
        "train_u8_max": amax_u8,
        "a_max_abs": a,
        "input_scale": scale,
        "input_zero_point": 0,
        "rounding": "round_to_nearest_ties_to_even",
        "split_file_sha256": hashlib.sha256(
            open(os.path.join(MANIFESTS, "split_v1.json"), "rb").read()
        ).hexdigest(),
        "val_test_used_for_calibration": False,
        "diagnostics": stats,
        "consequence_note": (
            "像素恒非负且 input zp=0，故 q 落在 [0,127]，INT8 负半区闲置；"
            "这是 zp=0 的数学后果，非缺陷。若将来要提升动态范围，须由 A 决定"
            "改 zp 或改用 per-tensor asymmetric，并升预处理版本。"),
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "input_calibration_v1.json")
    if args.dry_run:
        print("\n  DRY-RUN：未写盘")
        print(f"  将写入 {p}")
        return 0
    with open(p, "w", encoding="utf-8") as f:
        json.dump(calib, f, ensure_ascii=False, indent=2)
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    print()
    print(f"  ✔ 已写 {p}")
    print(f"    SHA-256 = {h}")
    print()
    print("  ★ 这个 scale 从此冻结：模型训练、量化、板测都用它，不得改。")
    print("    若需改（例如换 percentile），必须升预处理版本号并重算哈希。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
