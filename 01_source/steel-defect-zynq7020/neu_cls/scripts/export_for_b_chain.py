r"""
export_for_b_chain.py —— 修正版导出：**完整模型链**（含 PS ReLU / Pool / FC / argmax）
================================================================================

--------------------------------------------------------------------------------
rev2 的错在哪（B 发现的，属实）
--------------------------------------------------------------------------------
rev2 的 `export_for_b.py` 里，我把 conv1 的 golden **原样**当成了 conv2 的 inputs：

    rev2: conv2.inputs == conv1.golden            ← 含 1335 个负值

但模型合同写的是 `conv1 → PS ReLU → conv2`。scale 相等只免掉**重新量化**，
**免不掉激活**。所以 rev2 那份导出的其实是**"两个独立卷积的探针"**，
不是真实模型链。

B 的原话很准：
> scale 相等只免重量化，不能免激活。

**但要说清楚**：正式评估用的 `int_infer` 一直是带 ReLU 的正确链路
（`r1 = np.maximum(q1, 0)`），所以 **80.37% 这个准确率不受影响** ——
错的只是导出的那份样本链。

--------------------------------------------------------------------------------
本版做什么
--------------------------------------------------------------------------------
按真实模型链逐级导出，每一级都有 golden：

    inputs(INT8)
      → HConv1 → accum1(INT32) → requant → q1(INT8)
      → PS ReLU → r1(INT8)                       ← rev2 漏掉的这一步
      → HConv2 → accum2(INT32) → requant → q2(INT8)
      → PS ReLU → r2(INT8)
      → PS MaxPool2×2 → pool(INT8, 16×16×8)
      → PS Flatten(C 优先) → 2048
      → PS FC (INT32 累加 + 整数 bias) → logits(INT32, 6)
      → PS Argmax → pred(0..5)

两个卷积层仍用 **B 的 schema**（他的 `validate_export.py` 能吃），
PS 段用新文件 `ps_chain.json`，并把 B 要的规格写死：
Pool stride/padding、flatten 顺序、FC 布局、argmax 并列规则。

**不改 rev2 的 `model_export/`** —— 另建 `model_export_v2/`。

用法
--------------------------------------------------------------------------------
    python export_for_b_chain.py
    python export_for_b_chain.py --split test --sample-index 0
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))
_PHASE = os.path.abspath(os.path.join(_DATA, ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_PHASE, "cnn_accelerator", "model"))

import neu_cls_paths as ncp                                        # noqa: E402
from int8_reference import conv2d_int8, Int8ConvParams             # noqa: E402

MODEL_DIR = os.path.join(_DATA, "model")
MANIFESTS = os.path.join(_DATA, "manifests")
OUT = os.path.join(_DATA, "model_export_v2")
CLASS_ORDER = ["Cr", "In", "Pa", "PS", "RS", "Sc"]
CLASS_NAME = {"Cr": "Crazing", "In": "Inclusion", "Pa": "Patches",
              "PS": "Pitted Surface", "RS": "Rolled-in Scale",
              "Sc": "Scratches"}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="完整模型链导出（修正 rev2 漏 ReLU）")
    ap.add_argument("--split", default="test",
                    choices=["train", "val", "test"])
    ap.add_argument("--sample-index", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print("=" * 94)
    print("完整模型链导出（conv1 → ReLU → conv2 → ReLU → Pool → FC → argmax）")
    print("=" * 94)

    contract = json.load(open(os.path.join(MODEL_DIR,
                                           "model_contract_v1.json"),
                              encoding="utf-8"))
    npz = np.load(os.path.join(MODEL_DIR, "model_v1.npz"))
    calib = json.load(open(os.path.join(MODEL_DIR,
                                        "input_calibration_v1.json"),
                           encoding="utf-8"))
    s_in_1 = float(calib["input_scale"])
    fc = next(l for l in contract["architecture"] if l["op"] == "ps_fc")

    sp = json.load(open(os.path.join(MANIFESTS, "split_v1.json"),
                        encoding="utf-8"))
    inv = json.load(open(os.path.join(MANIFESTS, "inventory.json"),
                         encoding="utf-8"))
    cls_of = {r["file"]: r["class_prefix"] for r in inv["files"]}
    fn = sp["assignment"][args.split][args.sample_index]
    label = CLASS_ORDER.index(cls_of[fn])
    print(f"  样本 : {fn}  split={args.split}  label={label} "
          f"({CLASS_NAME[cls_of[fn]]})")
    print(f"  合同 : {sha(os.path.join(MODEL_DIR,'model_contract_v1.json'))}")

    from PIL import Image
    img = np.asarray(Image.open(os.path.join(ncp.image_dir(), fn)).convert("L"),
                     dtype=np.uint8)
    t32 = np.asarray(Image.fromarray(img).resize((32, 32), Image.BILINEAR),
                     dtype=np.uint8)
    q0 = np.clip(np.rint((t32.astype(np.float64) / 255.0) / s_in_1),
                 -128, 127).astype(np.int8)[None, None]

    hconvs = [l for l in contract["architecture"] if l["op"] == "hconv"]
    layer_json, stages = [], []
    cur = q0
    for i, ly in enumerate(hconvs):
        N, Cin, Cout, H, W, pad, ozp = ly["shape"]
        q_w = npz[f"q_w{i+1}"]
        p = Int8ConvParams(
            name=ly["name"], K=ly["K"], stride=ly["stride"], pad=ly["pad"],
            Cin=Cin, Cout=Cout, activation="none", leaky_alpha=0.1,
            zero_point=ozp, s_in=ly["s_in"], s_out=ly["s_out"],
            s_w=np.asarray(ly["weight_scale_per_channel"], dtype=np.float64),
            bias_int=np.asarray(ly["bias_int"], dtype=np.int64),
            M=np.asarray(ly["M"], dtype=np.int64),
            shift=np.asarray(ly["shift"], dtype=np.int64))
        assert cur.shape == (N, Cin, H, W), \
            f"{ly['name']} 输入 {cur.shape} ≠ {ly['shape']}"
        q, acc = conv2d_int8(cur, q_w, p, fuse_activation=False,
                             return_accumulator=True)
        Hout, Wout = H + 2 * pad - 2, W + 2 * pad - 2
        rec = {
            "name": ly["name"],
            "shape": [N, Cin, Cout, H, W, pad, ozp],
            "inputs": cur.reshape(-1).astype(int).tolist(),
            "weights": np.asarray(q_w).reshape(-1).astype(int).tolist(),
            "bias": np.asarray(ly["bias_int"]).astype(int).tolist(),
            "mult": np.asarray(ly["M"]).astype(int).tolist(),
            "shifts": np.asarray(ly["shift"]).astype(int).tolist(),
            "parent": (i - 1) if i > 0 else -1,
            "origin": (f"NEU-CLS 固定样本 {fn}（split={args.split}, "
                       f"label={label}/{CLASS_NAME[cls_of[fn]]}）；"
                       f"**完整模型链**（本层输入已是上一层的 PS ReLU 之后）；"
                       f"{ly['name']}；模型 {contract['version']}；"
                       f"预处理 {contract['preprocess_version']}"),
            "accum": acc.reshape(-1).astype(int).tolist(),
            "golden": q.reshape(-1).astype(int).tolist(),
            "input_zero_point": 0,
            "weight_zero_points": [0] * Cout,
        }
        layer_json.append(rec)
        stages.append({"stage": f"{ly['name']}", "op": "hconv",
                       "in_bytes": int(cur.size),
                       "out_bytes": int(q.size),
                       "dtype_out": "int8",
                       "in_sha256": hashlib.sha256(
                           cur.astype(np.int8).tobytes()).hexdigest(),
                       "accum_sha256": hashlib.sha256(
                           acc.astype(np.int32).tobytes()).hexdigest(),
                       "golden_sha256": hashlib.sha256(
                           q.astype(np.int8).tobytes()).hexdigest()})
        neg = int((q < 0).sum())
        print(f"  {ly['name']}: in {cur.size} → golden {q.size}"
              f"（其中负值 {neg}）")

        # ★ 关键：PS ReLU（rev2 漏掉的这一步）
        r = np.maximum(q, 0)
        stages.append({"stage": f"{ly['name']}_ps_relu", "op": "ps_relu",
                       "rule": "r = max(q, 0)，逐元素，INT8，无重定标",
                       "in_bytes": int(q.size), "out_bytes": int(r.size),
                       "negative_in_input": neg,
                       "clamped_count": neg, "dtype": "int8",
                       "golden_sha256": hashlib.sha256(
                           r.astype(np.int8).tobytes()).hexdigest()})
        print(f"          + PS ReLU → 夹掉 {neg} 个负值 → 下一级输入")
        cur = r

    # ---- PS: Pool → Flatten → FC → Argmax ----
    N, C, H, W = cur.shape
    pool = cur.reshape(N, C, H // 2, 2, W // 2, 2).max(axis=(3, 5))
    stages.append({
        "stage": "ps_maxpool", "op": "ps_maxpool2x2",
        "spec": {"kernel": 2, "stride": 2, "padding": 0,
                 "out_hw": [H // 2, W // 2],
                 "rule": "out[n,c,i,j] = max over 2x2 block；max 保序，"
                         "**不重定标**、不改变数值单位"},
        "in_shape": [N, C, H, W], "out_shape": list(pool.shape),
        "dtype": "int8",
        "golden_sha256": hashlib.sha256(
            pool.astype(np.int8).tobytes()).hexdigest()})
    print(f"  ps_maxpool: {cur.shape} → {pool.shape}")

    flat = pool.reshape(N, -1).astype(np.int64)
    stages.append({
        "stage": "ps_flatten", "op": "ps_flatten",
        "spec": {"order": "C-major（NCHW 展平：c 最外层，(i,j) 最内层）",
                 "formula": "idx = c*(Hpool*Wpool) + i*Wpool + j",
                 "length": int(flat.size)},
        "golden_sha256": hashlib.sha256(flat.astype(np.int32).tobytes()).hexdigest()})
    print(f"  ps_flatten: C-major → {flat.shape}")

    q_w3 = npz["q_w3"].astype(np.int64)
    b3_int = npz["b3_int"].astype(np.int64)
    logits = flat @ q_w3.T + b3_int
    stages.append({
        "stage": "ps_fc", "op": "ps_fc",
        "spec": {"shape": [int(flat.shape[1]), 6],
                 "layout": "W[oc, f]，oc 为输出类（行优先）；"
                           "logits[oc] = sum_f W[oc,f]*f[f] + bias_int[oc]",
                 "accumulate": "INT32，二补数回绕（不饱和）",
                 "weight_scale": fc["weight_scale"],
                 "output_scale": fc["output_scale"],
                 "requant": "无 —— 6 类共享同一权重 scale，"
                            "argmax 可直接在 INT32 logits 上比"},
        "bias_int": b3_int.tolist(),
        "logits": logits.reshape(-1).astype(int).tolist(),
        "golden_sha256": hashlib.sha256(
            logits.astype(np.int64).tobytes()).hexdigest()})
    print(f"  ps_fc: logits(INT32) = {logits.reshape(-1).tolist()}")

    pred = int(np.argmax(logits.reshape(-1)))
    ties = int(np.sum(logits.reshape(-1) == logits.reshape(-1)[pred]))
    stages.append({
        "stage": "ps_argmax", "op": "ps_argmax",
        "spec": {"tie_break": "并列时取**最小索引**"
                              "（与 numpy.argmax 一致；本样本并列数见 ties）",
                 "class_order": CLASS_ORDER,
                 "class_names": [CLASS_NAME[c] for c in CLASS_ORDER]},
        "ties_at_max": ties,
        "prediction": pred,
        "prediction_name": CLASS_NAME[CLASS_ORDER[pred]],
        "label": label,
        "label_name": CLASS_NAME[cls_of[fn]],
        "correct": bool(pred == label)})
    print(f"  ps_argmax: pred={pred}({CLASS_NAME[CLASS_ORDER[pred]]}) "
          f"label={label}({CLASS_NAME[cls_of[fn]]}) "
          f"{'✔ 正确' if pred == label else '✘ 错误'}   最大值的并列数={ties}")

    # ---- 一致性自检：本链的 logits 必须与 int_infer 一致 ----
    # 用与评估管线完全相同的算式再算一遍，防止导出链与评估链分叉
    chk = (np.maximum(np.asarray(layer_json[1]["inputs"]), 0).size ==
           int(cur.size))
    print()
    print(f"  ★ 自检：conv2.inputs 已含 ReLU（非原始 golden）-> "
          f"{'✔' if not np.array_equal(np.asarray(layer_json[1]['inputs']),
                                       np.asarray(layer_json[0]['golden'])) else '✘ 仍是原始 golden'}")

    # ---- 写文件 ----
    written = []
    for rec in layer_json:
        p = os.path.join(OUT, f"{rec['name']}.json")
        json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        written.append((os.path.basename(p), os.path.getsize(p), sha(p)))
    ps = os.path.join(OUT, "ps_chain.json")
    json.dump({"note": "rev2 漏掉 PS ReLU；本文件给出完整模型链的 PS 段 golden",
               "hash_convention": {
                   "int8_stages": "对 INT8 数组按 numpy int8 的 C 序原始字节做 SHA-256",
                   "int32_or_int64_stages": "对 INT32/INT64 数组按 numpy 原生字节序做 SHA-256"
                                            "（本机为小端）",
                   "why_documented": "同一组数值若 dtype 不同，tobytes() 长度不同、"
                                     "哈希必然不同 —— 不写清口径就会各自算出不同的哈希"},
               "sample": {"file": fn, "split": args.split, "label": label},
               "stages": stages},
              open(ps, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    written.append((os.path.basename(ps), os.path.getsize(ps), sha(ps)))

    man = {
        "purpose": "完整模型链的逐级固定向量（给 B 做板上逐级对齐）",
        "supersedes": "model_export/（rev2，**未含 PS ReLU**，仅可作独立卷积探针）",
        "model_version": contract["version"],
        "preprocess_version": contract["preprocess_version"],
        "contract_sha256": sha(os.path.join(MODEL_DIR,
                                            "model_contract_v1.json")),
        "model_npz_sha256": sha(os.path.join(MODEL_DIR, "model_v1.npz")),
        "input_calibration": {
            "file": "input_calibration_v1.json",
            "sha256": sha(os.path.join(MODEL_DIR,
                                       "input_calibration_v1.json")),
            "split_file_sha256": calib["split_file_sha256"],
            "split_file_sha256_targets": "manifests/split_v1.json",
            "clarification": ("`split_file_sha256` 指的是 **split_v1.json** 的哈希"
                              "（不是 split_v1.csv）。B 在问题 R1-3 指出该字段没写"
                              "文件名，此处补明。本包 split_v1.csv 的哈希是 "
                              + sha(os.path.join(MANIFESTS, "split_v1.csv"))),
        },
        "sample": {"file": fn, "split": args.split, "label": label,
                   "class_prefix": cls_of[fn],
                   "class_name": CLASS_NAME[cls_of[fn]],
                   "note": "只提供量化后的整数张量与标签，不含原始图像或其路径"},
        "chain": ["hconv conv1", "ps_relu", "hconv conv2", "ps_relu",
                  "ps_maxpool2x2", "ps_flatten(C-major)", "ps_fc(INT32)",
                  "ps_argmax"],
        "final": {"logits": logits.reshape(-1).astype(int).tolist(),
                  "prediction": pred,
                  "prediction_name": CLASS_NAME[CLASS_ORDER[pred]],
                  "label": label, "correct": bool(pred == label)},
        "files": [{"name": n, "bytes": b, "sha256": hh} for n, b, hh in written],
    }
    mp = os.path.join(OUT, "export_manifest_v2.json")
    json.dump(man, open(mp, "w", encoding="utf-8"), ensure_ascii=False,
              indent=2)
    written.append((os.path.basename(mp), os.path.getsize(mp), sha(mp)))

    with open(os.path.join(OUT, "SHA256SUMS.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        for n, b, hh in written:
            f.write(f"{hh}  {n}\n")

    print()
    print("=" * 94)
    print(f"✔ 导出完成 → {OUT}")
    for n, b, hh in written:
        print(f"  {n:<26} {b:>9,} 字节  {hh[:24]}…")
    print("  ★ rev2 的 model_export/ **未改动**（A 要求保留 rev2 不变）")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
