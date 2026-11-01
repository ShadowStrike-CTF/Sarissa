"""Flag encodings used in generated challenges. Single source; hosts vendor this.

Byte-for-byte identical to Poligon's ``android.encode_flag`` (base64) and ``evidence._hex``
(hex): ``str.encode()`` with the default UTF-8 codec, standard base64 alphabet with padding,
lowercase hex.
"""

from __future__ import annotations

import base64


def encode_b64(text: str) -> str:
    """Standard base64 (with ``=`` padding) of the UTF-8 bytes of ``text``."""
    return base64.b64encode(text.encode()).decode()


def encode_hex(text: str) -> str:
    """Lowercase hex of the UTF-8 bytes of ``text``."""
    return text.encode().hex()
