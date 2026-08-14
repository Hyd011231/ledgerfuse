"""生成打包用图标：packaging/icon.icns（macOS）与 icon.ico（Windows）。

复用 mac/make_icon.py 里的绘制逻辑，CI 和本地都跑这一个入口。
用法：python packaging/make_icons.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mac"))

from make_icon import render  # noqa: E402

if __name__ == "__main__":
    img = render()
    out = ROOT / "packaging"
    img.save(out / "icon.icns", format="ICNS")
    img.save(out / "icon.ico", format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(out / "icon.png")
    print("生成：", ", ".join(p.name for p in out.glob("icon.*")))
