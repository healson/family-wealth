#!/usr/bin/env bash
# ============================================================
# family-wealth 安卓 APK 一键打包脚本（Windows Git Bash / macOS / Linux）
# 依赖：JDK 21 + Android SDK（或用 Android Studio 自带环境）
# 用法：
#   NAS_URL=http://192.168.1.100:8000/api ./build-apk.sh
#   （NAS_URL 为家庭财富后端的访问地址，默认 http://192.168.1.100:8000/api）
# 产物（带版本号）：family-wealth-app-vX.Y.Z.apk（复制到本目录）
# ============================================================
set -e
cd "$(dirname "$0")"

NAS_URL="${NAS_URL:-http://192.168.1.100:8000/api}"
echo "=========================================="
echo "后端 API 地址: $NAS_URL"
echo "（如不是此地址，请用 NAS_URL 环境变量指定）"
echo "=========================================="

# 版本号：唯一事实来源 = backend/app/main.py 的 VERSION
VERSION=$(grep -oP 'VERSION = "\K[^"]+' ../backend/app/main.py 2>/dev/null || echo "1.6.3")
echo "当前版本: v$VERSION"

# ---------- 环境检查 ----------
if ! command -v java >/dev/null 2>&1 && [ -z "$JAVA_HOME" ]; then
  echo "❌ 未找到 JDK。请安装 JDK 21 并设置 JAVA_HOME，或使用 Android Studio 自带的 JDK。"
  exit 1
fi
JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/}java"
echo "✅ Java: $($JAVA_BIN -version 2>&1 | head -1)"

if [ -z "$ANDROID_HOME" ] && [ -z "$ANDROID_SDK_ROOT" ]; then
  echo "❌ 未找到 Android SDK。请安装并设置 ANDROID_HOME（如 C:\\Users\\<你>\\AppData\\Local\\Android\\Sdk）。"
  exit 1
fi
echo "✅ Android SDK: ${ANDROID_HOME:-$ANDROID_SDK_ROOT}"

# ---------- 构建前端（注入 NAS API 地址） ----------
echo ""
echo "▶ 构建前端（API 地址 = $NAS_URL）..."
# vite.config.js 里 emptyOutDir=false（避免 Windows 文件占用导致构建失败），
# 代价是旧 hash 产物会在 dist/ 里累积、并被一并打进 APK。这里的先清空保证产物干净。
rm -rf dist
VITE_API_BASE="$NAS_URL" npm run build

# ---------- 同步 web 资源到安卓工程 ----------
echo ""
echo "▶ 同步资源到安卓工程..."
# Windows 上 `cap sync/copy` 有概率在清理插件文件时报错（universalify remove 异常）。
# 失败不影响打包：回退为手动同步 web 资源即可（等价于 cap copy 的产物拷贝部分，
# 插件配置 capacitor.config.json / capacitor.plugins.json 已在工程内且未变更）。
if ! npx cap sync android; then
  echo "⚠ cap sync 失败，回退为手动同步 web 资源（Windows 已知问题）..."
  rm -rf android/app/src/main/assets/public
  cp -r dist android/app/src/main/assets/public
fi

# ---------- 打包 APK ----------
echo ""
echo "▶ Gradle 打包（首次会下载依赖，请耐心等待）..."
cd android
if [ "$(uname -s)" = "MINGW"* ] || [ "$(uname -s)" = "MSYS"* ] || [ "$(uname -s)" = "CYGWIN"* ]; then
  ./gradlew.bat assembleDebug
else
  ./gradlew assembleDebug
fi
cd ..

APK="android/app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK" ]; then
  # 复制为带版本号的文件名（便于区分安装版本）
  RELEASED="family-wealth-app-v${VERSION}.apk"
  cp "$APK" "$RELEASED"
  echo ""
  echo "✅ 打包成功："
  echo "   $RELEASED"
  ls -lh "$APK" "$RELEASED" | awk '{print "   ", $9, $5}'
else
  echo "❌ 未找到 APK 产物，请查看上方 Gradle 输出。"
  exit 1
fi
