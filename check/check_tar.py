# -*- coding: utf-8 -*-
"""部署包（family-wealth.tar.gz）打包与校验。

这个脚本同时是「打包配方」和「打包校验」，两者用同一份排除规则，避免
「按 A 规则打包、按 B 规则检查」这种假通过。用 --out 指定路径即产出真实交付物。

历史上被这份规则挡掉的坑（写在这里免得再犯）：
  · .git 未排除 —— 项目入 git 后包体从 376KB 涨到 862KB、多 369 个条目；
  · 安卓产物写成具体层级（frontend/android/assets/public*）匹配不上 ——
    Capacitor 真实路径是 frontend/android/**app/src/main/assets/**public*，
    含 public_old_* 历史备份，7 份构建产物全被打进包（曾得 8MB，正常 410KB）；
  · APK 入库后会被一起打进去（12.6MB）—— 已单独排除，APK 走 Release 附件。

校验项：
  1. 顶层只有一个目录 family-wealth/；
  2. 无 .git / node_modules / dist / data / __pycache__ / *.pyc / screenshots /
     assets/public* / *.apk / *.tar.gz；
  3. 包体积在合理区间，且不存在单文件 > 1MB；
  4. 包内 backend/app/main.py 的 VERSION == 工作区 VERSION；
  5. 必备文件齐备（后端/前端源、Dockerfile、compose、README、tests、check）。

用法：
  python check/check_tar.py                      # 打包到临时文件并校验
  python check/check_tar.py --out ../family-wealth.tar.gz   # 产出真实部署包
"""
import argparse
import io
import os
import re
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "family-wealth"

MIN_BYTES, MAX_BYTES = 250 * 1024, 1024 * 1024
WARN_LOW, WARN_HIGH = 350 * 1024, 500 * 1024

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


# ----------------------------------------------------------------------------
# 排除规则（打包与校验共用）
# ----------------------------------------------------------------------------
def excluded(rel):
    """rel 为仓库内的 POSIX 相对路径。返回 True 表示不进包。"""
    parts = rel.split("/")
    name = parts[-1]

    if {"__pycache__", ".git", ".idea", ".vscode", ".venv", "venv"} & set(parts):
        return True
    if parts[0] in ("data", "screenshots", "node_modules"):
        return True
    if len(parts) >= 2 and parts[0] == "frontend" and parts[1] in ("node_modules", "dist"):
        return True
    if len(parts) >= 3 and parts[0] == "frontend" and parts[1] == "android" \
            and parts[2] in ("build", ".gradle", ".kotlin"):
        return True
    if len(parts) >= 4 and parts[:4] == ["frontend", "android", "app", "build"]:
        return True
    # 安卓 Capacitor 产物：.../main/assets/public 与 .../main/assets/public_old_*
    if "assets" in parts:
        i = parts.index("assets")
        if i + 1 < len(parts) and parts[i + 1].startswith("public"):
            return True
    if name.endswith((".pyc", ".pyo", ".log", ".tar", ".tgz", ".tar.gz")):
        return True
    if parts[0] == "apk" and name.lower().endswith(".apk"):
        return True
    return False


def collect():
    """返回 [(abs_path, arc_rel_path)]，已按规则过滤且按路径排序。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = sorted(
            d for d in dirnames
            if not excluded((rel_dir + "/" + d).lstrip("/"))
        )
        for fn in sorted(filenames):
            rel = (rel_dir + "/" + fn).lstrip("/")
            if excluded(rel):
                continue
            out.append((os.path.join(dirpath, fn), rel))
    return out


def build(out_path):
    files = collect()
    with tarfile.open(out_path, "w:gz") as tf:
        for abs_path, rel in files:
            ti = tf.gettarinfo(abs_path, arcname="%s/%s" % (TOP, rel))
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = 0
            with open(abs_path, "rb") as fh:
                tf.addfile(ti, fh)
    return files


# ----------------------------------------------------------------------------
section("[1] 打包")
parser = argparse.ArgumentParser()
parser.add_argument("--out", default=None)
args = parser.parse_args()

tmp_holder = None
if args.out:
    out_path = os.path.abspath(args.out)
    print("       输出：%s" % out_path)
else:
    tmp_holder = tempfile.mkdtemp(prefix="fw_tarcheck_")
    out_path = os.path.join(tmp_holder, "family-wealth.tar.gz")
    print("       输出：临时文件（未指定 --out）")

files = build(out_path)
size = os.path.getsize(out_path)
print("       入包文件 %d 个，体积 %d 字节（%.1f KB）" % (len(files), size, size / 1024.0))
check("归档已生成且非空", size > 0)

section("[2] 顶层结构")
with tarfile.open(out_path, "r:gz") as tf:
    names = tf.getnames()
    members = tf.getmembers()

tops = sorted({n.split("/")[0] for n in names})
check("顶层只有一个目录 %s/" % TOP, tops == [TOP], "实际 %r" % tops)

section("[3] 排除项（不该出现在包里的东西）")
forbidden = [
    ("含 .git", lambda p: "/.git/" in "/%s/" % p or p.startswith(".git/")),
    ("含 node_modules", lambda p: "/node_modules/" in "/%s/" % p),
    ("含 frontend/dist", lambda p: "/frontend/dist/" in "/%s/" % p),
    ("含顶层 data/（用户财务数据）", lambda p: "/data/" in "/%s/" % p[1:]),
    ("含 __pycache__", lambda p: "/__pycache__/" in "/%s/" % p),
    ("含 .pyc", lambda p: p.endswith(".pyc")),
    ("含 screenshots", lambda p: "/screenshots/" in "/%s/" % p),
    ("含安卓 assets/public* 产物", lambda p: re.search(r"/assets/public", p) is not None),
    ("含 .apk 安装包", lambda p: p.lower().endswith(".apk")),
    ("含 *.tar.gz（自包含）", lambda p: p.endswith((".tar.gz", ".tgz"))),
]
for label, pred in forbidden:
    hits = [n for n in names if pred(n)]
    check("不%s" % label, not hits, "命中 %d 个，例如 %s" % (len(hits), hits[:3]))

section("[4] 体积与最大文件")
check("体积在 %.0fKB–%.0fKB 之间" % (MIN_BYTES / 1024, MAX_BYTES / 1024),
      MIN_BYTES <= size <= MAX_BYTES, "实际 %.1f KB" % (size / 1024.0))
if not (WARN_LOW <= size <= WARN_HIGH):
    warn("体积偏离常规区间 %.0f–%.0f KB" % (WARN_LOW / 1024, WARN_HIGH / 1024),
         "实际 %.1f KB —— 正常包约 380–420 KB，请确认是否漏排除" % (size / 1024.0))

blobs = [m for m in members if m.isfile()]
big = sorted(blobs, key=lambda m: -m.size)[:10]
biggest = big[0] if big else None
check("无单文件超过 1 MB", biggest is None or biggest.size <= 1024 * 1024,
      "最大 %s (%.0f KB)" % (biggest.name, biggest.size / 1024.0) if biggest else "")
print("       包内最大 5 个文件：")
for m in big[:5]:
    print("         %8.1f KB  %s" % (m.size / 1024.0, m.name))

section("[5] 必备文件与版本一致性")
required = [
    "backend/app/main.py",
    "backend/app/models.py",
    "backend/app/seed.py",
    "backend/requirements.txt",
    "frontend/package.json",
    "frontend/src/App.jsx",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.local.yml",
    "README.md",
    "check/check_version.py",
    "check/check_compose.py",
    "check/check_tar.py",
    "apk/README.md",
]
for rel in required:
    check("含 %s" % rel, ("%s/%s" % (TOP, rel)) in names)
check("含后端回归测试目录 backend/tests",
      any(n.startswith("%s/backend/tests/" % TOP) for n in names))

workspace_main = os.path.join(ROOT, "backend", "app", "main.py")
with open(workspace_main, encoding="utf-8") as fh:
    ws_ver = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
ws_ver = ws_ver.group(1) if ws_ver else ""

packed_ver = ""
with tarfile.open(out_path, "r:gz") as tf:
    try:
        data = tf.extractfile("%s/backend/app/main.py" % TOP).read().decode("utf-8")
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', data, re.M)
        packed_ver = m.group(1) if m else ""
    except Exception as exc:  # noqa: BLE001
        packed_ver = "读取失败: %s" % exc

check("包内 VERSION 与工作区一致", bool(ws_ver) and packed_ver == ws_ver,
      "包内 %r / 工作区 %r" % (packed_ver, ws_ver))
print("       VERSION = %s" % ws_ver)

# 抽验：包内 main.py 与工作区文件逐字节一致（防「打包时文件被改」）
with tarfile.open(out_path, "r:gz") as tf:
    a = tf.extractfile("%s/backend/app/main.py" % TOP).read()
with open(workspace_main, "rb") as fh:
    b = fh.read()
check("包内 main.py 与工作区逐字节一致", a == b, "%d vs %d 字节" % (len(a), len(b)))

section("[6] 条目数量")
check("文件数在 80–400 之间", 80 <= len(blobs) <= 400, "实际 %d" % len(blobs))

print()
print("=" * 68)
if args.out:
    print("部署包已产出：%s（%.1f KB）" % (out_path, size / 1024.0))
if _warns:
    print("软提示 %d 条：" % len(_warns))
    for x in _warns:
        print("  - %s" % x)
if _fails:
    print("结果：%d 项检查，%d 项失败" % (_checks, len(_fails)))
    for x in _fails:
        print("  ✗ %s" % x)
    if tmp_holder:
        import shutil

        shutil.rmtree(tmp_holder, ignore_errors=True)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅" % _checks)
if tmp_holder:
    import shutil

    shutil.rmtree(tmp_holder, ignore_errors=True)
