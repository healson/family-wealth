# -*- coding: utf-8 -*-
"""版本号一致性校验 —— 单一事实源 = backend/app/main.py 的 VERSION。

硬检查（任一失败即 exit 1）：
  1. main.py 里的 VERSION 存在且形如 x.y.z；
  2. README.md「版本历史」表格首行 = 本版本且标注「（当前）」；
  3. 安卓 app/build.gradle 是「构建时读取 backend/app/main.py」而不是写死版本号；
  4. apk/ 下若存在 *.apk，其文件名版本必须等于 VERSION
     （新策略下 APK 走 Release 附件，本目录通常已无 apk 文件）。

软检查（只提示，不影响退出码）：
  5. frontend/package.json 的 version —— 约定上版本号只在 main.py 与 README 两处递增，
     前端版本不参与运行时展示（前端显示的是 /api/health 返回的 VERSION），故不一致仅提示；
  6. 各 compose 注释里「想固定版本改用 :x.y.z」的示例版本是否已同步。

用法：python check/check_version.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fails, _warns, _checks = [], [], 0


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print("  [OK]   %s" % name)
    else:
        print("  [FAIL] %s%s" % (name, ("  -> %s" % detail) if detail else ""))
        _fails.append(name)


def warn(name, detail=""):
    print("  [WARN] %s%s" % (name, ("  -> %s" % detail) if detail else ""))
    _warns.append(name)


def section(title):
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

section("[1] 单一事实源：backend/app/main.py 的 VERSION")
main_py = read("backend/app/main.py")
check("backend/app/main.py 存在", main_py is not None)
version = ""
if main_py:
    m = VERSION_RE.search(main_py)
    check("能解析出 VERSION 常量", m is not None, "未匹配到 /^VERSION\\s*=\\s*\"([^\"]+)\"/m")
    if m:
        version = m.group(1)
        print("        VERSION = %s" % version)
        check("VERSION 形如 x.y.z", bool(SEMVER_RE.match(version)), version)
        check(
            "/api/health 直接返回该常量（不是另写一份）",
            re.search(r'"version"\s*:\s*VERSION', main_py) is not None,
            "health 端点未直接引用 VERSION（可能又写了一份版本号字面量）",
        )

if not version:
    print()
    print("VERSION 解析失败，后续检查无法进行。")
    sys.exit(1)

section("[2] README.md「版本历史」首行")
readme = read("README.md")
check("README.md 存在", readme is not None)
if readme:
    head = readme.find("## 📌 版本历史")
    check("存在「📌 版本历史」章节", head >= 0)
    if head >= 0:
        rows = [ln for ln in readme[head:].splitlines() if ln.strip().startswith("|")]
        data_rows = [ln for ln in rows if "---" not in ln and "版本" not in ln.split("|")[1]]
        check("版本历史表格有数据行", len(data_rows) > 0)
        if data_rows:
            first = data_rows[0]
            cells = [c.strip() for c in first.strip().strip("|").split("|")]
            ver_cell = cells[0] if cells else ""
            check(
                "首行是本版本 v%s" % version,
                ("v%s" % version) in ver_cell,
                "首行版本列为 %r" % ver_cell,
            )
            check(
                "首行标注「（当前）」",
                "当前" in ver_cell,
                "首行版本列为 %r（旧版本应去掉「当前」标注）" % ver_cell,
            )
            stale = [
                ln for ln in data_rows[1:]
                if "（当前）" in ln or "(当前)" in ln
            ]
            check("除首行外没有其它行标注「（当前）」", not stale, str(len(stale)) + " 行仍标当前")
        # 同版本号不应在表格里出现两次
        dup = len(re.findall(r"v%s" % re.escape(version), readme))
        print("        提示：README 中 v%s 共出现 %d 次" % (version, dup))

section("[3] 安卓端：版本号必须构建时读取，不得写死")


def strip_gradle_comments(src):
    """去掉 // 行注释与 /* */ 块注释。

    必要：本文件里有一句说明性注释写着「此前这里是写死的 versionCode 1 /
    versionName "1.0"」，若不剥注释，检查会被自己的说明文字误判为「存在写死版本」。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


gradle_raw = read("frontend/android/app/build.gradle")
check("frontend/android/app/build.gradle 存在", gradle_raw is not None)
if gradle_raw:
    gradle = strip_gradle_comments(gradle_raw)
    check(
        "通过 rootProject.file() 指向 backend/app/main.py",
        "rootProject.file(" in gradle and "backend/app/main.py" in gradle,
        "未引用后端 VERSION 文件",
    )
    check(
        "从 main.py 文本里正则解析 VERSION",
        "=~" in gradle and "VERSION" in gradle,
        "未见解析 VERSION 的正则",
    )
    check(
        "versionName 引用变量而非字面量",
        re.search(r"versionName\s+fwVersion\b", gradle) is not None
        and re.search(r'versionName\s+["\']', gradle) is None,
        "存在写死的 versionName（代码里不该出现字面版本号）",
    )
    check(
        "versionCode 引用变量而非字面量",
        re.search(r"versionCode\s+fwVersionCode\b", gradle) is not None
        and re.search(r"versionCode\s+[\"'\d]", gradle) is None,
        "存在写死的 versionCode（代码里不该出现字面数字）",
    )
    check(
        "versionCode 换算规则为 X*10000+Y*100+Z",
        re.search(r"\*\s*10000\s*\+\s*.*\*\s*100\s*\+", gradle) is not None,
        "未找到 versionCode 换算公式",
    )

section("[4] apk/ 目录（新策略：APK 走 Release 附件，此处应为空）")
apk_dir = os.path.join(ROOT, "apk")
apks = []
if os.path.isdir(apk_dir):
    apks = sorted(f for f in os.listdir(apk_dir) if f.lower().endswith(".apk"))
check("apk/README.md 存在（说明 APK 分发策略）", os.path.isfile(os.path.join(apk_dir, "README.md")))
if apks:
    print("        apk/ 下存在 %d 个安装包：%s" % (len(apks), ", ".join(apks)))
    for name in apks:
        m = re.search(r"-v(\d+\.\d+\.\d+)\.apk$", name)
        check(
            "%s 版本与 VERSION 一致" % name,
            bool(m) and m.group(1) == version,
            "文件名版本 %s != VERSION %s" % (m.group(1) if m else "?", version),
        )
else:
    print("        apk/ 下无安装包（符合当前策略：APK 只在 Release 附件里提供）")

section("[5] 软检查：frontend/package.json 版本")
pkg = read("frontend/package.json")
if pkg:
    m = re.search(r'"version"\s*:\s*"([^"]+)"', pkg)
    fe_ver = m.group(1) if m else "?"
    if fe_ver == version:
        print("        frontend/package.json version = %s（与后端一致）" % fe_ver)
    else:
        warn(
            "frontend/package.json version 与后端不一致",
            "前端 %s / 后端 %s —— 前端版本不参与运行时展示，不影响功能；"
            "若要消除提示可手动同步" % (fe_ver, version),
        )
else:
    warn("未找到 frontend/package.json")

section("[6] 软检查：compose 注释里的「固定版本」示例")
for rel in ("docker-compose.yml", "docker-compose.local.yml", "nas-deploy/docker-compose.yml"):
    text = read(rel)
    if text is None:
        continue
    for m in re.finditer(r":(\d+\.\d+\.\d+)(?![0-9.])", text):
        if m.group(1) != version:
            warn(
                "%s 里的固定版本示例过期" % rel,
                "写的是 :%s，当前版本 :%s" % (m.group(1), version),
            )

print()
print("=" * 68)
if _warns:
    print("软提示 %d 条（不影响结果）：" % len(_warns))
    for x in _warns:
        print("  - %s" % x)
if _fails:
    print("结果：%d 项检查，%d 项失败" % (_checks, len(_fails)))
    for x in _fails:
        print("  ✗ %s" % x)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅  （版本 %s）" % (_checks, version))
