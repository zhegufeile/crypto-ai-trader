from app.data.onchainos_risk_export import export_onchainos_risks


def test_export_onchainos_risks_marks_honeypot_and_critical():
    security_payload = {
        "data": [
            {
                "symbol": "SCAM",
                "riskLevel": "CRITICAL",
                "action": "block",
                "labels": ["honeypot", "cannot_sell"],
            }
        ]
    }
    advanced_payload = {
        "data": [
            {
                "symbol": "SCAM",
                "riskControlLevel": "5",
                "tokenTags": ["honeypot", "lowLiquidity"],
                "top10HoldPercent": "92",
                "devHoldingPercent": "28",
                "bundleHoldingPercent": "17",
                "suspiciousHoldingPercent": "12",
            }
        ]
    }

    snapshot = export_onchainos_risks(security_payload, advanced_payload, default_chain="solana")

    assert len(snapshot["risks"]) == 1
    risk = snapshot["risks"][0]
    assert risk["symbol"] == "SCAM"
    assert risk["honeypot"] is True
    assert risk["is_safe_buy"] is False
    assert risk["risk_level"] == "CRITICAL"
    assert "honeypot" in risk["risk_tags"]
