# KOL Import Format v1

统一输入格式建议使用 JSON 数组，每个元素是一条原始帖子。

```json
[
  {
    "author": "xincctnnq",
    "text": "BTCUSDT breakout with volume expansion",
    "created_at": "2026-04-17T13:32:00Z",
    "url": "https://x.com/.../status/123",
    "likes": 132,
    "reposts": 21,
    "replies": 4,
    "views": 8300,
    "symbols": ["BTCUSDT"],
    "tags": ["breakout", "volume"],
    "source": "x"
  }
]
```

字段说明：

- `author`: KOL 账号名
- `text`: 原文内容
- `created_at`: ISO 8601 时间，建议带 `Z`
- `url`: 原始链接，便于回溯
- `likes` / `reposts` / `replies` / `views`: 可选互动数据
- `symbols`: 帖子显式涉及的币种，建议规范为 `BTCUSDT` 这种格式
- `tags`: 手工或半自动打的标签
- `source`: 默认 `x`

兼容输入：

- `.json`: 支持完整对象数组，也支持字符串数组
- `.md` / `.txt`: 每行一条帖子，建议用 `author | created_at | text` 的简化格式

导入后行为：

- 原始帖子会写入本地数据库中的 `KOLPostRecord` 表
- 后续运行 `scripts/backtest_kol_cards.py` 会根据这些帖子回放历史行情，更新策略卡的历史胜率、平均 RR 和样本数
