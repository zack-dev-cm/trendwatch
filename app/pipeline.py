import argparse
import base64
import datetime as dt
import html
import io
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from moviepy import VideoFileClip
from openai import OpenAI
from PIL import Image
from pytube import YouTube
from rich.console import Console
from rich.progress import Progress
from youtube_transcript_api import YouTubeTranscriptApi

# Optional resilient pytube fork
try:
    from pytubefix import YouTube as YTFix  # type: ignore
except ImportError:  # pragma: no cover - optional dep
    YTFix = None

DEFAULT_QUERY = "YouTube Shorts"
DEFAULT_DAYS_BACK = 10
DEFAULT_MAX_RESULTS = 50
MIN_VIEWS = 100_000
LIKE_RATIO_THRESHOLD = 0.9
FRAME_SAMPLES = 3
VISION_MODEL = "o3"
TEXT_MODEL = "o4-mini"

console = Console()


@dataclass
class Keys:
    youtube: str
    openai: str


def load_keys() -> Keys:
    """Load API keys from env or Colab userdata"""
    try:
        from google.colab import userdata

        yt = userdata.get("YOUTUBE_API_KEY")
        oa = userdata.get("OPENAI_API_KEY")
    except Exception:
        from dotenv import load_dotenv

        load_dotenv()
        yt = os.getenv("YOUTUBE_API_KEY")
        oa = os.getenv("OPENAI_API_KEY")
    if not yt or not oa:
        console.print("[bold red]❌ Missing API keys – set YOUTUBE_API_KEY & OPENAI_API_KEY[\n]")
        raise SystemExit(1)
    return Keys(yt, oa)


def yt_service(y_key: str):
    return build("youtube", "v3", developerKey=y_key)


def search_shorts(yt, q: str, days_back: int, max_items: int) -> List[str]:
    """Return video IDs for Shorts (<60s) sorted by viewCount."""
    published_after = (dt.datetime.utcnow() - dt.timedelta(days=days_back)).isoformat("T") + "Z"
    vids: List[str] = []
    next_tok = None
    while len(vids) < max_items:
        resp = (
            yt.search()
            .list(
                q=q,
                type="video",
                videoDuration="short",
                part="id",
                maxResults=min(50, max_items - len(vids)),
                publishedAfter=published_after,
                order="viewCount",
                pageToken=next_tok,
            )
            .execute()
        )
        vids += [i["id"]["videoId"] for i in resp["items"]]
        next_tok = resp.get("nextPageToken")
        if not next_tok:
            break
    return vids[:max_items]


def fetch_details(yt, ids: List[str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for chunk in [ids[i: i + 50] for i in range(0, len(ids), 50)]:
        data = yt.videos().list(id=",".join(chunk), part="snippet,statistics,contentDetails").execute()
        for item in data["items"]:
            stats = item.get("statistics", {})
            snip = item["snippet"]
            dur_iso = item["contentDetails"]["duration"]
            duration_sec = iso8601_duration_to_seconds(dur_iso)
            publish_dt = dt.datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            now_utc = dt.datetime.now(dt.timezone.utc)
            elapsed_days = (now_utc - publish_dt).days or 1
            rows.append(
                {
                    "video_id": item["id"],
                    "title": snip["title"],
                    "description": snip.get("description", ""),
                    "publish_dt": publish_dt.isoformat(),
                    "channel": snip.get("channelTitle", ""),
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "duration_sec": duration_sec,
                    "elapsed_days": elapsed_days,
                    "views_per_day": int(stats.get("viewCount", 0)) / elapsed_days,
                }
            )
    df = pd.DataFrame(rows)
    df["like_ratio"] = df["likes"] / (df["likes"] + 1e-6)
    return df


def iso8601_duration_to_seconds(d: str) -> int:
    import re

    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0
    h, m_, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + m_ * 60 + s


def try_captions(video_id: str) -> Optional[str]:
    try:
        tr = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        return "\n".join(c["text"] for c in tr)
    except Exception:
        return None


def try_api_captions(yt, video_id: str) -> Optional[str]:
    try:
        caps = yt.captions().list(videoId=video_id, part="id").execute()
        if not caps["items"]:
            return None
        track_id = caps["items"][0]["id"]
        body = yt.captions().download(id=track_id, tfmt="srt").execute()["body"]
        return body
    except HttpError:
        return None


def sample_frames(video_url: str, n: int = FRAME_SAMPLES) -> List[Image.Image]:
    try:
        yt_obj = (YTFix or YouTube)(video_url)
        stream = yt_obj.streams.filter(progressive=True, file_extension="mp4").first()
        if not stream:
            console.print(f"[yellow]⚠️ No progressive stream for {video_url}")
            return []
        tmp_path = stream.download(output_path=tempfile.gettempdir(), skip_existing=True)
        clip = VideoFileClip(tmp_path)
        dur = clip.duration
        frames = [Image.fromarray(clip.get_frame(dur * (i + 1) / (n + 1))) for i in range(n)]
        clip.close()
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        return frames
    except Exception as e:
        console.print(f"[yellow]⚠️ Frame sampling failed for {video_url}: {e}")
        return []


def ocr_frames(client: OpenAI, frames: List[Image.Image]) -> str:
    texts: List[str] = []
    for img in frames:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": "Extract all visible text and a short scene description (≤40 words)."},
                    ],
                }
            ],
        )
        texts.append(resp.choices[0].message.content.strip())
    return "\n".join(texts)


def analyze_text(client: OpenAI, text: str) -> Dict[str, str]:
    prompt = (
        "Read the captions & description below. Return two XML tags only:\n"
        "<topic> – main subject in ≤5 words\n"
        "<hooks> – concise list of virality hooks (≤40 chars each, ';'-separated)\n\n"
        "TEXT:\n" + text
    )
    resp = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    out = resp.choices[0].message.content
    import re

    topic = re.search(r"<topic>(.*?)</topic>", out, re.S)
    hooks = re.search(r"<hooks>(.*?)</hooks>", out, re.S)
    return {
        "topic": html.unescape(topic.group(1).strip()) if topic else "",
        "hooks": html.unescape(hooks.group(1).strip()) if hooks else "",
    }


def process_video(client: OpenAI, yt, vid: str, frame_samples: int = FRAME_SAMPLES) -> Dict[str, str]:
    caption = try_captions(vid) or try_api_captions(yt, vid)
    if not caption:
        frames = sample_frames(f"https://www.youtube.com/watch?v={vid}", frame_samples)
        if frames:
            caption = ocr_frames(client, frames)
    if not caption:
        caption = ""
    analysis = analyze_text(client, caption)
    return {"captions": caption, **analysis}


def virality_score(row: pd.Series) -> float:
    return row.views / 1_000 + row.likes + row.views_per_day * 0.1


def run_pipeline(
    OPENAI_API_KEY,
    YOUTUBE_API_KEY,
    query: str = DEFAULT_QUERY,
    days_back: int = DEFAULT_DAYS_BACK,
    max_results: int = DEFAULT_MAX_RESULTS,
    out_csv: str = "trendwatch_results.csv",
):
    client = OpenAI(api_key=OPENAI_API_KEY)
    yt = yt_service(YOUTUBE_API_KEY)

    console.print(f"[bold cyan]🔍 Searching for shorts: '{query}' (last {days_back} days)…")
    vids = search_shorts(yt, query, days_back, max_results)
    console.print(f"Found {len(vids)} potential shorts – fetching details…")
    details = fetch_details(yt, vids)
    console.print("Filtering by virality thresholds…")
    df = details[(details.views >= MIN_VIEWS) & (details.like_ratio >= LIKE_RATIO_THRESHOLD)].reset_index(drop=True)
    console.print(f"[green]✔ {len(df)} shorts pass the filter")

    captions: List[str] = []
    topics: List[str] = []
    hooks: List[str] = []

    with Progress() as progress:
        task = progress.add_task("Analyzing", total=len(df))
        for row in df.itertuples():
            pdata = process_video(client, yt, row.video_id)
            captions.append(pdata["captions"])
            topics.append(pdata["topic"])
            hooks.append(pdata["hooks"])
            progress.advance(task)

    df["captions"] = captions
    df["topic"] = topics
    df["catchy_factors"] = hooks
    df["virality_score"] = df.apply(virality_score, axis=1)

    df.to_csv(out_csv, index=False)
    console.print(f"[bold green]✅ Saved results to {out_csv} ({len(df)} rows)")
    return df


def save_parquet(df: pd.DataFrame, out_path: str):
    df.to_parquet(out_path, index=False)


def cli():
    p = argparse.ArgumentParser(description="Trend‑watch YouTube Shorts")
    p.add_argument("--query", default=DEFAULT_QUERY, help="Search query (default: 'YouTube Shorts')")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK, help="Published within last N days")
    p.add_argument("--max", type=int, default=DEFAULT_MAX_RESULTS, help="Max shorts to fetch before filter")
    p.add_argument("--out", default="trendwatch_results.csv", help="Output CSV path")
    p.add_argument("--mcp", action="store_true", help="Launch an MCP server after collecting data")
    p.add_argument("--openai_key", default=os.getenv("OPENAI_API_KEY", ""), help="OpenAI API key")
    p.add_argument("--yt_key", default=os.getenv("YOUTUBE_API_KEY", ""), help="Youtube API key")
    args = p.parse_args()

    df = run_pipeline(
        OPENAI_API_KEY=args.openai_key,
        YOUTUBE_API_KEY=args.yt_key,
        query=args.query,
        days_back=args.days,
        max_results=args.max,
        out_csv=args.out,
    )
    if args.mcp:
        from . import server
        server._df = df  # reuse server but override df
        server.mcp.run(transport="sse", host="0.0.0.0", port=server.PORT)


if __name__ == "__main__":
    cli()
