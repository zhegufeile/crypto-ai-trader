class LLMClient:
    """Placeholder for future LLM-backed analysis.

    The MVP intentionally works without an LLM key by using RuleBasedAnalyst.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)
