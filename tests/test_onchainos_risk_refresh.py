import json
from pathlib import Path

from app.data.onchainos_cli import OnchainOSCLI
from app.data.onchainos_risk_refresh import (
    RiskRefreshTarget,
    load_signal_targets,
    refresh_onchainos_risks,
)


class FakeOnchainOSCLI:
    def security_token_scan(self, *, tokens):
        assert tokens == [("501", "addr1"), ("501", "addr2")]
        return {
            "data": [
                {
                    "token": {"symbol": "PNKSTR", "tokenAddress": "addr1"},
                    "chain": "solana",
                    "riskLevel": "LOW",
                    "labels": ["lowLiquidity"],
                },
                {
                    "token": {"symbol": "SCAM", "tokenAddress": "addr2"},
                    "chain": "solana",
                    "riskLevel": "CRITICAL",
                    "labels": ["honeypot"],
                    "action": "block",
                },
            ]
        }

    def token_advanced_info(self, *, address, chain):
        assert chain == "solana"
        if address == "addr1":
            return {
                "data": {
                    "symbol": "PNKSTR",
                    "tokenAddress": "addr1",
                    "chain": "solana",
                    "riskControlLevel": "LOW",
                    "tokenTags": ["lowLiquidity"],
                    "top10HoldPercent": 33,
                }
            }
        return {
            "data": {
                "symbol": "SCAM",
                "tokenAddress": "addr2",
                "chain": "solana",
                "riskControlLevel": "CRITICAL",
                "tokenTags": ["honeypot"],
                "top10HoldPercent": 96,
            }
        }


def test_load_signal_targets_reads_addresses_and_chain_indices(tmp_path: Path):
    path = tmp_path / "signals.snapshot.json"
    path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "symbol": "PNKSTR",
                        "token_address": "addr1",
                        "chain": "solana",
                        "chain_index": "501",
                    },
                    {
                        "symbol": "PNKSTR",
                        "token_address": "addr1",
                        "chain": "solana",
                        "chain_index": "501",
                    },
                    {
                        "symbol": "SCAM",
                        "token_address": "addr2",
                        "chain": "solana",
                        "chain_index": "501",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    targets = load_signal_targets(path)

    assert targets == [
        RiskRefreshTarget(symbol="PNKSTR", address="addr1", chain="solana", chain_index="501"),
        RiskRefreshTarget(symbol="SCAM", address="addr2", chain="solana", chain_index="501"),
    ]


def test_refresh_onchainos_risks_writes_snapshot_and_raw_payloads(tmp_path: Path):
    output = tmp_path / "risks.snapshot.json"
    security_raw = tmp_path / "token_scan.raw.json"
    advanced_raw = tmp_path / "advanced_info.raw.json"

    summary = refresh_onchainos_risks(
        targets=[
            RiskRefreshTarget(symbol="PNKSTR", address="addr1", chain="solana", chain_index="501"),
            RiskRefreshTarget(symbol="SCAM", address="addr2", chain="solana", chain_index="501"),
        ],
        cli=FakeOnchainOSCLI(),
        output_path=output,
        security_raw_output=security_raw,
        advanced_raw_output=advanced_raw,
    )

    snapshot = json.loads(output.read_text(encoding="utf-8"))

    assert summary["blocked_symbols"] == ["SCAM"]
    assert security_raw.exists()
    assert advanced_raw.exists()
    assert snapshot["kind"] == "risk_snapshot"
    assert any(item["symbol"] == "SCAM" and item["honeypot"] for item in snapshot["risks"])


def test_onchainos_cli_applies_proxy_environment(monkeypatch):
    captured = {}

    class Result:
        stdout = "{}"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    cli = OnchainOSCLI("onchainos.exe", proxy_url="http://127.0.0.1:10809")
    cli.token_search("PNKSTR", chain="solana", limit=3)

    assert captured["command"][0] == "onchainos.exe"
    assert captured["env"]["HTTPS_PROXY"] == "http://127.0.0.1:10809"
