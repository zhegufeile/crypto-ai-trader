import json
from pathlib import Path

from app.data.twikit_export import load_browser_cookie_export


def test_load_browser_cookie_export_from_simple_dict(tmp_path: Path):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"auth_token": "aaa", "ct0": "bbb", "lang": "zh-cn"}), encoding="utf-8")

    cookies = load_browser_cookie_export(path)

    assert cookies["auth_token"] == "aaa"
    assert cookies["ct0"] == "bbb"


def test_load_browser_cookie_export_from_cookie_list(tmp_path: Path):
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            [
                {"name": "auth_token", "value": "aaa", "domain": ".x.com"},
                {"name": "ct0", "value": "bbb", "domain": ".x.com"},
                {"name": "other", "value": "ccc", "domain": ".example.com"},
            ]
        ),
        encoding="utf-8",
    )

    cookies = load_browser_cookie_export(path)

    assert cookies == {"auth_token": "aaa", "ct0": "bbb"}
