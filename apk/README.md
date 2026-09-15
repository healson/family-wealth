# 安卓安装包（APK）

本目录存放构建好的安卓安装包，直接下载即可安装，无需自行搭建 Android 构建环境。

## 命名规范

```
family-wealth-app-vX.Y.Z.apk
```

版本号取自 `backend/app/main.py` 的 `VERSION`，与后端、Docker 镜像同源（`build-apk.sh` 构建时读取，写入 `versionName` 与 `versionCode`）。

## 当前文件

| 文件 | 版本 | 大小 | 说明 |
|---|---|---|---|
| `family-wealth-app-v1.7.9.apk` | 1.7.9 | 12.6 MB | `versionCode=10709`，minSdk 24 / targetSdk 36，debug 签名 |

## 安装

覆盖安装即可保留数据（同包名 `com.family.wealth`、签名一致）。首次安装需在系统设置里允许「安装未知来源应用」。

## 校验

```bash
# 比对哈希（确认文件完整、与构建产物一致）
sha256sum family-wealth-app-v1.7.9.apk

# 查包内真实版本（APK 是压缩包，直接 grep 字符串查不到版本号）
aapt dump badging family-wealth-app-v1.7.9.apk | head -1
# 或读构建元数据：app/build/outputs/apk/debug/output-metadata.json
```

v1.7.9 的 SHA256：

```
a99cf32dfd43c649c17f41dd7f88ca095b10a05ac8c8945f51585b74296b4b3e
```

## 两点约定（重要）

1. **二进制入库不可回收**：APK 一旦提交，即使之后删除，它仍留在 git 历史里，仓库体积只增不减，此后每次发布约 +12.6 MB。
   - 若想控制体积：**每次只保留最新一版**（提交新版本时同步删除旧版本文件）——旧版本仍可从 git 历史里取回，也可在 GitHub Release 里挂附件。
   - 若想完全不占仓库：改用 GitHub Release 附件发布，本目录留空的 `README.md` 说明链接即可。

2. **不要用 `git add -A` 之外的方式遗漏本目录**：`frontend/android/**` 的构建产物（`build/`、`assets/public/`）已在 `.gitignore` 中排除，本目录是唯一入库的产物目录，二者不要混淆。
