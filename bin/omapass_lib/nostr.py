"""Nostr keys: Bech32 nsec/npub encoding, generation and the nostr commands."""

import json
import os
import sys

from omapass_lib import common, keyring_store

NOSTR_ACCOUNT = "nostr:default"
NOSTR_FOLDER = "Nostr"
NOSTR_KIND = "nostr"

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


def polymod(values):
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= GEN[i]
    return chk


def hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def create_checksum(hrp, data):
    values = hrp_expand(hrp) + data
    mod = polymod(values + [0] * 6) ^ 1
    return [(mod >> 5 * (5 - i)) & 31 for i in range(6)]


def bech32_encode(hrp, data):
    combined = data + create_checksum(hrp, data)
    return hrp + "1" + "".join(CHARSET[d] for d in combined)


def bech32_decode(bech):
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return None, None
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        return None, None
    hrp = bech[:pos]
    data = []
    for c in bech[pos + 1 :]:
        idx = CHARSET.find(c)
        if idx == -1:
            return None, None
        data.append(idx)
    if polymod(hrp_expand(hrp) + data) != 1:
        return None, None
    return hrp, data[:-6]


def convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def nsec_encode(raw32):
    data = convertbits(raw32, 8, 5, True)
    if data is None:
        common.die("failed to encode nsec")
    return bech32_encode("nsec", data)


def parse_nostr_secret(stored):
    stored = stored.strip()
    if stored.startswith("nsec1"):
        hrp, data = bech32_decode(stored)
        if hrp != "nsec" or data is None:
            common.die("stored nostr key is not valid nsec1")
        raw = convertbits(data, 5, 8, False)
        if raw is None or len(raw) != 32:
            common.die("stored nostr key is not valid nsec1")
        return bytes(raw)
    if len(stored) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored):
        return bytes.fromhex(stored)
    common.die("stored nostr key format not recognized (expected nsec1 or 64-char hex)")


def has_nostr_crypto():
    for name in ("coincurve", "secp256k1"):
        try:
            __import__(name)
            return name
        except ImportError:
            pass
    return None


def npub_from_sk(raw32):
    backend = has_nostr_crypto()
    if not backend:
        return None
    if backend == "coincurve":
        from coincurve import PrivateKey

        xonly = PrivateKey(raw32).public_key.format(compressed=True)[1:]
    else:
        import secp256k1

        xonly = secp256k1.PrivateKey(raw32, raw=True).pubkey.serialize(compressed=True)[1:]
    data = convertbits(xonly, 8, 5, True)
    return bech32_encode("npub", data)


def generate_nsec_material():
    sk = os.urandom(32)
    nsec = nsec_encode(sk)
    npub = npub_from_sk(sk)
    return nsec, npub


def cmd_generate_nostr(args):
    account = args.account or NOSTR_ACCOUNT
    folder = args.folder or NOSTR_FOLDER
    backend = keyring_store.get_backend()
    nsec, npub = generate_nsec_material()
    # The helper refuses to replace unless asked; no separate exists check.
    backend.store(account, folder, nsec, NOSTR_KIND, args.replace)
    payload = {"ok": True, "account": account}
    if npub:
        payload["npub"] = npub
    print(json.dumps(payload, ensure_ascii=False))


def cmd_nostr_new(args):
    account = args.account or NOSTR_ACCOUNT
    folder = args.folder or NOSTR_FOLDER
    backend = keyring_store.get_backend()
    nsec, npub = generate_nsec_material()
    backend.store(account, folder, nsec, NOSTR_KIND)
    if npub:
        print(npub)
    elif has_nostr_crypto() is None:
        print(
            "NOTE: install python-coincurve (or python-secp256k1) to derive npub (omapass nostr show-npub)"
        )


def cmd_nostr_show_npub(args):
    account = args.account or common.take_optional_account(args.rest, NOSTR_ACCOUNT)
    stored = keyring_store.get_backend().get_secret(account, NOSTR_KIND)
    sk = parse_nostr_secret(stored)
    npub = npub_from_sk(sk)
    if not npub:
        common.die("npub requires python-coincurve or python-secp256k1")
    print(npub)


def cmd_nostr_show_nsec(args):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        common.die("nostr show-nsec requires an interactive terminal")
    account = args.account or common.take_optional_account(args.rest, NOSTR_ACCOUNT)
    print("Type yes to reveal the Nostr secret key: ", end="", file=sys.stderr)
    answer = input().strip()
    if answer != "yes":
        common.die("confirmation failed")
    print(keyring_store.get_backend().get_secret(account, NOSTR_KIND))


def cmd_nostr_rm(args):
    account = args.account or common.take_optional_account(args.rest, NOSTR_ACCOUNT)
    keyring_store.get_backend().clear(account, NOSTR_KIND)
