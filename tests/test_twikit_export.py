from pathlib import Path

from app.data.twikit_export import dedupe_records, merge_records, tweet_to_export_record


class FakeTweet:
    def __init__(self):
        self.id = "123"
        self.text = "BTCUSDT breakout with volume"
        self.created_at = "2026-05-10T10:00:00Z"
        self.favorite_count = 10
        self.retweet_count = 3
        self.reply_count = 1
        self.view_count = 99


def test_tweet_to_export_record_maps_fields():
    record = tweet_to_export_record(FakeTweet(), "arya_web3")

    assert record["id"] == "123"
    assert record["author"] == "arya_web3"
    assert record["symbols"] == ["BTCUSDT"]
    assert record["url"] == "https://x.com/arya_web3/status/123"


def test_merge_records_deduplicates_and_sorts():
    existing = [{"id": "1", "created_at": "2026-05-09T10:00:00Z", "author": "a", "text": "old"}]
    fresh = [
        {"id": "1", "created_at": "2026-05-09T10:00:00Z", "author": "a", "text": "old"},
        {"id": "2", "created_at": "2026-05-10T10:00:00Z", "author": "a", "text": "new"},
    ]

    merged = merge_records(existing, fresh)

    assert [item["id"] for item in merged] == ["2", "1"]
