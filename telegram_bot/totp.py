"""Minimal RFC 6238 verification for high-impact Telegram controls."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from collections.abc import Mapping


class TotpVerifier:
    def __init__(
        self,
        secret: str,
        *,
        period_seconds: int = 30,
        digits: int = 6,
        window: int = 1,
    ):
        normalized = "".join(str(secret).split()).upper()
        self._secret = normalized
        self.period_seconds = int(period_seconds)
        self.digits = int(digits)
        self.window = int(window)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TotpVerifier:
        values = os.environ if environ is None else environ
        return cls(values.get("TELEGRAM_CONTROL_TOTP_SECRET", ""))

    @property
    def configured(self) -> bool:
        return bool(self._secret)

    def verify(self, code: str, *, now: float | None = None) -> bool:
        if not self.configured:
            return False
        candidate = str(code).strip()
        if len(candidate) != self.digits or not candidate.isdigit():
            return False
        instant = time.time() if now is None else float(now)
        counter = int(instant // self.period_seconds)
        for offset in range(-self.window, self.window + 1):
            expected = self._code(counter + offset)
            if expected is not None and hmac.compare_digest(candidate, expected):
                return True
        return False

    def _code(self, counter: int) -> str | None:
        padding = "=" * ((8 - len(self._secret) % 8) % 8)
        try:
            key = base64.b32decode(self._secret + padding, casefold=True)
        except (ValueError, base64.binascii.Error):
            return None
        digest = hmac.new(
            key,
            struct.pack(">Q", counter),
            hashlib.sha1,
        ).digest()
        offset = digest[-1] & 0x0F
        binary = struct.unpack(">I", digest[offset : offset + 4])[0]
        value = (binary & 0x7FFFFFFF) % (10**self.digits)
        return str(value).zfill(self.digits)
