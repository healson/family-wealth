"""使用手册：返回渲染后的 README HTML，供页面内直接阅读"""
from pathlib import Path

import markdown
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/docs", tags=["使用手册"])

_README_STYLE = """
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2329; background: #fff; margin: 0; padding: 24px 32px 64px; line-height: 1.7; }
  h1 { font-size: 24px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
  h2 { font-size: 20px; margin-top: 32px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
  h3 { font-size: 17px; margin-top: 24px; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th, td { border: 1px solid #e5e6eb; padding: 8px 10px; text-align: left; font-size: 14px; }
  th { background: #f7f8fa; }
  tr:nth-child(even) td { background: #fafbfc; }
  code { background: #f2f3f5; padding: 2px 5px; border-radius: 3px; font-size: 13px; }
  pre { background: #f6f8fa; padding: 12px 16px; border-radius: 6px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  blockquote { margin: 0; padding: 8px 16px; border-left: 4px solid #d0d7de; color: #57606a; background: #f6f8fa; }
  a { color: #1677ff; }
  hr { border: none; border-top: 1px solid #eee; margin: 24px 0; }
  ul, ol { padding-left: 24px; }
"""


def _find_readme() -> Path | None:
    """定位 README.md（多路径兜底）：
    - 容器内：/app/README.md（Dockerfile 已 COPY README.md ./）
    - 本地开发：backend/../README.md（项目根）
    - 兜底：后端目录等
    """
    here = Path(__file__).resolve()  # backend/app/routers/docs.py
    candidates = [
        here.parents[2],            # /app（容器）或 backend（本地）
        here.parents[3],            # 项目根（本地）
        here.parents[1],            # backend/app
        Path("/app"),
    ]
    for parent in candidates:
        candidate = parent / "README.md"
        if candidate.is_file():
            return candidate
    return None


@router.get("/readme")
def readme():
    path = _find_readme()
    if path is None:
        return JSONResponse({"title": "使用手册", "html": "<p>未找到 README.md</p>"})
    md_text = path.read_text(encoding="utf-8")
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    html = (
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        f"<style>{_README_STYLE}</style></head><body>{body}</body></html>"
    )
    return JSONResponse({"title": "使用手册", "html": html})
