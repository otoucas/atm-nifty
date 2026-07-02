"""Parses an Apple Wallet (.pkpass) file to extract the redemption code.

⚠️ UNVERIFIED: written from the public PassKit file-format spec (a .pkpass is a
ZIP archive containing a `pass.json` with a `barcodes` array; each entry has a
`message` field holding the value encoded in the barcode/QR shown on the pass).
Not yet checked against a real HighCo Nifty pass — confirm the actual field
layout before relying on this.
"""

import json
import zipfile
from io import BytesIO
from typing import Optional


def extract_code_from_pkpass(data: bytes) -> Optional[str]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        with archive.open("pass.json") as f:
            pass_data = json.load(f)

    barcodes = pass_data.get("barcodes") or ([pass_data["barcode"]] if "barcode" in pass_data else [])
    for barcode in barcodes:
        message = barcode.get("message")
        if message:
            return message
    return None
