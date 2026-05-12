# Runbook

## 本地运行

```powershell
pip install -r requirements.txt
python scripts/bootstrap_db.py
uvicorn app.main:app --reload
```

## 手动扫描

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/admin/scan
```

## 风控原则

- 不配置真实交易权限前，只运行模拟盘。
- API key 不写入代码，统一走环境变量。
- 出现连续亏损、极端波动、资金费率过热时禁止开仓。
