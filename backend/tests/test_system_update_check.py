# -*- coding: utf-8 -*-
"""「检查更新」接口回归测试（v1.8.0）

新增 `GET /api/system/update-check`，配套校验四件事：

  1. **只读性**：接口只返回信息，不触发任何更新动作（不会去拉镜像 / 重启容器）；
  2. **版本比较**：远端高于本地 → 有更新；等于 / 低于 / 无法解析 → 无更新或无法判断；
  3. **优雅降级**：未配置来源、清单读不到、令牌无效 —— 一律返回 200 + 明确说明，
     而不是 500 或空白页（这样前端能给出可操作的提示）；
  4. **不泄露令牌**：响应里任何位置都不得出现 GITHUB_TOKEN 的值。

用本地起的 HTTP 服务当更新清单，因此不依赖外网就能覆盖「有更新 / 无更新 / 坏清单」
三条主路径。
"""
import http.server
import json
import os
import sys
import tempfile
import threading

TMP = tempfile.mkdtemp(prefix="fw_update_check_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["TZ"] = "Asia/Shanghai"
# 让 httpx 不要把我们本地起的 127.0.0.1 清单服务走代理
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import VERSION, app  # noqa: E402
from app.routers.system import _safe  # noqa: E402
from app.seed import init_db  # noqa: E402

_db = SessionLocal()
try:
    init_db(_db)
finally:
    _db.close()

client = TestClient(app)
_login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
assert _login.status_code == 200, _login.text
H = {"Authorization": "Bearer %s" % _login.json()["token"]}

_fails = []
_checks = 0

FAKE_TOKEN = "ghp_THIS_IS_A_FAKE_TOKEN_FOR_TEST_0123456789"
_env_keys = ("UPDATE_CHECK_MANIFEST_URL", "GITHUB_TOKEN", "GH_TOKEN", "UPDATE_CHECK_REPO")


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  -> %s" % (name, detail))
        _fails.append("%s: %s" % (name, detail))


def section(t):
    print()
    print("=" * 68)
    print(t)
    print("=" * 68)


def set_env(**kw):
    """kw 里值为 None 表示删除该环境变量。"""
    for k in _env_keys:
        os.environ.pop(k, None)
    for k, v in kw.items():
        if v is not None:
            os.environ[k] = v


def call(force=True):
    r = client.get("/api/system/update-check", headers=H,
                   params={"force": 1} if force else {})
    assert r.status_code == 200, "HTTP %s: %s" % (r.status_code, r.text[:300])
    return r.json()


def parse_ver(v):
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------------------
# 本地更新清单服务
# ---------------------------------------------------------------------------
class _ManifestHandler(http.server.BaseHTTPRequestHandler):
    payload = {"version": "0.0.0"}
    status = 200
    raw_body = None

    def do_GET(self):  # noqa: N802
        cls = type(self)
        body = cls.raw_body if cls.raw_body is not None else json.dumps(cls.payload).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(cls.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音访问日志
        pass


_server = http.server.HTTPServer(("127.0.0.1", 0), _ManifestHandler)
_port = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()
MANIFEST_URL = "http://127.0.0.1:%d/version.json" % _port

_major, _minor, _patch = parse_ver(VERSION)
HIGHER = "%d.%d.%d" % (_major, _minor + 1, 0)
LOWER = "%d.%d.%d" % (_major, _minor - 1 if _minor > 0 else 0, 0)

section("[1] 基本形状与只读性")
set_env()
r = client.get("/api/system/update-check", headers=H, params={"force": 1})
check("GET /api/system/update-check -> 200", r.status_code == 200, r.text[:200])
d = r.json()
check("current == 后端 VERSION", d.get("current") == VERSION, "%r vs %r" % (d.get("current"), VERSION))
check("返回 upgrade_command 且是 pull && up -d",
      isinstance(d.get("upgrade_command"), str) and "pull" in d["upgrade_command"]
      and "up -d" in d["upgrade_command"], str(d.get("upgrade_command")))
check("返回 checked_at", bool(d.get("checked_at")), str(d.get("checked_at")))
check("update_available 是 bool 或 None",
      d.get("update_available") is None or isinstance(d.get("update_available"), bool),
      repr(d.get("update_available")))
check("不含任何「自动更新」相关字段（只读，不触发动作）",
      not any(k in d for k in ("auto_update", "restart", "applied", "pulled")), str(sorted(d)))

section("[2] 未配置来源 → 明确降级，不报错")
set_env()
d = call()
check("source == 'none'", d.get("source") == "none", str(d.get("source")))
check("update_available is None", d.get("update_available") is None, repr(d.get("update_available")))
check("note 说明了如何启用检查", "UPDATE_CHECK_MANIFEST_URL" in d.get("note", ""),
      d.get("note", "")[:120])
check("note 里给了手动升级命令", "pull" in d.get("note", ""), d.get("note", "")[:120])

section("[3] 清单版本高于本地 → 有更新")
_ManifestHandler.status = 200
_ManifestHandler.raw_body = None
_ManifestHandler.payload = {"version": HIGHER, "url": "https://example.com/releases", "name": "test"}
set_env(UPDATE_CHECK_MANIFEST_URL=MANIFEST_URL)
d = call()
check("source == 'manifest'", d.get("source") == "manifest", str(d.get("source")))
check("latest == %s" % HIGHER, d.get("latest") == HIGHER, str(d.get("latest")))
check("update_available is True", d.get("update_available") is True, repr(d.get("update_available")))
check("note 提示有新版本", "新版本" in d.get("note", ""), d.get("note", "")[:140])
check("html_url 透传自清单", d.get("html_url") == "https://example.com/releases", str(d.get("html_url")))

section("[4] 清单版本等于本地 → 无更新")
_ManifestHandler.payload = {"version": VERSION}
d = call()
check("update_available is False", d.get("update_available") is False, repr(d.get("update_available")))
check("note 说明已是最新", "最新版本" in d.get("note", ""), d.get("note", "")[:140])

section("[5] 清单版本低于本地 → 无更新（不回退）")
_ManifestHandler.payload = {"version": LOWER}
d = call()
check("update_available is False", d.get("update_available") is False, repr(d.get("update_available")))

section("[6] 清单带 v 前缀 / 带后缀也能解析")
_ManifestHandler.payload = {"version": "v%s" % HIGHER}
d = call()
check("'v%s' 解析为 %s" % (HIGHER, HIGHER), d.get("latest") == HIGHER, str(d.get("latest")))
check("'v%s' 的 latest_tag 保留原串" % HIGHER, d.get("latest_tag") == "v%s" % HIGHER,
      str(d.get("latest_tag")))
_ManifestHandler.payload = {"version": "%s-beta.1" % HIGHER}
d = call()
check("'%s-beta.1' 的 latest 归一化为 %s" % (HIGHER, HIGHER), d.get("latest") == HIGHER,
      str(d.get("latest")))
check("latest_tag 保留 '%s-beta.1'" % HIGHER, d.get("latest_tag") == "%s-beta.1" % HIGHER,
      str(d.get("latest_tag")))
check("note 如实标注带后缀（不误导成正式版）",
      d.get("update_available") is True and "beta" in d.get("note", ""), d.get("note", "")[:160])
_ManifestHandler.payload = {"version": HIGHER}
d = call()
check("无后缀时 note 不出现多余标注", "（来源标记为" not in d.get("note", ""), d.get("note", "")[:160])

section("[7] 坏清单 / 不可达 → 降级但不 500")
_ManifestHandler.payload = {"version": "not-a-version"}
d = call()
check("版本号非法 → source 'none'", d.get("source") == "none", str(d.get("source")))
check("版本号非法 → note 含「读取失败」", "读取失败" in d.get("note", ""), d.get("note", "")[:140])

_ManifestHandler.raw_body = b"{ this is not json"
d = call()
check("非 JSON 响应 → source 'none'", d.get("source") == "none", str(d.get("source")))
_ManifestHandler.raw_body = None

_ManifestHandler.status = 500
d = call()
check("HTTP 500 → source 'none'", d.get("source") == "none", str(d.get("source")))
_ManifestHandler.status = 200

set_env(UPDATE_CHECK_MANIFEST_URL="http://127.0.0.1:%d/nothing-here" % _port)
d = call()
check("404 路径 → source 'none'", d.get("source") == "none", str(d.get("source")))

section("[8] 无效令牌 / 不存在的仓库 → 降级")
set_env(GITHUB_TOKEN=FAKE_TOKEN, UPDATE_CHECK_REPO="healson/__definitely_nonexistent_repo__")
d = call()
check("source 回落到 'none'", d.get("source") == "none", str(d.get("source")))
check("note 提到查询失败", "查询失败" in d.get("note", ""), d.get("note", "")[:140])

section("[9] 令牌绝不泄露")
blob = json.dumps(d, ensure_ascii=False)
check("响应体不含令牌明文", FAKE_TOKEN not in blob, "note 里出现了令牌")
check("响应体不含 'ghp_' 前缀片段", "ghp_" not in blob, "note 里出现了 ghp_ 片段")
raw = client.get("/api/system/update-check", headers=H, params={"force": 1}).text
check("原始响应文本不含令牌", FAKE_TOKEN not in raw, raw[:200])
masked = _safe(RuntimeError("请求失败，使用的令牌是 %s，请检查" % FAKE_TOKEN))
check("_safe() 会把异常里的令牌替换成 ***", FAKE_TOKEN not in masked and "***" in masked, masked[:160])

section("[10] 缓存行为")
set_env(UPDATE_CHECK_MANIFEST_URL=MANIFEST_URL)
_ManifestHandler.payload = {"version": HIGHER}
first = call(force=True)
second = call(force=False)
check("首次查询 cached=False", first.get("cached") is False, repr(first.get("cached")))
check("紧随其后的查询命中缓存 cached=True", second.get("cached") is True, repr(second.get("cached")))
check("缓存命中时数据一致", second.get("latest") == first.get("latest"), "%r vs %r" % (second.get("latest"), first.get("latest")))
_ManifestHandler.payload = {"version": LOWER}
third = call(force=True)
check("force=1 绕过缓存拿到新结果", third.get("cached") is False and third.get("update_available") is False,
      "cached=%r available=%r" % (third.get("cached"), third.get("update_available")))

section("[11] 鉴权与系统信息")
set_env()
r_anon = client.get("/api/system/update-check")
check("未登录访问 → 401", r_anon.status_code == 401, "%s" % r_anon.status_code)
r_info = client.get("/api/system/info", headers=H)
check("GET /api/system/info -> 200", r_info.status_code == 200, r_info.text[:200])
info = r_info.json()
check("info.version == VERSION", info.get("version") == VERSION, str(info.get("version")))
check("info.timezone 透传 TZ", info.get("timezone") == "Asia/Shanghai", str(info.get("timezone")))
check("未配置时 update_check_configured is False", info.get("update_check_configured") is False,
      repr(info.get("update_check_configured")))
set_env(UPDATE_CHECK_MANIFEST_URL=MANIFEST_URL)
info2 = client.get("/api/system/info", headers=H).json()
check("配置后 update_check_configured is True", info2.get("update_check_configured") is True,
      repr(info2.get("update_check_configured")))
check("/api/system/info 不含任何凭据字段",
      not any(k in json.dumps(info2) for k in ("TOKEN", "ghp_", "PASSWORD", "SECRET")),
      json.dumps(info2, ensure_ascii=False))

set_env()
_server.shutdown()

print()
print("=" * 68)
if _fails:
    print("结果：%d/%d 通过，%d 失败" % (_checks - len(_fails), _checks, len(_fails)))
    for x in _fails:
        print("  -", x)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅" % _checks)
