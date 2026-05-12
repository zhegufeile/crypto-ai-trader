from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ONCHAINOS_PATH = Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "onchainos.exe"


class OnchainOSCLIError(RuntimeError):
    pass


class OnchainOSCLI:
    def __init__(self, executable: str | Path | None = None, *, proxy_url: str | None = None) -> None:
        self.executable = str(Path(executable) if executable else DEFAULT_ONCHAINOS_PATH)
        self.proxy_url = proxy_url

    def token_search(self, query: str, *, chain: str, limit: int = 5) -> Any:
        return self._run_json(["token", "search", "--query", query, "--chain", chain, "--limit", str(limit)])

    def token_advanced_info(self, *, address: str, chain: str) -> Any:
        return self._run_json(["token", "advanced-info", "--address", address, "--chain", chain])

    def security_token_scan(self, *, tokens: list[tuple[str, str]]) -> Any:
        if not tokens:
            return {"data": []}
        encoded = ",".join(f"{chain_index}:{address}" for chain_index, address in tokens)
        return self._run_json(["security", "token-scan", "--tokens", encoded])

    def _run_json(self, args: list[str]) -> Any:
        command = [self.executable, *args]
        env = os.environ.copy()
        if self.proxy_url:
            env["HTTP_PROXY"] = self.proxy_url
            env["HTTPS_PROXY"] = self.proxy_url
            env["http_proxy"] = self.proxy_url
            env["https_proxy"] = self.proxy_url
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
        except FileNotFoundError as exc:
            raise OnchainOSCLIError(f"onchainos executable not found: {self.executable}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or str(exc)
            raise OnchainOSCLIError(details) from exc

        output = (completed.stdout or "").strip()
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise OnchainOSCLIError(f"onchainos returned non-JSON output: {output[:200]}") from exc
