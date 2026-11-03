r"""
neu_cls_paths.py —— NEU-CLS 源数据与产物的**唯一**路径来源
================================================================================

--------------------------------------------------------------------------------
为什么需要这个模块（这是第 3 次踩同一个坑）
--------------------------------------------------------------------------------
我在本项目里已经两次因为"写死相对路径"而失败：
  1. `validate_parsers_on_b.py` 写死 `../../../B_handoff_2026-10-11/…`，换个阶段就找不到；
  2. `verify_b_board_evidence` 写死 `../B2`，同样换阶段即失效。

NEU-CLS 的图像在 `7/A/NEU-CLS`（1800 张，70 MB），而我这一阶段在 `8/`。
如果写死 `8/A/NEU-CLS` 就立刻再踩一次；如果把 70 MB 复制一份，又浪费且会出现
"两份源数据哪个是权威"的问题。

所以统一成：**按特征搜索**（找同时具备 `Cr_1.bmp`…`Sc_300.bmp` 的目录），
找不到就报错并列出搜过的位置 —— 不猜、不复制、不写死。

--------------------------------------------------------------------------------
解析顺序
--------------------------------------------------------------------------------
  1. 环境变量 `NEU_CLS_IMAGES` / `NEU_CLS_RAR`
  2. `local_config.json`（本模块同目录，机器本地，不外发）
  3. 从本文件所在阶段根**逐级向上**，每级向下 `SEARCH_DEPTH` 层搜索
     （这样 `7/A/NEU-CLS` 能被 `8/` 里的脚本找到）

用法
--------------------------------------------------------------------------------
    import neu_cls_paths as ncp
    img = ncp.image_dir()      # 找不到会抛 NotConfigured，带修复指引
    rar = ncp.archive_rar()
"""

import glob
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, ".."))            # <phase>/data/neu_cls
_PHASE = os.path.abspath(os.path.join(_DATA, ".."))     # <phase>/
_CONF = os.path.join(_HERE, "local_config.json")

ENV_IMAGES = "NEU_CLS_IMAGES"
ENV_RAR = "NEU_CLS_RAR"

# 目录内容特征：六个类的首末样本文件名
_PROBE_FILES = ("Cr_1.bmp", "Sc_300.bmp")
RAR_NAME = "NEU-CLS.rar"
SEARCH_DEPTH = 4
UP_LEVELS = 4


class NotConfigured(RuntimeError):
    """源数据未找到。这是配置问题，不是程序 bug。"""


def _local():
    if os.path.isfile(_CONF):
        try:
            return json.load(open(_CONF, encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            return {}
    return {}


def _explain(what, env, key, tried):
    lines = [f"\n未找到：{what}\n",
             f"  请用环境变量指定：\n      $env:{env} = \"<实际路径>\"\n",
             f"  或写进 {os.path.relpath(_CONF, _HERE)}：\n"
             f"      {{ \"{key}\": \"<实际路径>\" }}\n",
             "  已搜索的位置："]
    lines += [f"      {t}" for t in tried]
    lines.append("\n  说明：本模块刻意**不猜路径、也不复制源数据** —— "
                 "复制会制造「两份源数据哪个权威」的问题。")
    return "\n".join(lines)


def _is_image_dir(d):
    return all(os.path.isfile(os.path.join(d, f)) for f in _PROBE_FILES)


def image_dir():
    """NEU-CLS 解包后的图像目录（含 1800 张 BMP）。"""
    v = os.environ.get(ENV_IMAGES) or _local().get("image_dir")
    if v:
        v = os.path.abspath(v)
        if _is_image_dir(v):
            return v
        raise NotConfigured(f"\n已配置的图像目录不像 NEU-CLS：{v}\n"
                            f"  该目录应含 {' 与 '.join(_PROBE_FILES)}\n")
    tried, level = [], _PHASE
    for _ in range(UP_LEVELS):
        for depth in range(1, SEARCH_DEPTH + 1):
            pat = os.path.join(level, *(["*"] * depth))
            for cand in glob.glob(pat):
                if os.path.isdir(cand) and _is_image_dir(cand):
                    return os.path.abspath(cand)
                tried.append(cand)
        level = os.path.dirname(level)
        if not level or level == os.path.dirname(level):
            break
    raise NotConfigured(_explain("NEU-CLS 图像目录", ENV_IMAGES, "image_dir",
                                 tried[:20] or ["（无）"]))


def archive_rar():
    """NEU-CLS 原始归档（只读；用于复核 SHA-256）。找不到时返回 None。"""
    v = os.environ.get(ENV_RAR) or _local().get("rar_path")
    if v and os.path.isfile(v):
        return os.path.abspath(v)
    tried, level = [], _PHASE
    for _ in range(UP_LEVELS):
        for depth in range(1, SEARCH_DEPTH + 1):
            pat = os.path.join(level, *(["*"] * (depth - 1)), RAR_NAME)
            for hit in glob.glob(pat):
                if os.path.isfile(hit):
                    return os.path.abspath(hit)
        level = os.path.dirname(level)
        if not level or level == os.path.dirname(level):
            break
    return None


def describe():
    print("=" * 84)
    print("NEU-CLS 路径解析")
    print("=" * 84)
    try:
        d = image_dir()
        n = len([f for f in os.listdir(d) if f.lower().endswith(".bmp")])
        print(f"  [✔] 图像目录 : {d}")
        print(f"       BMP 数  : {n}")
    except NotConfigured as e:
        print(f"  [✘] 图像目录 : 未找到")
        print(str(e))
    r = archive_rar()
    print(f"  [{'✔' if r else '·'}] 归档     : {r or '（未找到，将跳过归档哈希复核）'}")
    print("=" * 84)


if __name__ == "__main__":
    describe()
