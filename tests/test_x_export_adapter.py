from pathlib import Path

from app.data.x_client import XExportAdapter


def test_x_export_adapter_loads_json(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text(
        """
[
  {
    "author": "arya",
    "text": "BTCUSDT breakout with volume",
    "created_at": "2026-04-17T13:32:00Z",
    "likes": 12,
    "reposts": 3
  }
]
""".strip(),
        encoding="utf-8",
    )

    posts = XExportAdapter().load_raw_posts(path, "json")

    assert len(posts) == 1
    assert posts[0].author == "arya"
    assert posts[0].symbols == ["BTCUSDT"]


def test_x_export_adapter_loads_csv(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text(
        "author,text,created_at,likes,reposts,url\n"
        "btc_alert,BTCUSDT pullback,2026-04-17T13:32:00Z,5,1,https://x.com/a\n",
        encoding="utf-8",
    )

    posts = XExportAdapter().load_raw_posts(path, "csv")

    assert len(posts) == 1
    assert posts[0].author == "btc_alert"
    assert posts[0].url == "https://x.com/a"


def test_x_export_adapter_uses_parent_folder_name_when_author_missing(tmp_path: Path):
    folder = tmp_path / "Arya_web3"
    folder.mkdir()
    path = folder / "posts.csv"
    path.write_text(
        "tweet_id,text,created_at,favorite_count,retweet_count,reply_count,view_count\n"
        "'1',BTCUSDT breakout,2026-04-17T13:32:00Z,5,1,0,100\n",
        encoding="utf-8",
    )

    posts = XExportAdapter().load_raw_posts(path, "csv")

    assert len(posts) == 1
    assert posts[0].author == "Arya_web3"
    assert posts[0].likes == 5
    assert posts[0].views == 100


def test_x_export_adapter_loads_txt(tmp_path: Path):
    path = tmp_path / "x.txt"
    path.write_text("Alpha | 2026-04-17T13:32:00Z | SOLUSDT breakout", encoding="utf-8")

    posts = XExportAdapter().load_raw_posts(path, "txt")

    assert len(posts) == 1
    assert posts[0].author == "unknown"
    assert posts[0].symbols == ["SOLUSDT"]
