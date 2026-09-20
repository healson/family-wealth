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
# 用 sed 而不是 grep -oP（后者依赖 GNU grep 的 PCRE，Windows Git Bash 上不一定有）；
# 解析失败就**直接中止**而不是回退到某个写死的版本号 —— 宁可不出包，也不能出一个
# 文件名版本号错误的 APK（装上去之后与 /api/health 对不上，排查起来很费劲）。
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' ../backend/app/main.py | head -1)
if [ -z "$VERSION" ]; then
  echo "❌ 无法从 ../backend/app/main.py 解析 VERSION，已中止（不猜版本号）。"
  exit 1
fi
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

# ---------- 清理 assets 下的历史备份目录（体积关键！） ----------
# android/app/src/main/assets/ 下的**全部内容**都会被打进 APK —— AAPT 会把整个 assets/
# 目录原样打包，不看你用不用。历史上（2026-08-25 ~ 08-30）多次同步在 assets/ 下留下了
# public_old_<时间戳> 备份目录，累积到 6 份、21.4 MB，而当前真正需要的 web 资源只有
# 2.5 MB —— 等于 APK 里近 90% 的 web 资源是废的（v1.7.9 的 12.6 MB 包就带着这些）。
echo ""
echo "▶ 清理 assets 下的历史备份目录..."
ASSETS_DIR="android/app/src/main/assets"
if [ -d "$ASSETS_DIR" ]; then
  STALE=$(find "$ASSETS_DIR" -maxdepth 1 -mindepth 1 -type d ! -name public)
  if [ -n "$STALE" ]; then
    echo "$STALE" | while IFS= read -r d; do
      [ -n "$d" ] || continue
      echo "   删除 $(basename "$d")  ($(du -sh "$d" 2>/dev/null | cut -f1))"
      rm -rf "$d"
    done
  else
    echo "   无历史备份目录"
  fi
  REMAIN=$(find "$ASSETS_DIR" -maxdepth 1 -mindepth 1 -type d ! -name public)
  if [ -n "$REMAIN" ]; then
    echo "❌ assets 下仍存在非 public 目录（会让 APK 体积虚高），已中止："
    echo "$REMAIN"
    exit 1
  fi
fi

# ---------- 打包 APK ----------
echo ""
echo "▶ Gradle 打包（首次会下载依赖，请耐心等待）..."
cd android

# 先删掉上一次的 APK 产物，强制 Gradle 重新写一个新文件。
# 不删的后果（v1.8.0 实测）：AGP 的增量打包会把上一版里**已删除**的条目保留在原偏移上、
# 写成零长度占位，于是新 APK 里留下大段零字节 —— 实测清掉 6 份历史 assets 备份后，
# 包内真实内容只剩 4.76 MB，文件却仍有 12.54 MB，其中 7.71 MB 是零填充。
# 删掉 outputs 后重打包立刻回到 4.84 MB。代价约 30 秒。
rm -rf app/build/outputs

if [ "$(uname -s)" = "MINGW"* ] || [ "$(uname -s)" = "MSYS"* ] || [ "$(uname -s)" = "CYGWIN"* ]; then
  ./gradlew.bat assembleDebug
else
  ./gradlew assembleDebug
fi
cd ..

APK="android/app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK" ]; then
  # ---------- 打包后自检：确认没有把历史 assets 备份带进包 ----------
  # 用 JDK 自带的 jar 列包内条目（不依赖 unzip，Windows Git Bash 上没有 unzip）。
  JAR="jar"
  if [ -n "$JAVA_HOME" ] && [ -x "$JAVA_HOME/bin/jar" ]; then
    JAR="$JAVA_HOME/bin/jar"
  fi
  if command -v "$JAR" >/dev/null 2>&1; then
    echo ""
    echo "▶ 自检：包内 assets 顶层条目..."
    ASSET_DIRS=$("$JAR" tf "$APK" | sed -n 's#^assets/\([^/]*\)/.*#\1#p' | sort -u)
    echo "$ASSET_DIRS" | sed 's/^/   assets\//'
    BAD=$(echo "$ASSET_DIRS" | grep -c '_old_')
    if [ "$BAD" != "0" ]; then
      echo "❌ 包内仍有 $BAD 个 _old_ 备份目录，APK 体积会虚高，请检查上面的清理步骤。"
      exit 1
    fi
    echo "   ✅ 无历史备份目录"
  else
    echo "⚠ 未找到 jar 命令，跳过包内自检"
  fi

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
