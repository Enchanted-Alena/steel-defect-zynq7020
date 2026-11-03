r"""
export_test_set_for_b.py —— 导出全 270 张测试集的冻结派生张量
================================================================================

--------------------------------------------------------------------------------
为什么现在做这个
--------------------------------------------------------------------------------
A 的 `B_NEU_MODEL_REV3_SINGLE_SAMPLE_BOARD_AUDIT_2026-10-20.md` 说：

> Full 270-sample derived vectors remain unnecessary for this first alignment,
> but are **required before claiming board test-set accuracy**.

单样本对齐已经 PASS（我的导出与板上逐值相同）。下一步若要主张"板端测试集准确率"，
就必须有**全部 270 张**的冻结派生输入/标签/golden。

这是纯软件工作、不碰板子、现在就能做完 —— 做完了 A/B 想推进时不必再等。

--------------------------------------------------------------------------------
格式：为什么用二进制 + CSV 索引，而不是 270 个 JSON
--------------------------------------------------------------------------------
单样本的 `conv1.json` 是 44 KB（因为可读的 JSON 数组）。270 份就是 ~12 MB，
而且 99% 的字节是方括号和逗号。

这里改成**紧凑二进制 + 一个 CSV 索引**：

    test_set/inputs_int8.bin          270 × 1024 =   276,480 字节
    test_set/conv1_golden_int8.bin    270 × 4096 = 1,105,920 字节
    test_set/conv2_golden_int8.bin    270 × 8192 = 2,211,840 字节
    test_set/logits_int32.bin         270 ×   6 =     6,480 字节
    test_set/index.csv                逐样本 文件/类/标签/预测/是否正确/FNV

**字节序与 dtype 写死在 README 里** —— 上一轮已经踩过"dtype 不同则哈希不同"的坑，
这次一开始就规定清楚。

--------------------------------------------------------------------------------
纪律
--------------------------------------------------------------------------------
  · 只导出**量化后的整数张量**，不含原始 BMP、不含图像路径
  · 明确标注这 270 张来自 **test split**，且 split 已冻结
  · 每样本给 FNV-1a，方便板端逐样本快速核对（与 B 的既有做法一致）

用法
--------------------------------------------------------------------------------
    python export_test_set_for_b.py
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

MODEL = os.path.join(_DATA, "model")
MAN = os.path.join(_DATA, "manifests")
OUT = os.path.join(_DATA, "test_set_export")
CLASS_ORDER = ["Cr", "In", "Pa", "PS", "RS", "Sc"]
CLASS_NAME = {"Cr": "Crazing", "In": "Inclusion", "Pa": "Patches",
              "PS": "Pitted Surface", "RS": "Rolled-in Scale",
              "Sc": "Scratches"}


def fnv1a(b):
    h = 0x811C9DC5
    for x in b:
        h = ((h ^ int(x)) * 0x01000193) & 0xFFFFFFFF
    return h


def main():
    ap = argparse.ArgumentParser(description="导出全 270 张测试集冻结派生张量")
    ap.add_argument("--split", default="test")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print("=" * 94)
    print(f"导出 {args.split} split 的全部冻结派生张量")
    print("=" * 94)

    contract = json.load(open(os.path.join(MODEL, "model_contract_v1.json"),
                              encoding="utf-8"))
    npz = np.load(os.path.join(MODEL, "model_v1.npz"))
    calib = json.load(open(os.path.join(MODEL, "input_calibration_v1.json"),
                           encoding="utf-8"))
    s_in_1 = float(calib["input_scale"])
    fc = next(l for l in contract["architecture"] if l["op"] == "ps_fc")

    sp = json.load(open(os.path.join(MAN, "split_v1.json"), encoding="utf-8"))
    inv = json.load(open(os.path.join(MAN, "inventory.json"), encoding="utf-8"))
    cls_of = {r["file"]: r["class_prefix"] for r in inv["files"]}
    files = sp["assignment"][args.split]
    print(f"  样本数 : {len(files)}   模型 {contract['version']}")

    hconvs = [l for l in contract["architecture"] if l["op"] == "hconv"]
    ps = []
    for ly in hconvs:
        N, Cin, Cout, H, W, pad, ozp = ly["shape"]
        ps.append(Int8ConvParams(
            name=ly["name"], K=ly["K"], stride=ly["stride"], pad=ly["pad"],
            Cin=Cin, Cout=Cout, activation="none", leaky_alpha=0.1,
            zero_point=ozp, s_in=ly["s_in"], s_out=ly["s_out"],
            s_w=np.asarray(ly["weight_scale_per_channel"], dtype=np.float64),
            bias_int=np.asarray(ly["bias_int"], dtype=np.int64),
            M=np.asarray(ly["M"], dtype=np.int64),
            shift=np.asarray(ly["shift"], dtype=np.int64)))
    q_w1, q_w2 = npz["q_w1"], npz["q_w2"]
    q_w3 = npz["q_w3"].astype(np.int64)
    b3 = npz["b3_int"].astype(np.int64)

    from PIL import Image
    img_dir = ncp.image_dir()
    IN = np.zeros((len(files), 1024), dtype=np.int8)
    G1 = np.zeros((len(files), 4096), dtype=np.int8)
    G2 = np.zeros((len(files), 8192), dtype=np.int8)
    LG = np.zeros((len(files), 6), dtype=np.int32)
    labels = np.zeros(len(files), dtype=np.int32)
    rows = []

    for i, fn in enumerate(files):
        a = np.asarray(Image.open(os.path.join(img_dir, fn)).convert("L"),
                       dtype=np.uint8)
        t = np.asarray(Image.fromarray(a).resize((32, 32), Image.BILINEAR),
                       dtype=np.uint8)
        q0 = np.clip(np.rint((t.astype(np.float64) / 255.0) / s_in_1),
                     -128, 127).astype(np.int8)[None, None]
        q1, _ = conv2d_int8(q0, q_w1, ps[0], fuse_activation=False,
                            return_accumulator=True)
        r1 = np.maximum(q1, 0)
        q2, _ = conv2d_int8(r1, q_w2, ps[1], fuse_activation=False,
                            return_accumulator=True)
        r2 = np.maximum(q2, 0)                       # PS ReLU（rev2 漏掉的这一步）
        p = r2.reshape(1, 8, 16, 2, 16, 2).max(axis=(3, 5))
        logits = p.reshape(1, -1).astype(np.int64) @ q_w3.T + b3
        pred = int(np.argmax(logits.reshape(-1)))
        lab = CLASS_ORDER.index(cls_of[fn])

        IN[i] = q0.reshape(-1)
        G1[i] = q1.reshape(-1)
        G2[i] = q2.reshape(-1)
        LG[i] = logits.reshape(-1).astype(np.int32)
        labels[i] = lab
        rows.append({
            "idx": i, "file": fn, "split": args.split,
            "class_prefix": cls_of[fn], "class_name": CLASS_NAME[cls_of[fn]],
            "label": lab, "pred": pred,
            "correct": int(pred == lab),
            "logits": ";".join(str(int(v)) for v in logits.reshape(-1)),
            "fnv_input": f"0x{fnv1a(q0.tobytes()):08X}",
            "fnv_conv1_golden": f"0x{fnv1a(q1.tobytes()):08X}",
            "fnv_relu1": f"0x{fnv1a(r1.tobytes()):08X}",
            "fnv_conv2_golden": f"0x{fnv1a(q2.tobytes()):08X}",
            "fnv_relu2": f"0x{fnv1a(r2.tobytes()):08X}",
            "fnv_logits_le32": f"0x{fnv1a(logits.astype(np.int32).tobytes()):08X}",
        })
        if (i + 1) % 60 == 0:
            print(f"      … {i+1}/{len(files)}")

    acc = float(np.mean(labels == np.array([r["pred"] for r in rows])))
    print(f"\n  整数 test 准确率 = {acc:.4f}"
          f"（{sum(r['correct'] for r in rows)}/{len(rows)}）")
    print("  → 与已报告的 217/270 = 0.8037 "
          f"{'✔ 一致' if sum(r['correct'] for r in rows) == 217 else '✘ 不一致'}")

    # ---- 写二进制 ----
    written = []
    for name, arr in (("inputs_int8.bin", IN), ("conv1_golden_int8.bin", G1),
                      ("conv2_golden_int8.bin", G2), ("logits_int32.bin", LG)):
        p = os.path.join(OUT, name)
        open(p, "wb").write(arr.tobytes())
        written.append((name, os.path.getsize(p),
                        hashlib.sha256(open(p, "rb").read()).hexdigest()))
        print(f"  ✔ {name:<24} {os.path.getsize(p):>10,} 字节  {arr.dtype}  {arr.shape}")

    lab_p = os.path.join(OUT, "labels_int32.bin")
    open(lab_p, "wb").write(labels.tobytes())
    written.append(("labels_int32.bin", os.path.getsize(lab_p),
                    hashlib.sha256(open(lab_p, "rb").read()).hexdigest()))

    # ---- CSV 索引 ----
    csv_p = os.path.join(OUT, "index.csv")
    cols = list(rows[0].keys())
    with open(csv_p, "w", encoding="utf-8", newline="\n") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]) for c in cols) + "\n")
    written.append(("index.csv", os.path.getsize(csv_p),
                    hashlib.sha256(open(csv_p, "rb").read()).hexdigest()))
    print(f"  ✔ index.csv               {os.path.getsize(csv_p):>10,} 字节")

    # ---- README ----
    readme = f"""# NEU-CLS 全 {len(files)} 张 `{args.split}` 冻结派生张量

生成日期：2026-10-20　　模型：`{contract['version']}`　预处理：`{contract['preprocess_version']}`

## 关键哈希绑定

```
model_contract_v1.json   {hashlib.sha256(open(os.path.join(MODEL,'model_contract_v1.json'),'rb').read()).hexdigest()}
model_v1.npz             {hashlib.sha256(open(os.path.join(MODEL,'model_v1.npz'),'rb').read()).hexdigest()}
input_calibration_v1.json {hashlib.sha256(open(os.path.join(MODEL,'input_calibration_v1.json'),'rb').read()).hexdigest()}
manifests/split_v1.json  {calib['split_file_sha256']}   ← split_file_sha256 指的就是它
```

## 文件与字节布局（**定长记录，无分隔符**）

| 文件 | dtype | 形状 | 每样本字节 | 总字节 |
|---|---|---|---:|---:|
| `inputs_int8.bin` | int8 | [{len(files)},1024] | 1,024 | {len(files)*1024:,} |
| `conv1_golden_int8.bin` | int8 | [{len(files)},4096] | 4,096 | {len(files)*4096:,} |
| `conv2_golden_int8.bin` | int8 | [{len(files)},8192] | 8,192 | {len(files)*8192:,} |
| `logits_int32.bin` | int32 | [{len(files)},6] | 24 | {len(files)*24:,} |
| `labels_int32.bin` | int32 | [{len(files)}] | 4 | {len(files)*4:,} |
| `index.csv` | — | — | — | — |

**读取约定（务必按此，否则会读错位）**
- 第 i 个样本的数据 = `arr[i]`，即字节偏移 `i * 每样本字节`。
- dtype 严格按上表：`int8` 为有符号 8 位，`int32` 为 **小端** 有符号 32 位。
- `inputs` 是量化后的 INT8 输入（`q = clip(round_ties_to_even(x/scale), -128, 127)`，
  `scale = {s_in_1!r}`，`input_zero_point = 0`）。
- `conv1_golden` / `conv2_golden` 是 **requant 之后**的 INT8 卷积输出（conv1 的 zp=0、conv2 的 zp=0）。
- ⚠ **conv2 的输入是 `max(conv1_golden, 0)`**，不是 conv1_golden 原值 —— 中间有 PS ReLU。
- `logits` 是 FC 的 INT32 输出（**不 requant**，6 类共享 scale），argmax 取最小索引。

## 模型链

```
inputs(INT8) → HConv1(1→4) → requant → q1
             → PS ReLU  → max(q1,0)          ← conv2 的实际输入
             → HConv2(4→8) → requant → q2
             → PS ReLU  → max(q2,0)
             → PS MaxPool 2×2 / stride 2 / pad 0  → 16×16×8
             → PS Flatten C-major（idx = c*256 + i*16 + j）
             → PS FC (INT32 回绕 + 整数 bias)  → logits(6)
             → PS Argmax（并列取最小索引）
```

## 逐样本 FNV-1a

`index.csv` 里每行给了 6 个 FNV-1a（`0x%08X`），可直接与板上日志逐样本比对：

| 列 | 覆盖内容 |
|---|---|
| `fnv_input` | 1,024 字节 INT8 输入 |
| `fnv_conv1_golden` | 4,096 字节 conv1 输出 |
| `fnv_relu1` | 4,096 字节 ReLU1 输出 |
| `fnv_conv2_golden` | 8,192 字节 conv2 输出 |
| `fnv_relu2` | 8,192 字节 ReLU2 输出 |
| `fnv_logits_le32` | 6 个 int32 小端的日志 |

## 准确率

本包这 {len(files)} 张上的整数准确率 = **{sum(r['correct'] for r in rows)}/{len(files)} = {acc:.4f}**。
这是**软件**结果；**板上准确率尚未测量**，需要另行授权、另行运行。

## 不包含什么

- **不含任何原始 BMP 或 `NEU-CLS.rar`**，也不含图像绝对路径（`index.csv` 只有文件名）
- 不含 ARM-only vs PS+PL 的延迟/加速数据
- 不含板上 BMP 解码/resize/量化的验证（本包的输入已经是**量化后的张量**，
  板上不需要再做预处理）
"""
    rp = os.path.join(OUT, "README.md")
    open(rp, "w", encoding="utf-8").write(readme)
    written.append(("README.md", os.path.getsize(rp),
                    hashlib.sha256(open(rp, "rb").read()).hexdigest()))
    print(f"  ✔ README.md               {os.path.getsize(rp):>10,} 字节")

    with open(os.path.join(OUT, "SHA256SUMS.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        for n, b, h in written:
            f.write(f"{h}  {n}\n")
    print(f"  ✔ SHA256SUMS.txt（{len(written)} 条）")
    print()
    print("=" * 94)
    print(f"✔ 导出完成 → {OUT}")
    print("  ★ 不含任何原始图像；只含量化后的整数张量与文件名")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
