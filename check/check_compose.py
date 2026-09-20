# -*- coding: utf-8 -*-
"""compose 结构不变量校验。

为什么需要它：这三份 compose 里「服务名 / 端口 / 数据卷 / 环境变量键名 / 网段」是
部署契约，一旦被误改（手工替换 services 段、批量改注释、格式化重排）后果很重——
最典型的是数据卷 `./data:/data` 被改动或删掉，会让 NAS 上的 SQLite 数据库「消失」。
本脚本把这些不变量固化成断言，改注释可以，动结构就会失败。

校验文件（存在才查）：
  · docker-compose.yml         —— 从 GHCR 拉取预构建镜像（仓库内，不得含 build）
  · docker-compose.local.yml   —— 本地构建兜底（仓库内，必须有 build）
  · nas-deploy/docker-compose.yml —— 用户 NAS 上的副本（刻意放在仓库外，含真实凭据）

仓库内文件的额外安全检查：ADMIN_PASSWORD / JWT_SECRET 必须是占位值，
防止把真实凭据误提交进仓库。

依赖：PyYAML（pip install pyyaml）
用法：
  python check/check_compose.py                             # 只查仓库内两份
  python check/check_compose.py ../nas-deploy/docker-compose.yml
                                                            # 额外查用户 NAS 上那份副本
                                                            # （仓库外，含真实凭据，不查占位值）
"""
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("需要 PyYAML：pip install pyyaml")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRA = sys.argv[1:]

REMOTE = "docker-compose.yml"
LOCAL = "docker-compose.local.yml"
NAS = "nas-deploy/docker-compose.yml"

# 仓库内文件必须是占位凭据；仓库外的用户副本不查这一项
PLACEHOLDER_ADMIN = "admin123"
PLACEHOLDER_JWT = "please-change-me"

_fails, _checks = [], []


def check(name, cond, detail=""):
    _checks.append(name)
    if cond:
        print("  [OK]   %s" % name)
    else:
        print("  [FAIL] %s%s" % (name, ("  -> %s" % detail) if detail else ""))
        _fails.append(name)


def read_yaml(rel):
    path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return None, None
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        return yaml.safe_load(raw), raw
    except yaml.YAMLError as exc:
        return "PARSE_ERROR: %s" % exc, raw


def env_map(entries):
    """把 compose environment 列表/字典统一成 {key: value}，并剥掉行内 # 注释。"""
    out = {}
    if isinstance(entries, dict):
        for k, v in entries.items():
            out[str(k)] = str(v).split("#")[0].strip()
        return out
    for item in entries or []:
        if not isinstance(item, str) or "=" not in item:
            continue
        k, _, v = item.partition("=")
        out[k.strip()] = v.split("#")[0].strip()
    return out


def port_pairs(ports):
    """统一成 [(host_port, container_port)]。容器侧必须是 8000，宿主侧随意
    （仓库默认 8000，用户 NAS 上是 5888 —— 那是合法的个性化，不该判失败）。"""
    out = []
    for p in ports or []:
        if isinstance(p, dict):
            out.append((str(p.get("published", "")), str(p.get("target", ""))))
        else:
            s = str(p).split("#")[0].strip()
            host, _, cont = s.rpartition(":")
            out.append((host, cont))
    return out


def volume_items(volumes):
    out = []
    for v in volumes or []:
        if isinstance(v, dict):
            out.append("%s:%s" % (v.get("source", ""), v.get("target", "")))
        else:
            out.append(str(v).split("#")[0].strip())
    return out


def audit(rel, in_repo):
    label = rel if in_repo else "%s（仓库外，含真实凭据，不查占位值）" % rel
    print()
    print("=" * 68)
    print("检查 %s" % label)
    print("=" * 68)
    data, _raw = read_yaml(rel)
    if data is None:
        print("  文件不存在 —— 跳过")
        return
    if isinstance(data, str) and data.startswith("PARSE_ERROR"):
        check("%s 可被 YAML 解析" % os.path.basename(rel), False, data)
        return
    check("YAML 可解析", True)

    key = os.path.basename(rel)
    svc_all = (data or {}).get("services") or {}
    check("顶层有 services", bool(svc_all), "services 为空")
    svc = svc_all.get("family-wealth")
    check("存在服务 family-wealth", svc is not None, "实际服务名：%s" % list(svc_all))
    if svc is None:
        return

    # ---- 端口：必须恰好一条，且容器侧为 8000 ----
    ports = port_pairs(svc.get("ports"))
    check("ports 至少一条映射", len(ports) > 0, "ports=%r" % svc.get("ports"))
    check("容器侧端口必须是 8000", all(c == "8000" for _h, c in ports),
          "实际 %r" % (ports,))
    check("只暴露一个端口", len(ports) == 1, "实际 %d 条" % len(ports))

    # ---- 数据卷：绝对不能丢、不能改挂载点 ----
    vols = volume_items(svc.get("volumes"))
    check("volumes 含 ./data:/data（SQLite 数据持久化，丢了会丢账！）",
          "./data:/data" in vols, "实际 %r" % (vols,))

    # ---- 环境变量键名 ----
    env = env_map(svc.get("environment"))
    for key in ("ADMIN_PASSWORD", "JWT_SECRET", "TZ"):
        check("environment 含 %s" % key, key in env, "实际键：%s" % sorted(env))
    check("SEED_DEMO_DATA 键存在（新装体验开关）", "SEED_DEMO_DATA" in env)

    # ---- 容器名与重启策略 ----
    check("container_name = family-wealth", svc.get("container_name") == "family-wealth",
          "实际 %r" % svc.get("container_name"))
    check("restart 为 unless-stopped 或 always",
          svc.get("restart") in ("unless-stopped", "always"),
          "实际 %r" % svc.get("restart"))

    # ---- 健康检查 ----
    hc = svc.get("healthcheck") or {}
    check("定义了 healthcheck", bool(hc.get("test")), "无 healthcheck")
    if hc.get("test"):
        check("healthcheck 打的是 /api/health",
              "/api/health" in str(hc.get("test")), str(hc.get("test"))[:120])

    # ---- 镜像来源：仓库内两份语义相反 ----
    has_build = "build" in svc
    has_image = "image" in svc
    if key == REMOTE:
        check("有 image", has_image)
        check("不得含 build（这份是拉镜像版）", not has_build,
              "出现了 build: %r" % svc.get("build"))
        img = str(svc.get("image", ""))
        check("image 指向 ghcr.io/healson/family-wealth",
              img.startswith("ghcr.io/healson/family-wealth:"), "实际 %r" % img)
        tag = img.rpartition(":")[2]
        check("tag 是 latest / stable / 具体版本号之一",
              tag in ("latest", "stable") or bool(re.match(r"^\d+\.\d+\.\d+$", tag)),
              "实际 :%s" % tag)
    elif key == LOCAL:
        check("有 build（这份是本地构建版）", has_build, "缺少 build")
        if has_build:
            b = svc.get("build") or {}
            if isinstance(b, str):
                check("build.context = .", b == ".", "实际 %r" % b)
            else:
                check("build.context = .", b.get("context") == ".", "实际 %r" % b.get("context"))
                check("build.dockerfile = Dockerfile",
                      b.get("dockerfile") == "Dockerfile", "实际 %r" % b.get("dockerfile"))
    elif has_image:
        img = str(svc.get("image", ""))
        check("image 指向 ghcr.io/healson/family-wealth",
              img.startswith("ghcr.io/healson/family-wealth:"), "实际 %r" % img)

    # ---- 仓库内：凭据必须是占位值 ----
    if in_repo:
        check("ADMIN_PASSWORD 是占位值 %s（防真实密码入库）" % PLACEHOLDER_ADMIN,
              env.get("ADMIN_PASSWORD") == PLACEHOLDER_ADMIN,
              "实际 %r —— 真实密码不得提交进仓库！" % env.get("ADMIN_PASSWORD"))
        check("JWT_SECRET 是占位值 %s（防真实密钥入库）" % PLACEHOLDER_JWT,
              env.get("JWT_SECRET") == PLACEHOLDER_JWT,
              "实际 %r —— 真实密钥不得提交进仓库！" % env.get("JWT_SECRET"))

    # ---- 独立网段（若定义）----
    net = ((data or {}).get("networks") or {}).get("default") or {}
    cfg = ((net.get("ipam") or {}).get("config") or [])
    for i, c in enumerate(cfg):
        sn = str(c.get("subnet", ""))
        check("networks.default.ipam.config[%d].subnet 是合法 CIDR" % i,
              bool(re.match(r"^\d+\.\d+\.\d+\.\d+/\d{1,2}$", sn)), "实际 %r" % sn)


for _rel, _in_repo in ((REMOTE, True), (LOCAL, True), (NAS, False)):
    audit(_rel, _in_repo)
for _extra in EXTRA:
    audit(os.path.abspath(_extra), False)

print()
print("=" * 68)
if _fails:
    print("结果：%d 项检查，%d 项失败" % (len(_checks), len(_fails)))
    for x in _fails:
        print("  ✗ %s" % x)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅" % len(_checks))
