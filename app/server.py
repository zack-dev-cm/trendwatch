from fastmcp import FastMCP
import os
import pandas as pd
import textwrap
from fastapi import Request, HTTPException
from fastapi.staticfiles import StaticFiles

DATA_PATH = os.getenv("DATA_PATH", "/data/trendwatch.parquet")

if not os.path.exists(DATA_PATH):
    raise FileNotFoundError(f"DATA_PATH '{DATA_PATH}' does not exist")

_df = pd.read_parquet(DATA_PATH)
PORT = int(os.getenv("PORT", "8000"))
API_TOKEN = os.getenv("API_TOKEN", "")

mcp = FastMCP(
    name="YouTubeShortsTrendwatch",
    instructions="Trending YouTube Shorts corpus for deep research",
)


@mcp.app.middleware("http")
async def auth_header(request: Request, call_next):
    if API_TOKEN and request.headers.get("Authorization") != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "Unauthorized")
    return await call_next(request)


@mcp.tool()
async def search(query: str):
    mask = (_df.title.str.contains(query, case=False, na=False) | _df.description.str.contains(query, case=False, na=False))
    sub = _df[mask].head(20)
    return {"results": [
        {
            "id": r.video_id,
            "title": r.title,
            "text": textwrap.shorten(r.description, 140),
            "url": f"https://www.youtube.com/watch?v={r.video_id}",
        } for _, r in sub.iterrows()
    ]}


@mcp.tool()
async def fetch(id: str):
    sub = _df.loc[_df.video_id == id]
    if sub.empty:
        raise HTTPException(404, "Video not found")
    row = sub.iloc[0]
    return {
        "id": id,
        "title": row.title,
        "text": f"{row.description}\n\nCaptions:\n{row.captions}",
        "url": f"https://www.youtube.com/watch?v={id}",
        "metadata": {
            "publish_dt": row.publish_dt,
            "views": int(row.views),
            "likes": int(row.likes),
            "virality_score": float(row.virality_score),
            "topic": row.topic,
            "catchy": row.catchy_factors,
        },
    }

mcp.app.mount("/", StaticFiles(directory="app/ui", html=True), name="site")

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=PORT)
