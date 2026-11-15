from dataclasses import dataclass


@dataclass(frozen=True)
class BanState:
    ban_level: int
    retry_after_seconds: int
    expires_at_ms: int
