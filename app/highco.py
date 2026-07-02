"""Adapter that turns a promotion's HighCo reference (the URL/identifier decoded
from its QR code) into a fresh redemption code for the till.

⚠️ PARTIALLY VERIFIED (2026-07-02): a real HighCo Nifty link (highcodata.walletpass.fr,
a PassKit-style wallet distribution platform) was inspected with a desktop User-Agent.
It redirects (3 hops) to an HTML landing page that says "scan this QR with your phone
to download your pass" — i.e. a *non-wallet-capable* client never gets a code directly.
The working theory, NOT YET CONFIRMED, is that a request with a mobile Safari
User-Agent gets served the actual `.pkpass` file (a zip containing `pass.json`,
whose `barcodes[].message` field holds the code — see pkpass_utils.py). This has
not been tested live: doing so may mint a real, single-use redemption code against
an actual in-flight promotion, so it needs to happen deliberately, not from
automated retries. Confirm before relying on this in production.
"""

import re

import httpx

from .pkpass_utils import extract_code_from_pkpass

_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{6,14}\b")
_JSON_CODE_KEYS = ("code", "coupon_code", "redemption_code", "voucher_code", "barcode")

# iOS Safari UA — HighCo's wallet-distribution platform appears to serve the
# actual .pkpass file only to clients that look wallet-capable (unverified).
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


class HighCoResponseError(RuntimeError):
    def __init__(self, message: str, raw_excerpt: str = ""):
        super().__init__(message)
        self.raw_excerpt = raw_excerpt


def generate_code(reference: str, timeout: float = 15.0) -> str:
    """Call the HighCo endpoint identified by `reference` and return a fresh code.

    Each call is expected to mint a new, single-use code (one call = one till
    transaction) — do not cache or reuse the result.
    """
    try:
        response = httpx.get(
            reference,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _MOBILE_USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HighCoResponseError(f"Requête HighCo échouée : {exc}") from exc

    return _extract_code(response)


def _extract_code(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")

    if "application/vnd.apple.pkpass" in content_type:
        code = extract_code_from_pkpass(response.content)
        if code:
            return code
        raise HighCoResponseError(
            "Pass Wallet reçu mais aucun code trouvé dans pass.json", raw_excerpt=f"{len(response.content)} bytes"
        )

    if "wallet" in content_type:
        raise HighCoResponseError(
            "La réponse HighCo est un pass Wallet d'un format inattendu — extraction non implémentée.",
            raw_excerpt=f"content-type={content_type}",
        )

    if "json" in content_type:
        try:
            data = response.json()
        except ValueError as exc:
            raise HighCoResponseError("Réponse JSON illisible", raw_excerpt=response.text[:500]) from exc
        for key in _JSON_CODE_KEYS:
            if key in data and data[key]:
                return str(data[key])
        raise HighCoResponseError(
            "Réponse JSON sans champ de code reconnu", raw_excerpt=str(data)[:500]
        )

    text = response.text.strip()

    if "text/html" in content_type or text.startswith("<"):
        if "Scannez ce QR code" in text or "télécharger votre pass" in text:
            raise HighCoResponseError(
                "HighCo a renvoyé la page de repli « scannez avec votre téléphone » au lieu du pass — "
                "le User-Agent utilisé n'est probablement pas reconnu comme compatible Wallet.",
                raw_excerpt=text[:500],
            )
        match = _CODE_PATTERN.search(text)
        if match:
            return match.group(0)
        raise HighCoResponseError("Aucun code trouvé dans la page HTML", raw_excerpt=text[:500])

    if text:
        match = _CODE_PATTERN.fullmatch(text) or _CODE_PATTERN.search(text)
        if match:
            return match.group(0)
        return text  # fall back to whatever plain text was returned

    raise HighCoResponseError("Réponse HighCo vide ou de format non reconnu", raw_excerpt=repr(response.content[:200]))
