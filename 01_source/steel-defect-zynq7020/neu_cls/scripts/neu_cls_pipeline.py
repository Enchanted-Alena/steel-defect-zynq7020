r"""
neu_cls_pipeline.py —— NEU-CLS 数据清点 / 近重复分群 / 分层切分 / 泄漏审计
================================================================================

版本：v2（2026-10-18 晚）
      v1 用 64 位 dHash 做近重复判据，**过度合并**：把 210 张 PS 图并成一群，
      导致训练集塌成"一块钢板"。原因见下方"为什么改判据"。

--------------------------------------------------------------------------------
为什么这件事这么重要（通俗版）
--------------------------------------------------------------------------------
NEU-CLS 每类 300 张 200×200 灰度图，是从**少量整块钢板**上裁下来的区域。
同一块钢板上的相邻区域长得极像。如果随机切分，训练集和测试集里会出现
"几乎同一张图" —— 模型在测试时等于**见过答案**。这叫**数据泄漏**，
它不会报错，只会让准确率虚高，而且骗得过所有人。

所以正确顺序是：**先找出"同源"的图 → 按群分组 → 以群为单位切分**。
从构造上保证同源的图不会跨越训练/测试边界。

--------------------------------------------------------------------------------
为什么改判据（v1 的错，值得记下来）
--------------------------------------------------------------------------------
v1 用 64 位 dHash（把图缩到 9×8，比较相邻像素大小）。问题是：
**9×8 只有 72 个像素的信息量**，大量视觉上完全不同的缺陷图，
梯度符号图案却是一样的。

实测（本项目 1800 张上）：
    64 位 dHash，阈值 ≤4/64          → Cr 205 群、In 94 群、**PS 88 群**
    其中 PS 有一个 **210 张**的巨群，In 有一个 **151 张**的巨群
→ 按这个分群切分，**PS 的训练集就只有 1 个群**（等于一块钢板）

换成更可解释、更有分辨力的判据后：
    **32×32 灰度归一化互相关（NCC）**，在 τ=0.98 下：
        Cr 300 群 / In 296 群（最大 5）/ Pa 299 群（最大 2）/
        PS 275 群（最大 10）/ RS 300 群 / Sc 300 群
→ 这才符合"NEU-CLS 是不同区域裁剪、只有极少数真正近乎相同"的事实。

**教训**：相似度判据必须**在真实数据上标定**，不能凭"常用做法"直接套。
哈希位数太低会把"结构相似"误当"内容相同"，进而把切分做废 ——
而且表面上每一步都"成功"了。

--------------------------------------------------------------------------------
相似度判据（本版）
--------------------------------------------------------------------------------
  主判据 : 32×32 灰度（双线性降采样）后做零均值归一化，取互相关 NCC ∈ [-1,1]
           两图 NCC ≥ τ 视为同源
  辅助   : 文件 SHA-256（精确重复，必然同源）
  交叉核对: 256 位 dHash（16×16），用于报告，不作为主判据

  切分阈值 τ_split（默认 0.98）与**审计阈值**（更低，例如 0.95/0.90）必须不同：
  用同一个尺子"切"再用它"查"，等于什么都没查。

用法
--------------------------------------------------------------------------------
    python neu_cls_pipeline.py all
    python neu_cls_pipeline.py all --tau 0.97
    python neu_cls_pipeline.py inventory | features | split | audit
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))            # 7/data/neu_cls
_PHASE = os.path.abspath(os.path.join(_DATA, ".."))     # 7/
MANIFESTS = os.path.join(_DATA, "manifests")
REPORTS = os.path.join(_DATA, "reports")

EXPECTED_ARCHIVE_SHA = ("a85bcc6bfa1a40e76f28079e135694aaf5f6a4ee01203f7"
                        "eaacff0ebafaa96f8")
EXPECTED_ARCHIVE_BYTES = 50733617
EXPECTED_BMP = 1800
EXPECTED_PER_CLASS = 300

CLASS_MAP = {
    "Cr": "Crazing",
    "In": "Inclusion",
    "Pa": "Patches",
    "PS": "Pitted Surface",
    "RS": "Rolled-in Scale",
    "Sc": "Scratches",
}
CLASS_ORDER = ["Cr", "In", "Pa", "PS", "RS", "Sc"]

SPLIT_RATIO = {"train": 0.70, "val": 0.15, "test": 0.15}
SPLIT_SEED = 20261018

# 审计用的更宽（更低）阈值 —— 阈值越低越宽松，越容易"查出"相似对
AUDIT_TAUS = (0.99, 0.98, 0.95, 0.90)


# ---------------------------------------------------------------------------
def ensure_dirs():
    for d in (MANIFESTS, REPORTS):
        os.makedirs(d, exist_ok=True)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def default_source_dirs():
    """
    用 `neu_cls_paths` 解析源数据（按特征搜索，跨阶段可定位）。

    ★ 原来写死 `<阶段>/A/NEU-CLS` —— 进入阶段 8 后源数据还在 7/A，
      立刻失效。这是本项目第三次踩"写死相对路径"的坑，改为统一解析。
    """
    import neu_cls_paths as ncp
    return (ncp.image_dir(), ncp.archive_rar() or "")


def parse_bmp_header(path):
    """直接解析 BMP 头 —— 独立于图像库的证据，用来核对 A 的清单声明。"""
    with open(path, "rb") as f:
        head = f.read(54)
    if len(head) < 54:
        return {"_error": "文件短于 54 字节"}
    if head[0:2] != b"BM":
        return {"_error": "不是 BMP"}
    (file_size,) = struct.unpack_from("<I", head, 2)
    (data_offset,) = struct.unpack_from("<I", head, 10)
    (dib_size,) = struct.unpack_from("<I", head, 14)
    (width,) = struct.unpack_from("<i", head, 18)
    (height,) = struct.unpack_from("<i", head, 22)
    (planes,) = struct.unpack_from("<H", head, 26)
    (bpp,) = struct.unpack_from("<H", head, 28)
    (compression,) = struct.unpack_from("<I", head, 30)
    return {"file_size": file_size, "data_offset": data_offset,
            "dib_header_size": dib_size, "width": width, "height": height,
            "planes": planes, "bits_per_pixel": bpp, "compression": compression}


def thumb_u8(arr, size=32):
    """32×32 双线性降采样后的 uint8 缩略图（存进清单，聚类时再归一化）。"""
    from PIL import Image
    return np.asarray(Image.fromarray(arr).resize((size, size), Image.BILINEAR),
                      dtype=np.uint8)


def thumb_vec(arr, size=32):
    """32×32 双线性降采样 → 零均值单位化向量（用于 NCC）。"""
    v = thumb_u8(arr, size).astype(np.float64).ravel()
    v = v - v.mean()
    nrm = np.linalg.norm(v)
    return v / nrm if nrm > 0 else v


def dhash_bits(arr, hash_size=16):
    """16×16 差分哈希 → 256 位（仅作报告/交叉核对，不作主判据）。"""
    from PIL import Image
    im = Image.fromarray(arr).resize((hash_size + 1, hash_size), Image.BILINEAR)
    a = np.asarray(im, dtype=np.int16)
    diff = (a[:, 1:] > a[:, :-1]).flatten()
    bits = 0
    for v in diff:
        bits = (bits << 1) | int(bool(v))
    return bits


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def sizes(self):
        d = {}
        for i in range(len(self.p)):
            d[self.find(i)] = d.get(self.find(i), 0) + 1
        return d

    def groups(self):
        g = {}
        for i in range(len(self.p)):
            g.setdefault(self.find(i), []).append(i)
        return sorted((sorted(v) for v in g.values()),
                      key=lambda x: (-len(x), x[0]))


def load_gray(src_img, fn):
    from PIL import Image
    return np.asarray(Image.open(os.path.join(src_img, fn)).convert("L"),
                      dtype=np.uint8)


# ---------------------------------------------------------------------------
# 阶段 1：清点
# ---------------------------------------------------------------------------

def stage_inventory(src_img, src_rar):
    ensure_dirs()
    print("=" * 92)
    print("【阶段 1】清点（归档身份 + BMP 头独立复核）")
    print("=" * 92)
    problems = []

    rar_info = {}
    if not os.path.isfile(src_rar):
        problems.append(f"归档不存在：{src_rar}")
    else:
        t0 = time.time()
        h = sha256_file(src_rar)
        size = os.path.getsize(src_rar)
        rar_info = {"path": src_rar, "sha256": h, "size_bytes": size,
                    "hash_seconds": round(time.time() - t0, 2)}
        print(f"  归档 : {os.path.basename(src_rar)}  {size:,} 字节")
        print(f"  SHA-256 : {h}")
        if h == EXPECTED_ARCHIVE_SHA:
            print("    ✔ 与 A 声明的归档哈希一致")
        else:
            problems.append(f"归档 SHA-256 不符：实测 {h}")
        if size != EXPECTED_ARCHIVE_BYTES:
            problems.append(f"归档字节数 {size} ≠ {EXPECTED_ARCHIVE_BYTES}")

    if not os.path.isdir(src_img):
        problems.append(f"图像目录不存在：{src_img}")
        return problems, []

    files = sorted(f for f in os.listdir(src_img) if f.lower().endswith(".bmp"))
    print(f"\n  BMP 文件数 : {len(files)}")
    if len(files) != EXPECTED_BMP:
        problems.append(f"BMP 数量 {len(files)} ≠ {EXPECTED_BMP}")

    per_class = {c: 0 for c in CLASS_ORDER}
    unknown, bad = [], []
    dims, bpps, comps, planes_set = set(), set(), set(), set()
    rows = []
    for fn in files:
        p = os.path.join(src_img, fn)
        prefix = os.path.splitext(fn)[0].split("_")[0]
        if prefix not in CLASS_MAP:
            unknown.append(fn)
        else:
            per_class[prefix] += 1
        hdr = parse_bmp_header(p)
        if "_error" in hdr:
            bad.append((fn, hdr["_error"]))
            continue
        dims.add((hdr["width"], hdr["height"]))
        bpps.add(hdr["bits_per_pixel"])
        comps.add(hdr["compression"])
        planes_set.add(hdr["planes"])
        rows.append({"file": fn, "class_prefix": prefix,
                     "class_name": CLASS_MAP.get(prefix, "UNKNOWN"),
                     "width": hdr["width"], "height": hdr["height"],
                     "bits_per_pixel": hdr["bits_per_pixel"],
                     "compression": hdr["compression"],
                     "size_bytes": hdr["file_size"],
                     "sha256": sha256_file(p)})

    print("  按类计数 :")
    for c in CLASS_ORDER:
        n = per_class[c]
        print(f"      {c:>3} ({CLASS_MAP[c]:<16}) {n:>4} 张  "
              f"{'✔' if n == EXPECTED_PER_CLASS else '✘ 应为 300'}")
        if n != EXPECTED_PER_CLASS:
            problems.append(f"类别 {c} 数量 {n} ≠ {EXPECTED_PER_CLASS}")
    if unknown:
        problems.append(f"文件名前缀不在六类内：{unknown[:5]}")
    if bad:
        problems.append(f"BMP 头解析失败 {len(bad)} 个：{bad[:3]}")

    print(f"\n  维度集合   : {sorted(dims)}")
    print(f"  位深集合   : {sorted(bpps)}")
    print(f"  压缩方式   : {sorted(comps)}  (0 = 未压缩)")
    print(f"  平面数集合 : {sorted(planes_set)}")
    if dims != {(200, 200)}:
        problems.append(f"维度不是全 200×200：{sorted(dims)}")
    if bpps != {8}:
        problems.append(f"位深不是全 8：{sorted(bpps)}")
    if comps != {0}:
        problems.append(f"存在压缩 BMP：{sorted(comps)}")
    if planes_set != {1}:
        problems.append(f"平面数不是全 1：{sorted(planes_set)}")

    extras = sorted(f for f in os.listdir(src_img)
                    if not f.lower().endswith(".bmp"))
    print(f"\n  非 BMP 额外文件 : {extras if extras else '（无）'}")

    inv = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_image_dir": src_img,
        "source_archive": rar_info,
        "archive_sha256_matches_A": rar_info.get("sha256") == EXPECTED_ARCHIVE_SHA,
        "bmp_count": len(files), "per_class": per_class,
        "class_map": CLASS_MAP,
        "dimensions": sorted(dims), "bits_per_pixel": sorted(bpps),
        "compression": sorted(comps), "planes": sorted(planes_set),
        "extra_files": extras, "unknown_prefix_files": unknown,
        "bad_headers": bad, "files": rows,
    }
    with open(os.path.join(MANIFESTS, "inventory.json"), "w",
              encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)
    with open(os.path.join(MANIFESTS, "files_sha256.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        for r in sorted(rows, key=lambda x: (x["class_prefix"], x["file"])):
            f.write(f"{r['sha256']}  {r['class_prefix']}/{r['file']}\n")

    print(f"  已写 manifests/inventory.json（{len(rows)} 条）与 files_sha256.txt")

    md = ["# NEU-CLS 清点报告（C 侧独立复核）", "",
          f"生成时间（UTC）：{inv['generated_utc']}", "",
          "## 归档", "",
          f"- 路径：`{rar_info.get('path', 'N/A')}`",
          f"- 字节数：{rar_info.get('size_bytes', 0):,}",
          f"- SHA-256：`{rar_info.get('sha256', 'N/A')}`",
          f"- 与 A 声明值一致：**{inv['archive_sha256_matches_A']}**", "",
          "> ⚠ 该哈希只证明「收到的就是这个文件」，**不是发布者签名**。", "",
          "## 图像", "", f"- BMP 总数：{len(files)}", "",
          "| 前缀 | 官方类别名 | 张数 |", "|---|---|---:|"]
    for c in CLASS_ORDER:
        md.append(f"| `{c}` | {CLASS_MAP[c]} | {per_class[c]} |")
    md += ["", f"- 维度：{sorted(dims)}",
           f"- 位深：{sorted(bpps)} bpp",
           f"- 压缩：{sorted(comps)}（0 = 未压缩）",
           f"- 平面数：{sorted(planes_set)}",
           f"- 额外文件（已排除，不进数据加载器）：{extras if extras else '无'}",
           "", "## 结论", "", "**通过**" if not problems else "**不通过**", ""]
    md += [f"- ✘ {p}" for p in problems]
    with open(os.path.join(REPORTS, "01_inventory.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print()
    if problems:
        print("  ✘ 清点不通过：")
        for p in problems:
            print(f"      - {p}")
    else:
        print("  ✔ 清点全部通过")
    return problems, rows


# ---------------------------------------------------------------------------
# 阶段 2：相似度特征
# ---------------------------------------------------------------------------

def stage_features(src_img, rows):
    ensure_dirs()
    print()
    print("=" * 92)
    print("【阶段 2】相似度特征（32×32 NCC 主判据 + 256 位 dHash 交叉核对）")
    print("=" * 92)
    feats = []
    t0 = time.time()
    for i, r in enumerate(rows):
        arr = load_gray(src_img, r["file"])
        v = thumb_vec(arr)
        feats.append({
            "file": r["file"], "class_prefix": r["class_prefix"],
            "sha256": r["sha256"],
            "dhash256": f"{dhash_bits(arr, 16):064x}",
            "thumb_mean": round(float(arr.mean()), 3),
            "thumb_std": round(float(arr.std()), 3),
            # 存 32×32 uint8 缩略图（1024 字节 → 2048 hex），聚类时重算归一化向量
            "thumb_hex": thumb_u8(arr).tobytes().hex(),
        })
        if (i + 1) % 600 == 0:
            print(f"      … {i+1}/{len(rows)}")
    with open(os.path.join(MANIFESTS, "features.json"), "w",
              encoding="utf-8") as f:
        json.dump(feats, f, ensure_ascii=False)
    print(f"  ✔ {len(feats)} 张，用时 {time.time()-t0:.1f}s")
    print("  已写 manifests/features.json")
    return feats


def vec_from_hex(hx):
    a = np.frombuffer(bytes.fromhex(hx), dtype=np.uint8).astype(np.float64)
    a = a - a.mean()
    n = np.linalg.norm(a)
    return a / n if n > 0 else a


# ---------------------------------------------------------------------------
# 阶段 3：分群 + 分层切分
# ---------------------------------------------------------------------------

def _clusters_for_class(class_rows, tau):
    n = len(class_rows)
    X = np.stack([vec_from_hex(r["thumb_hex"]) for r in class_rows])
    C = X @ X.T
    uf = UnionFind(n)
    # 精确重复一律同源
    by_sha = {}
    for i, r in enumerate(class_rows):
        by_sha.setdefault(r["sha256"], []).append(i)
    for idxs in by_sha.values():
        for j in idxs[1:]:
            uf.union(idxs[0], j)
    for i, j in np.argwhere(np.triu(C >= tau, 1)):
        uf.union(int(i), int(j))
    return uf.groups(), C


def stage_split(feats, tau, ratio, seed, src_img):
    ensure_dirs()
    print()
    print("=" * 92)
    print("【阶段 3】近重复分群（NCC ≥ τ）+ 以群为单位的分层切分")
    print("=" * 92)
    print(f"  τ_split = {tau}   种子 = {seed}   比例 = {ratio}")
    print()

    by_class = {}
    for r in feats:
        by_class.setdefault(r["class_prefix"], []).append(r)
    for c in by_class:
        by_class[c].sort(key=lambda x: x["file"])

    rng = np.random.Generator(np.random.PCG64(seed))
    assignment, cluster_info, class_report = {}, {}, {}

    for c in CLASS_ORDER:
        rows = by_class[c]
        clusters, _ = _clusters_for_class(rows, tau)
        sizes = [len(g) for g in clusters]
        n = len(rows)
        targets = {k: int(round(n * v)) for k, v in ratio.items()}
        targets["train"] += n - sum(targets.values())
        got = {k: 0 for k in ratio}

        order = list(range(len(clusters)))
        rng.shuffle(order)
        order.sort(key=lambda i: -len(clusters[i]))

        for ci in order:
            members = clusters[ci]
            best, best_gap = None, -1
            for k in ("train", "val", "test"):
                gap = targets[k] - got[k]
                if gap > best_gap:
                    best, best_gap = k, gap
            if best_gap <= 0:
                best = max(("train", "val", "test"),
                           key=lambda k: targets[k] - got[k])
            for i in members:
                assignment[rows[i]["file"]] = best
            got[best] += len(members)

        cl_sizes = sorted(sizes, reverse=True)
        cluster_info[c] = {"n_images": n, "n_clusters": len(clusters),
                           "largest_cluster": cl_sizes[0],
                           "singletons": sum(1 for s in cl_sizes if s == 1)}
        class_report[c] = {"targets": targets, "achieved": got,
                           "n_clusters": len(clusters)}

    split = {"train": [], "val": [], "test": []}
    for fn, sp in assignment.items():
        split[sp].append(fn)
    for k in split:
        split[k].sort()

    # 每个集合里的群结构（关键：训练集不能塌成 1 个群）
    per_split_clusters = {}
    for c in CLASS_ORDER:
        rows = by_class[c]
        clusters, _ = _clusters_for_class(rows, tau)
        d = {}
        for k in ("train", "val", "test"):
            cs = [cl for cl in clusters
                  if assignment[rows[cl[0]]["file"]] == k]
            d[k] = {"n_images": sum(len(x) for x in cs),
                    "n_clusters": len(cs),
                    "largest_cluster": max((len(x) for x in cs), default=0)}
        per_split_clusters[c] = d

    manifest = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": "NEU-CLS",
        "purpose": "限定应用验证：六类图像分类（32×32 灰度）",
        "near_dup_metric": {
            "primary": "32x32 grayscale bilinear-downsample, zero-mean "
                       "normalized cross-correlation (NCC)",
            "threshold_tau": tau,
            "exact_dup": "identical file SHA-256 always merged",
            "cross_check": "256-bit dHash retained for reporting only",
            "note": "v1 used 64-bit dHash and OVER-MERGED (PS: 210-image "
                    "cluster); switched after calibrating on this dataset",
        },
        "split_algo": {
            "method": "grouped_stratified_by_ncc_cluster",
            "cluster_rule": "union-find, same class, NCC >= tau, exact dups "
                            "always merged",
            "group_ordering": "size descending, ties by seeded shuffle",
            "ratio": ratio, "seed": seed, "rng": "numpy PCG64",
        },
        "counts": {k: len(v) for k, v in split.items()},
        "class_clusters": cluster_info,
        "class_targets_vs_achieved": class_report,
        "per_split_clusters": per_split_clusters,
        "assignment": split,
    }
    with open(os.path.join(MANIFESTS, "split_v1.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    by_file = {r["file"]: r for r in feats}
    with open(os.path.join(MANIFESTS, "split_v1.csv"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("file,class_prefix,class_name,split,sha256\n")
        for k in ("train", "val", "test"):
            for fn in split[k]:
                r = by_file[fn]
                f.write(f"{fn},{r['class_prefix']},"
                        f"{CLASS_MAP[r['class_prefix']]},{k},{r['sha256']}\n")

    print("  各类分群结构（τ=%.2f）：" % tau)
    for c in CLASS_ORDER:
        ci = cluster_info[c]
        print(f"      {c:>3}: {ci['n_images']:>4} 张 → {ci['n_clusters']:>4} 群"
              f"  (最大群 {ci['largest_cluster']:>3}, 单张群 {ci['singletons']:>4})")
    print()
    print("  切分后每个集合的群结构（★ 训练集群数越多越好）：")
    print(f"      {'类':<4}{'集合':<7}{'张数':>5}{'群数':>6}{'最大群':>7}")
    for c in CLASS_ORDER:
        for k in ("train", "val", "test"):
            d = per_split_clusters[c][k]
            warn = "   ⚠ 训练集过于集中" if (k == "train" and d["n_clusters"] <= 3) else ""
            print(f"      {c:<4}{k:<7}{d['n_images']:>5}{d['n_clusters']:>6}"
                  f"{d['largest_cluster']:>7}{warn}")
    print()
    print(f"  合计：train {len(split['train'])}, val {len(split['val'])}, "
          f"test {len(split['test'])}")
    print("  已写 manifests/split_v1.json 与 split_v1.csv")
    return manifest, by_file, by_class


# ---------------------------------------------------------------------------
# 阶段 4：泄漏审计
# ---------------------------------------------------------------------------

def stage_audit(feats, manifest, by_class, tau_split):
    ensure_dirs()
    print()
    print("=" * 92)
    print("【阶段 4】泄漏审计（精确重复 + 近重复，多阈值）")
    print("=" * 92)
    problems = []
    split_of = {}
    for k in ("train", "val", "test"):
        for fn in manifest["assignment"][k]:
            split_of[fn] = k

    # 精确重复
    by_sha = {}
    for r in feats:
        by_sha.setdefault(r["sha256"], []).append(r["file"])
    dups = {h: v for h, v in by_sha.items() if len(v) > 1}
    exact_cross = [(h, fs) for h, fs in dups.items()
                   if len({split_of[f] for f in fs}) > 1]
    print("  【精确重复】")
    if not dups:
        print("      ✔ 1800 个不同 SHA-256，无字节级重复")
    else:
        for h, fs in dups.items():
            sp = [split_of[f] for f in fs]
            print(f"      {h[:16]}… → {fs}  集合 {sp}  "
                  f"{'✔ 同集' if len(set(sp)) == 1 else '✘ 跨集'}")
        if exact_cross:
            problems.append(f"精确重复跨集 {len(exact_cross)} 组")
        else:
            print("      ✔ 精确重复组都在同一集合内")

    # 近重复多阈值
    print("\n  【近重复】按类比较，统计跨集对数（阈值越低越宽松，越容易查出相似对）")
    hdr = f"      {'τ':>6}{'同类相似对':>12}{'跨集对':>9}{'跨 train/test':>15}  判定"
    print(hdr)
    detail = {}
    for tau in AUDIT_TAUS:
        tot = cross = cross_tt = 0
        for c in CLASS_ORDER:
            rows = by_class[c]
            n = len(rows)
            X = np.stack([vec_from_hex(r["thumb_hex"]) for r in rows])
            C = X @ X.T
            for i, j in np.argwhere(np.triu(C >= tau, 1)):
                tot += 1
                si, sj = split_of[rows[i]["file"]], split_of[rows[j]["file"]]
                if si != sj:
                    cross += 1
                    if {si, sj} == {"train", "test"}:
                        cross_tt += 1
        verdict = ("✔ 无跨集" if cross == 0
                   else f"⚠ {cross} 跨集")
        detail[tau] = {"similar_pairs": tot, "cross_pairs": cross,
                       "cross_train_test": cross_tt}
        print(f"      {tau:>6.2f}{tot:>12}{cross:>9}{cross_tt:>15}  {verdict}")

    strict = detail.get(tau_split)
    if strict and strict["cross_pairs"]:
        problems.append(f"切分阈值 τ={tau_split} 下仍有跨集相似对")
    print(f"\n      τ_split = {tau_split} 下跨集对 = "
          f"{strict['cross_pairs'] if strict else 'N/A'}"
          f"（构造上保证为 0）")
    print("      更宽松阈值下出现的跨集对**是真实的相似、不是泄漏**，")
    print("      但报告必须写明用的是哪个阈值 —— 只写「已做泄漏检查」等于没说。")

    # 报告
    md = ["# NEU-CLS 泄漏审计（C 侧）", "",
          f"生成时间（UTC）：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
          "", "## 判据", "",
          "- 主判据：32×32 灰度归一化互相关（NCC）",
          f"- 切分阈值 τ_split = **{tau_split}**（NCC ≥ τ 视为同源，必同组）",
          "- 精确重复：文件 SHA-256 相同（一律同源）",
          "- 审计用更低阈值（更宽松）：见下表", "",
          "## 精确重复", "",
          f"- 重复组数：{len(dups)}，其中跨集 {len(exact_cross)} 组", ""]
    if dups:
        md += ["| SHA-256 | 文件 | 集合 |", "|---|---|---|"]
        for h, fs in dups.items():
            md.append(f"| `{h}` | {', '.join(fs)} | "
                      f"{', '.join(split_of[f] for f in fs)} |")
        md.append("")
    md += ["## 近重复（多阈值）", "",
           "| τ | 同类相似对 | 跨集对 | 跨 train/test |", "|---:|---:|---:|---:|"]
    for tau in AUDIT_TAUS:
        d = detail[tau]
        md.append(f"| {tau} | {d['similar_pairs']} | {d['cross_pairs']} | "
                  f"{d['cross_train_test']} |")
    md += ["", "## 结论", "", "**审计通过**" if not problems else "**审计不通过**", ""]
    md += [f"- ✘ {p}" for p in problems]
    md += ["", "## 读这张表要注意什么", "",
           f"τ = {tau_split} 那一行必然是 0 —— 因为切分就是按这个阈值分群的。",
           "**这不是「发现数据干净」，而是「我设计的」。**",
           "",
           "真正有信息量的是**更低阈值**（0.95、0.90）那几行：它们用更宽的尺子去量，",
           "如果那里出现大量跨集对，说明**不同钢板上的缺陷本身就长得很像** ——",
           "这是数据特性，不是切分错误，但必须写清楚，否则读者会误以为测试集",
           "与训练集完全无关。", ""]
    with open(os.path.join(REPORTS, "02_leakage_audit.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n  已写 reports/02_leakage_audit.md")
    return problems, detail


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="NEU-CLS 数据流水线 v2")
    ap.add_argument("stage", choices=["inventory", "features", "split",
                                      "audit", "all"])
    ap.add_argument("--images", default=None)
    ap.add_argument("--rar", default=None)
    ap.add_argument("--tau", type=float, default=0.98,
                    help="近重复 NCC 阈值（默认 0.98）")
    ap.add_argument("--seed", type=int, default=SPLIT_SEED)
    args = ap.parse_args()

    d_img, d_rar = default_source_dirs()
    src_img = args.images or d_img
    src_rar = args.rar or d_rar

    problems = []
    rows = feats = manifest = by_class = None

    if args.stage in ("inventory", "all"):
        problems, rows = stage_inventory(src_img, src_rar)
        if problems and args.stage == "all":
            print("\n✘ 清点未通过，停止后续阶段")
            return 1

    if args.stage == "features":
        inv = json.load(open(os.path.join(MANIFESTS, "inventory.json"),
                             encoding="utf-8"))
        rows = inv["files"]

    if args.stage in ("features", "all"):
        feats = stage_features(src_img, rows)

    if feats is None:
        fp = os.path.join(MANIFESTS, "features.json")
        if not os.path.isfile(fp):
            print("✘ 请先跑 features 阶段")
            return 1
        feats = json.load(open(fp, encoding="utf-8"))

    if args.stage in ("split", "all"):
        manifest, by_file, by_class = stage_split(feats, args.tau, SPLIT_RATIO,
                                                  args.seed, src_img)

    if manifest is None:
        manifest = json.load(open(os.path.join(MANIFESTS, "split_v1.json"),
                                  encoding="utf-8"))
        by_class = {}
        for r in feats:
            by_class.setdefault(r["class_prefix"], []).append(r)
        for c in by_class:
            by_class[c].sort(key=lambda x: x["file"])

    if args.stage in ("audit", "all"):
        p2, _ = stage_audit(feats, manifest, by_class, args.tau)
        problems += p2

    print()
    print("=" * 92)
    if problems:
        print(f"✘ 有 {len(problems)} 项不通过")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("✔ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
