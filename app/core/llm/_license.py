# -*- coding: utf-8 -*-
"""
Koto License / Activation Key Module
=====================================
This file is compiled to a native .pyd via Cython during packaging.
Do NOT distribute the .py source; only the compiled binary ships with the installer.

The embedded system key is XOR-obfuscated with seed 0x6B.
To update the key, replace _K with: [b ^ _S for b in b"YOUR_NEW_API_KEY"]
"""

# XOR seed
_S = 0x6B

# Activation code reference (XOR-encoded "KotoAgent")
# To update: [b ^ _S for b in b"YourNewCode"]
_C = [0, 36, 63, 36, 10, 44, 46, 37, 63]

# Embedded system API key (XOR-encoded with seed _S)
# To update: [b ^ _S for b in b"YOUR_API_KEY_HERE"]
_K = [
    10, 2, 49, 42, 24, 50, 15, 5, 28, 12, 24, 9, 25, 19, 32, 24,
    44, 57, 35, 35, 62, 33, 26, 20, 29, 28, 57, 126, 3, 27, 123,
    63, 63, 20, 120, 61, 31, 50, 14,
]


def get_system_key(activation_code: str):
    """
    Return the embedded system API key if the activation code is valid.
    Returns None if the code is wrong.
    """
    encoded = [b ^ _S for b in activation_code.encode("utf-8")]
    if encoded != _C:
        return None
    return "".join(chr(b ^ _S) for b in _K)
