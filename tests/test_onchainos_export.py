import json
from pathlib import Path

from app.data.onchainos_export import export_onchainos_signals, load_onchainos_signal_payload


def test_export_onchainos_signals_normalizes_signal_list_payload():
    payload = {
        "data": [
            {
                "timestamp": "1710000000000",
                "chainIndex": "501",
                "price": "0.12",
                "walletType": "1,2",
                "triggerWalletCount": "4",
                "triggerWalletAddress": "addr1,addr2",
                "amountUsd": "125000",
                "soldRatioPercent": "18",
                "token": {
                    "tokenAddress": "So11111111111111111111111111111111111111112",
                    "symbol": "PNKSTR",
                    "name": "Pink Star",
                    "marketCapUsd": "3500000",
                    "holders": "2400",
                    "top10HolderPercent": "32",
                },
                "cursor": "abc123",
            }
        ]
    }

    snapshot = export_onchainos_signals(payload, default_chain="solana", min_wallet_count=1)

    assert snapshot["source"] == "okx_onchainos"
    assert len(snapshot["signals"]) == 1
    signal = snapshot["signals"][0]
    assert signal["symbol"] == "PNKSTR"
    assert signal["chain"] == "solana"
    assert signal["wallet_types"] == ["smart_money", "kol"]
    assert signal["wallet_count"] == 4
    assert signal["buy_amount_usd"] == 125000.0
    assert signal["signal_score"] > 0.7


def test_export_onchainos_signals_filters_weak_items():
    payload = {
        "signals": [
            {
                "walletType": "3",
                "triggerWalletCount": "1",
                "amountUsd": "5000",
                "soldRatioPercent": "90",
                "token": {"symbol": "DUST"},
            }
        ]
    }

    snapshot = export_onchainos_signals(payload, min_signal_score=0.5, min_wallet_count=2)

    assert snapshot["signals"] == []


def test_load_onchainos_signal_payload_reads_json(tmp_path: Path):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps({"signals": [{"token": {"symbol": "BTC"}}]}), encoding="utf-8")

    payload = load_onchainos_signal_payload(path)

    assert payload["signals"][0]["token"]["symbol"] == "BTC"
