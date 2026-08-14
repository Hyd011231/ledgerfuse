"""绘制 App 图标（1024x1024 PNG），由 make_app.sh 转成 icns。

用法：python make_icon.py 输出路径.png
配色走浅暖色：琥珀到陶土的渐变底 + 白色账页 + 上升柱状图。
"""

import math
import sys

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4  # 超采样倍数，画完再缩回 SIZE 得到平滑边缘

BG_TOP = (251, 208, 138)
BG_BOTTOM = (237, 149, 96)
SHEET = (255, 252, 247)
SPINE = (243, 203, 167)
BARS = [(240, 168, 104), (233, 140, 85), (217, 113, 63)]
BASELINE = (231, 205, 184)


def squircle(box, n=5.0, steps=720):
    """Apple 图标那种超椭圆圆角方形。box 为 (x0, y0, x1, y1)。"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a, b = (x1 - x0) / 2, (y1 - y0) / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        pts.append(
            (
                cx + a * math.copysign(abs(ct) ** (2 / n), ct),
                cy + b * math.copysign(abs(st) ** (2 / n), st),
            )
        )
    return pts


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        k = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * k) for i in range(3))
    return img.resize((size, size))


def render():
    s = SIZE * SS
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 渐变底 + 超椭圆遮罩。824/1024 是 Apple 图标模板里画布的占比
    inset = round(s * 100 / 1024)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(squircle((inset, inset, s - inset, s - inset)), fill=255)
    canvas.paste(vertical_gradient(s, BG_TOP, BG_BOTTOM), (0, 0), mask)

    # 白色账页，左侧留一条装订侧脊。圆角要裁到侧脊上，所以先画在单独图层再按遮罩贴
    pad = round(s * 226 / 1024)
    sheet = (pad, round(s * 262 / 1024), s - pad, s - round(s * 246 / 1024))
    radius = round(s * 46 / 1024)
    x0, y0, x1, y1 = sheet
    spine = round(s * 62 / 1024)

    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle(sheet, fill=SHEET)
    ld.rectangle((x0, y0, x0 + spine, y1), fill=SPINE)
    sheet_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(sheet_mask).rounded_rectangle(sheet, radius=radius, fill=255)
    canvas.paste(layer, (0, 0), sheet_mask)

    d = ImageDraw.Draw(canvas)

    # 三根上升柱子，圆头
    bx0, bx1 = x0 + spine + round(s * 34 / 1024), x1 - round(s * 42 / 1024)
    base = y1 - round(s * 50 / 1024)
    gap = round(s * 28 / 1024)
    bw = (bx1 - bx0 - gap * 2) / 3
    heights = [0.54, 0.77, 1.0]
    tallest = base - (y0 + round(s * 66 / 1024))
    for i, h in enumerate(heights):
        left = bx0 + i * (bw + gap)
        d.rounded_rectangle(
            (round(left), round(base - tallest * h), round(left + bw), base),
            radius=round(bw / 2),
            fill=BARS[i],
        )

    # 柱子底下的基准线
    lh = round(s * 10 / 1024)
    d.rounded_rectangle((bx0, base, bx1, base + lh), radius=lh // 2, fill=BASELINE)

    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    render().save(sys.argv[1])
