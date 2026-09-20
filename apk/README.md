# 安卓安装包（APK）分发说明

**本目录不再存放 APK 文件。** APK 改为通过 **GitHub Release 附件**发布。

## 为什么改（v1.8.0 起）

v1.7.9 时把 12.6 MB 的 APK 提交进了本目录，代价实测如下：

| 问题 | 实际情况 |
|---|---|
| 体积只增不减 | 二进制一旦进 git 对象库，**即使后来删除也删不掉**，此后每版约 +12.6 MB |
| clone / CI 变慢 | 每次 `actions/checkout` 都要下载完整历史，包体越来越大 |
| 跟代码版本耦合 | APK 与源码版本不同步时只能靠人工判断该不该更新 |
| 无法替换 | 传错了只能再加一版，不能覆盖 |

Release 附件没有这些问题：不进 git 对象库、可随时替换、有稳定直链、可带校验信息与发布说明。

## 现在去哪里下载

**方式一（推荐）**：仓库 Releases 页

```
https://github.com/healson/family-wealth/releases
```

点最新版本的 `family-wealth-app-vX.Y.Z.apk` 即下载。

> ⚠️ 仓库是**私有**的，下载前需在浏览器里登录 GitHub；手机浏览器同样要登录，
> 否则点链接会 403。如果不希望每次登录，可以把仓库转公开，或改用其它分发方式。

**方式二**：自己构建

```bash
cd frontend && bash build-apk.sh
# 产物：family-wealth-app-vX.Y.Z.apk（版本号自动取自 backend/app/main.py 的 VERSION）
```

## 命名规范（不变）

```
family-wealth-app-vX.Y.Z.apk
```

版本号取自 `backend/app/main.py` 的 `VERSION`，与后端、Docker 镜像、tar.gz 同源：
`android/app/build.gradle` 在构建时读取该文件，写入 `versionName` 与
`versionCode`（`X*10000 + Y*100 + Z`，如 1.7.9 → `10709`）。

## 发布流程（发布 APK 时照做）

```bash
# 1) 构建（本机需 JDK 21 + Android SDK，环境与耗时见 README 的「安卓 App（APK）打包」）
cd frontend && bash build-apk.sh

# 2) 校验包信息与哈希
aapt2 dump badging family-wealth-app-vX.Y.Z.apk | head -3   # 包名 / versionCode / versionName
ls -la family-wealth-app-vX.Y.Z.apk                          # 体积应约 4.8～5.0 MB
sha256sum family-wealth-app-vX.Y.Z.apk

# 3) 发布到 Release 附件（幂等：同名同尺寸会跳过，尺寸不同才先删后传）
GH_PAT_FILE=<含 repo 权限的 PAT 文件> \
TAG=vX.Y.Z \
APK=<APK 绝对路径> \
BODY_FILE=tools/release-notes/vX.Y.Z.md \
python tools/github_publish_release.py
```

**体积自查**：正常包约 **4.8～5.0 MB**。若明显偏大（历史上出现过 12.5 MB），是两个原因之一：
① `android/app/src/main/assets/` 下残留了 `public_old_*` 历史备份（AAPT 会把 `assets/` 整个打进包）；
② AGP 增量打包留下零填充。`build-apk.sh` 已对两者做了防护，正常走脚本不会再出现。

`tools/github_publish_release.py` 放在**仓库外的工作区**（`%WORKSPACE%/tools/`），
它不属于产品源码，故不在本仓库内。

## 校验（下载后）

```bash
# 1) 哈希
sha256sum family-wealth-app-vX.Y.Z.apk

# 2) 查包内真实版本 —— APK 是压缩包，直接 grep 包内字符串**查不到**版本号
#    （AndroidManifest.xml 被 deflate 压缩），必须用 aapt：
aapt2 dump badging family-wealth-app-vX.Y.Z.apk | head -1
# 或读构建元数据：frontend/android/app/build/outputs/apk/debug/output-metadata.json
```

## 安装

覆盖安装即可保留数据（同包名 `com.family.wealth`、签名一致）。首次安装需在系统设置里允许「安装未知来源应用」。

## 服务器地址

APK **不注入**任何 API 地址：地址由登录页运行时配置（localStorage `fw_server`，
优先级高于构建时注入）。换 NAS、换网络、换端口都不需要重新打包。

## 本目录为什么还在 git 里

只保留这份 `README.md`：说明 APK 去哪拿、怎么构建、怎么发布，并让
`check/check_tar.py` 的「必备文件」校验有一个稳定的锚点。
`apk/*.apk` 已在 `.gitignore` 中忽略，防止误提交。

历史包袱说明：**v1.7.9 的 APK 仍在 git 历史里**（commit `0f4866b`），无法回收。
如需取回，可用 `git show 0f4866b:apk/family-wealth-app-v1.7.9.apk > 1.7.9.apk`。
