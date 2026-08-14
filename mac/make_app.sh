#!/bin/bash
# 生成 合账(LedgerFuse).app 到 ~/Applications，双击即可启动（原生窗口，关窗即退出）。
# 前提：backend/.venv 已建好并装完依赖（含 pywebview），frontend/dist 已构建。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/Applications/LedgerFuse.app"
PYTHON="$REPO_DIR/backend/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "错误：找不到 $PYTHON（先在 backend/ 下创建 .venv 并安装 requirements.txt）"
  exit 1
fi

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LedgerFuse</string>
  <key>CFBundleDisplayName</key><string>合账</string>
  <key>CFBundleIdentifier</key><string>app.ledgerfuse</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>ledger</string>
  <key>CFBundleIconFile</key><string>appicon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# 新版 macOS 要求 CFBundleExecutable 是 Mach-O（shell 脚本会被 LaunchServices 以 -10669 拒绝），
# 编一个微型启动器：exec 到 venv python 保持同一进程，Dock 显示的是本 App
SHIM_SRC="$(mktemp -t ledger-shim).c"
cat > "$SHIM_SRC" <<'EOF'
#include <unistd.h>
int main(void) {
    chdir(BACKEND_DIR);
    execl(PY, PY, "desktop.py", (char *)0);
    return 1;
}
EOF
clang -O2 -DBACKEND_DIR="\"$REPO_DIR/backend\"" -DPY="\"$PYTHON\"" \
      -o "$APP_DIR/Contents/MacOS/ledger" "$SHIM_SRC"
rm -f "$SHIM_SRC"

# 图标：make_icon.py 画 1024 母图，切各尺寸后打成 icns（失败不影响使用）
TMP="$(mktemp -d)"
if "$PYTHON" "$(dirname "$0")/make_icon.py" "$TMP/icon.png"; then
  ICONSET="$TMP/appicon.iconset"
  mkdir "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z "$((s*2))" "$((s*2))" "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/appicon.icns"
else
  echo "警告：图标生成失败（需要 Pillow），App 会用系统默认图标"
fi
rm -rf "$TMP"

codesign --force -s - "$APP_DIR"
touch "$APP_DIR"
echo "已生成：$APP_DIR"
