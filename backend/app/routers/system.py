# -*- coding: utf-8 -*-
"""系统信息与更新检查。

设计原则：**只检查、只提示，绝不自动更新**。
本模块不会执行任何拉取镜像 / 重启容器 / 改文件的操作，只把「有没有新版本」
和「该怎么升级」告诉前端。自动更新需要把 docker socket 交给容器（等价于把
宿主机 root 权限交出去），对本项目「单人自用、部署在自家 NAS」的场景不值得。

更新来源有两种，按优先级：
  1. UPDATE_CHECK_MANIFEST_URL —— 任意公开 URL，返回 {"version": "x.y.z", ...}。
     适合「镜像私有 + 又不想在容器里放令牌」的情况（放个静态 JSON 即可）。
  2. GITHUB_TOKEN + UPDATE_CHECK_REPO —— 查 GitHub Releases API。
     仓库是私有的，所以必须带令牌（只需 repo 权限，或改为 public 后不需令牌）。

两者都没配时不做猜测：返回明确的「未配置来源」与启用说明，而不是报错。
"""
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user
from ..main import VERSION

router = APIRouter(
    prefix="/api/system",
    tags=["系统"],
    dependencies=[Depends(get_current_user)],
)

TIMEOUT = 8.0
CACHE_TTL = timedelta(minutes=10)
DEFAULT_REPO = "healson/family-wealth"

_cache = {"at": None, "data": None}

_UPGRADE_CMD = "docker compose pull && docker compose up -d"


def _repo():
    """每次调用时读环境变量（而不是模块导入时读一次），便于配置变更后立即生效。"""
    return (os.environ.get("UPDATE_CHECK_REPO") or "").strip() or DEFAULT_REPO


def _parse_ver(text):
    """把 x.y.z 解析成元组，非数字段按 0 处理。解析不出来返回 None。"""
    if not text:
        return None
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", str(text))
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _now():
    return datetime.now(timezone.utc)


def _result(**kw):
    base = {
        "current": VERSION,
        "latest": None,
        # 来源给出的原始 tag（如 "v1.8.0" 或 "1.8.0-beta.1"）；latest 是归一化后的 x.y.z
        "latest_tag": None,
        "update_available": None,
        "source": "none",
        "released_at": None,
        "html_url": None,
        "release_name": None,
        "note": "",
        "upgrade_command": _UPGRADE_CMD,
        "checked_at": _now().isoformat(timespec="seconds"),
    }
    base.update(kw)
    return base


def _norm(raw):
    """把来源给的版本串归一化成 x.y.z。

    latest 只保留前三段（用于比较与展示），原始串放在 latest_tag 里避免信息丢失 ——
    例如 1.8.0-beta.1 归一化后是 1.8.0，直接显示 latest 会让人以为正式版已经发了。
    解析不出来返回 None。
    """
    parsed = _parse_ver(raw)
    if not parsed:
        return None, None
    raw_str = str(raw or "").strip()
    return "%d.%d.%d" % parsed, (raw_str or None)


def _from_manifest(url):
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        payload = r.json()
    latest, latest_tag = _norm(payload.get("version"))
    if not latest:
        raise ValueError("清单里的 version 字段不是 x.y.z 形式：%r" % payload.get("version"))
    return _result(
        latest=latest,
        latest_tag=latest_tag,
        source="manifest",
        html_url=payload.get("url") or url,
        release_name=payload.get("name"),
        released_at=payload.get("released_at"),
    )


def _from_github(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "family-wealth-update-check",
    }
    if token:
        headers["Authorization"] = "Bearer %s" % token
    url = "https://api.github.com/repos/%s/releases/latest" % _repo()
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
        r = c.get(url, headers=headers)
        if r.status_code == 404:
            raise LookupError(
                "仓库不存在、没有任何 Release，或令牌无权访问（私有仓库需带 repo 权限的令牌）"
            )
        r.raise_for_status()
        d = r.json()
    latest, latest_tag = _norm(d.get("tag_name"))
    if not latest:
        raise ValueError("Release 的 tag 不是 vX.Y.Z 形式：%r" % d.get("tag_name"))
    return _result(
        latest=latest,
        latest_tag=latest_tag,
        source="github",
        html_url=d.get("html_url"),
        release_name=d.get("name"),
        released_at=d.get("published_at"),
    )


def _degrade(reason):
    return _result(
        source="none",
        note=(
            "%s\n"
            "启用检查的两种方式（任选其一）：\n"
            "① 公开清单：把 {\"version\": \"<最新版本号>\"} 放到任意可公开访问的 URL，"
            "然后给容器设置环境变量 UPDATE_CHECK_MANIFEST_URL=<该 URL>；\n"
            "② GitHub 令牌：给容器设置环境变量 GITHUB_TOKEN=<有 repo 权限的 PAT>，"
            "即可查询 %s 的 Releases（仓库是私有的，匿名查不到）。\n"
            "无论是否配置，都不影响正常使用；升级始终是手动执行：%s"
            % (reason, _repo(), _UPGRADE_CMD)
        ),
    )


def _fetch():
    url = (os.environ.get("UPDATE_CHECK_MANIFEST_URL") or "").strip()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()

    if url:
        try:
            return _from_manifest(url)
        except Exception as exc:  # noqa: BLE001
            return _degrade("已配置 UPDATE_CHECK_MANIFEST_URL，但读取失败：%s" % _safe(exc))
    if token:
        try:
            return _from_github(token)
        except Exception as exc:  # noqa: BLE001
            return _degrade("已配置 GITHUB_TOKEN，但查询失败：%s" % _safe(exc))
    return _degrade("未配置更新检查来源。")


def _safe(exc):
    """把异常转成可展示文本，并确保不泄露令牌。"""
    msg = "%s: %s" % (type(exc).__name__, exc)
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token and token in msg:
        msg = msg.replace(token, "***")
    return msg[:300]


def _finalize(data):
    cur = _parse_ver(VERSION)
    new = _parse_ver(data.get("latest"))
    if new is None or cur is None:
        data["update_available"] = None
        if not data.get("note"):
            data["note"] = "无法判断版本新旧（当前版本 %s）。" % VERSION
        return data
    available = new > cur
    data["update_available"] = available
    tag_note = ""
    if data.get("latest_tag") and data["latest_tag"] != data["latest"]:
        # 来源给的是 1.8.0-beta.1 这类带后缀的串，如实说明，避免误读为正式版已发
        tag_note = "（来源标记为 %s）" % data["latest_tag"]
    if available:
        data["note"] = (
            "发现新版本 v%s%s（当前 v%s）。升级：%s —— 数据在 ./data 里，不会丢。"
            % (data["latest"], tag_note, VERSION, _UPGRADE_CMD)
        )
    else:
        data["note"] = "已是最新版本（v%s）。" % VERSION
    return data


@router.get("/update-check")
def update_check(force: bool = Query(False, description="忽略缓存，强制重新查询")):
    """检查是否有新版本。只读、不触发任何更新动作。"""
    cached = _cache["data"]
    if not force and cached is not None and _cache["at"] is not None:
        if _now() - _cache["at"] < CACHE_TTL:
            out = dict(cached)
            out["cached"] = True
            return out
    data = _finalize(_fetch())
    _cache["at"] = _now()
    _cache["data"] = data
    out = dict(data)
    out["cached"] = False
    return out


@router.get("/info")
def system_info():
    """运行环境一览（排查用，不含任何密钥）。"""
    return {
        "version": VERSION,
        "timezone": os.environ.get("TZ") or "(未设置)",
        "data_dir": os.environ.get("DATA_DIR") or "(未设置)",
        "update_check_configured": bool(
            (os.environ.get("UPDATE_CHECK_MANIFEST_URL") or "").strip()
            or (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        ),
        "upgrade_command": _UPGRADE_CMD,
    }
