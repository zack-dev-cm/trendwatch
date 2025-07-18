from fastmcp import FastMCP
import os
import pandas as pd
import textwrap
from fastapi import Request, HTTPException
from fastapi.staticfiles import StaticFiles

DATA_PATH = os.getenv("DATA_PATH", "/data/trendwatch.parquet")


def _generate_sample_df(path: str) -> pd.DataFrame:
    """Create a tiny placeholder dataset and save it to ``path``."""
    data = [
        {
            "video_id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "description": "Classic hit used as example data.",
            "captions": "We're no strangers to love...",
            "publish_dt": "1987-07-27T00:00:00+00:00",
            "views": 1000000,
            "likes": 50000,
            "virality_score": 123.4,
            "topic": "example",
            "catchy_factors": "classic; catchy tune",
        },
        {
            "video_id": "2vjPBrBU-TM",
            "title": "Chandelier",
            "description": "Another demo record for testing.",
            "captions": "Party girls don't get hurt...",
            "publish_dt": "2014-03-06T00:00:00+00:00",
            "views": 2000000,
            "likes": 150000,
            "virality_score": 456.7,
            "topic": "demo",
            "catchy_factors": "dance; pop",
        },
        {
            "video_id": "kJQP7kiw5Fk",
            "title": "Despacito",
            "description": "Third sample video entry.",
            "captions": "Ay Fonsi...",
            "publish_dt": "2017-01-12T00:00:00+00:00",
            "views": 5000000,
            "likes": 300000,
            "virality_score": 789.0,
            "topic": "latin",
            "catchy_factors": "viral; upbeat",
        },
    ]
    df = pd.DataFrame(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path, index=False)
    return df


if os.path.exists(DATA_PATH):
    _df = pd.read_parquet(DATA_PATH)
else:
    _df = _generate_sample_df(DATA_PATH)
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
