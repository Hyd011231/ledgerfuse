"""无表格线 PDF 的 words 坐标法通用件（宁波银行 / 招商银行流水用）。

方法：get_text("words") 取出所有词 -> 按页面 rotation 变换到视觉坐标 ->
用表头词的 x 中心切出列区间 -> 以日期词为记录锚点，把锚点之间的词按列归并。
"""
from __future__ import annotations

import re
import fitz


def visual_words(page: fitz.Page) -> list[dict]:
    """页面所有词（视觉坐标，已处理 rotation），按 (y, x) 排序。"""
    mat = page.rotation_matrix
    out = []
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4])
        if page.rotation:
            r = r * mat
            r.normalize()
        out.append({"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
                    "cx": (r.x0 + r.x1) / 2, "cy": (r.y0 + r.y1) / 2,
                    "text": w[4]})
    out.sort(key=lambda d: (round(d["y0"], 1), d["x0"]))
    return out


def find_header_row(words: list[dict], labels: list[str], y_tol: float = 5.0) -> list[dict] | None:
    """找包含全部（或大部分）表头标签的那一行，返回按 x 排序的 [{'label','cx'}]。

    表头词可能被拆分/合并（如 '对方账号/卡号'），按"词文本是 label 的前缀或 label 是词的前缀"匹配。
    """
    # 候选：文本与某个 label 有前缀关系的词
    cands = []
    for w in words:
        for lb in labels:
            if w["text"] == lb or w["text"].startswith(lb) or lb.startswith(w["text"]):
                cands.append((lb, w))
                break
    if not cands:
        return None
    # 按 y 聚簇，找覆盖 label 最多的一行
    best_row, best_cnt = None, 0
    ys = sorted({round(w["cy"], 0) for _, w in cands})
    for y in ys:
        row = {}
        for lb, w in cands:
            if abs(w["cy"] - y) <= y_tol and lb not in row:
                row[lb] = w
        if len(row) > best_cnt:
            best_cnt, best_row = len(row), row
    if not best_row or best_cnt < max(3, len(labels) // 2):
        return None
    cols = [{"label": lb, "cx": w["cx"], "x0": w["x0"], "x1": w["x1"], "cy": w["cy"]}
            for lb, w in best_row.items()]
    cols.sort(key=lambda c: c["cx"])
    return cols


def column_bounds(cols: list[dict], page_width: float) -> list[tuple[float, float]]:
    """相邻表头中心的中点作为列边界，返回每列 (x_left, x_right)。"""
    bounds = []
    for i, c in enumerate(cols):
        left = 0.0 if i == 0 else (cols[i - 1]["cx"] + c["cx"]) / 2
        right = page_width if i == len(cols) - 1 else (c["cx"] + cols[i + 1]["cx"]) / 2
        bounds.append((left, right))
    return bounds


def group_records(words: list[dict], anchor_re: re.Pattern, anchor_col: tuple[float, float],
                  y_start: float, y_end: float) -> list[list[dict]]:
    """以匹配 anchor_re 且落在 anchor_col x 区间内的词为锚点，切分记录。

    返回每条记录的词列表（含锚点行到下一锚点之前的所有词）。
    """
    in_range = [w for w in words if y_start < w["cy"] < y_end]
    anchors = [w for w in in_range
               if anchor_re.fullmatch(w["text"]) and anchor_col[0] <= w["cx"] <= anchor_col[1]]
    anchors.sort(key=lambda w: w["y0"])
    records = []
    for i, a in enumerate(anchors):
        top = a["y0"] - 2
        bottom = anchors[i + 1]["y0"] - 2 if i + 1 < len(anchors) else y_end
        rec = [w for w in in_range if top <= w["y0"] < bottom]
        records.append(rec)
    return records


def group_records_centered(words: list[dict], anchor_re: re.Pattern, anchor_col: tuple[float, float],
                           y_start: float, y_end: float) -> list[list[dict]]:
    """居中对齐的表格（招行）：单元格多行内容以行中心对齐，锚点行是行的垂直中心。

    把每个词分配给中心距离最近的锚点。
    """
    in_range = [w for w in words if y_start < w["cy"] < y_end]
    anchors = [w for w in in_range
               if anchor_re.fullmatch(w["text"]) and anchor_col[0] <= w["cx"] <= anchor_col[1]]
    anchors.sort(key=lambda w: w["y0"])
    if not anchors:
        return []
    records: list[list[dict]] = [[] for _ in anchors]
    centers = [a["cy"] for a in anchors]
    # 记录带的上下界：首条之上一行内、末条之下留白由 y_end 控制
    top_limit = anchors[0]["y0"] - 16
    for w in in_range:
        if w["cy"] < top_limit:
            continue
        idx = min(range(len(centers)), key=lambda i: abs(w["cy"] - centers[i]))
        records[idx].append(w)
    return records


def record_to_cells(rec: list[dict], bounds: list[tuple[float, float]]) -> list[str]:
    """记录内的词按列区间归并，同列按 (y, x) 排序后拼接。"""
    cells = [[] for _ in bounds]
    for w in sorted(rec, key=lambda d: (round(d["y0"], 1), d["x0"])):
        for i, (lo, hi) in enumerate(bounds):
            if lo <= w["cx"] < hi:
                cells[i].append(w["text"])
                break
    return ["".join(c) for c in cells]
