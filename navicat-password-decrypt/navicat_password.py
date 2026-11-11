#!/usr/bin/env python3
"""Navicat 保存连接密码的加解密工具（Python 复刻 navicat解密码.php）。

version 11: Blowfish-ECB 分组 + XOR 反馈链，密钥 sha1('3DC5CA39')
version 12: AES-128-CBC，key='libcckeylibcckey' iv='libcciv libcciv '
两种输出的密文均为大写 Hex。
"""
import argparse
import hashlib
import sys

from Crypto.Cipher import AES, Blowfish

BLOW_STRING = "3DC5CA39"
BLOW_IV = bytes.fromhex("d9c7c3c8870d64bd")
AES_KEY = b"libcckeylibcckey"
AES_IV = b"libcciv libcciv "
_BLOW_KEY = hashlib.sha1(BLOW_STRING.encode()).digest()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _bf_ecb_encrypt_block(block: bytes) -> bytes:
    return Blowfish.new(_BLOW_KEY, Blowfish.MODE_ECB).encrypt(block)


def _bf_ecb_decrypt_block(block: bytes) -> bytes:
    return Blowfish.new(_BLOW_KEY, Blowfish.MODE_ECB).decrypt(block)


def _pkcs7_pad(data: bytes, bs: int = 16) -> bytes:
    pad = bs - len(data) % bs
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16 or pad > len(data) or data[-pad:] != bytes([pad]) * pad:
        return data
    return data[:-pad]


def encrypt_eleven(string: str) -> str:
    data = string.encode()
    out = b""
    cur = BLOW_IV
    for i in range(len(data) // 8):
        temp = _bf_ecb_encrypt_block(_xor(data[8 * i:8 * i + 8], cur))
        cur = _xor(cur, temp)
        out += temp
    left = len(data) % 8
    if left:
        cur = _bf_ecb_encrypt_block(cur)
        out += _xor(data[8 * (len(data) // 8):], cur)
    return out.hex().upper()


def decrypt_eleven(cipher_text: str) -> str:
    data = bytes.fromhex(cipher_text.strip().lower())
    out = b""
    cur = BLOW_IV
    for i in range(len(data) // 8):
        block = data[8 * i:8 * i + 8]
        out += _xor(_bf_ecb_decrypt_block(block), cur)
        cur = _xor(cur, block)
    left = len(data) % 8
    if left:
        cur = _bf_ecb_encrypt_block(cur)
        out += _xor(data[8 * (len(data) // 8):], cur)
    return _decode_result(out)


def encrypt_twelve(string: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(_pkcs7_pad(string.encode())).hex().upper()


def decrypt_twelve(cipher_text: str) -> str:
    data = bytes.fromhex(cipher_text.strip().lower())
    if len(data) % 16 or not data:
        return ""
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return _decode_result(_pkcs7_unpad(cipher.decrypt(data)))


def _decode_result(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def encrypt(plain: str, version: int = 12) -> str:
    return encrypt_eleven(plain) if version == 11 else encrypt_twelve(plain)


def decrypt(cipher_text: str, version: int = 12) -> str:
    return decrypt_eleven(cipher_text) if version == 11 else decrypt_twelve(cipher_text)


def _printable_score(text: str) -> float:
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch.isprintable() or ch in "\t\n")
    return good / len(text)


def decrypt_auto(cipher_text: str):
    """依次尝试 v12、v11，返回 (明文, 版本, 可信度)。"""
    candidates = []
    for version in (12, 11):
        try:
            text = decrypt(cipher_text, version)
        except Exception:
            continue
        score = _printable_score(text)
        candidates.append((score, text, version))
    if not candidates:
        return "", 0, 0.0
    candidates.sort(key=lambda c: c[0], reverse=True)
    score, text, version = candidates[0]
    if not text:
        return "", 0, 0.0
    return text, version, max(0.0, min(1.0, score))


def _mask(text: str) -> str:
    if not text:
        return "(空)"
    safe = "".join(c if c.isprintable() else "?" for c in text)
    if len(safe) <= 4:
        return f"****(len={len(safe)})"
    return f"{safe[:2]}***{safe[-2:]} (len={len(safe)})"


def scan_registry(value_name="Pwd", show=False, version=0, max_depth=12):
    """只读递归扫描 HKCU\\Software\\PremiumSoft，找出保存的密码并解密。

    连接不一定在 Servers\\<名> 下：新版 Navicat 会把带密码的副本放在
    <产品>\\CloudProjectServers\\<profile-uuid>\\<project-uuid>\\<连接名>，
    整棵树有几千个键，所以只能递归按值名找，别猜路径。
    """
    try:
        import winreg
    except ImportError:
        print("ERROR: scan 仅支持 Windows（需要 winreg 读注册表）", file=sys.stderr)
        return 1

    hive = winreg.HKEY_CURRENT_USER
    base = r"Software\PremiumSoft"
    hits = []
    stats = {"keys": 0}

    def read(key, name):
        try:
            return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return ""

    def walk(path, depth=0):
        if depth > max_depth:
            return
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            return
        with key:
            stats["keys"] += 1
            children = []
            i = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, i))
                except OSError:
                    break
                i += 1
            j = 0
            while True:
                try:
                    n, v, _t = winreg.EnumValue(key, j)
                except OSError:
                    break
                j += 1
                if str(n).lower() == value_name.lower() and isinstance(v, str) and v.strip():
                    hits.append((path, n, v.strip(), read(key, "Host"), read(key, "UserName"), read(key, "Port")))
        for c in children:
            walk(path + "\\" + c, depth + 1)

    walk(base)

    if not hits:
        print(f"已扫描 HKCU\\{base} 下 {stats['keys']} 个键，未找到值名含 {value_name!r} 的密码。")
        print("可能原因：连接未勾选「保存密码」；或该存储用了主密码/.ncx 容器（不属 v11/v12）。")
        return 0

    print(f"扫描 {stats['keys']} 个键，命中 {len(hits)} 个候选密文：\n")
    for path, name, ct, host, user, port in hits:
        conn = path.split("\\")[-1]
        ctx = f"{user}@{host}:{port}" if (host or user) else ""
        try:
            bytes.fromhex(ct.replace(" ", ""))
        except ValueError:
            print(f"[跳过] {conn} :: {name} 非 Hex(len={len(ct)}) {ctx}")
            continue
        if version:
            text = decrypt(ct, version)
            used, conf = version, _printable_score(text)
        else:
            text, used, conf = decrypt_auto(ct)
        if not text:
            print(f"[失败] {conn} :: {name} len={len(ct)} 解不出（不是 v11/v12 密文？） {ctx}")
            continue
        display = text if show else _mask(text)
        flag = "" if conf >= 0.95 else "  (低可信：可能不是这两套算法)"
        print(f"[v{used}] conn={conn!r} field={name} plain={display} target={ctx}{flag}")
    if not show:
        print("\n（默认打码，避免明文进日志/截图；确认是本机密码后加 --show）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Navicat 密码加解密（v11 Blowfish / v12 AES-128-CBC）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python navicat_password.py decrypt 15057D7BA390\n"
               "  python navicat_password.py decrypt -v 11 15057D7BA390\n"
               "  python navicat_password.py encrypt root -v 12\n"
               "  python navicat_password.py decrypt A1B2 C3D4 --csv\n"
               "  python navicat_password.py scan            # 只读扫本机注册表",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_dec = sub.add_parser("decrypt", help="解密（默认自动识别版本）")
    p_dec.add_argument("cipher", nargs="+", help="大写 Hex 密文，可多个")
    p_dec.add_argument("-v", "--version", type=int, default=0, choices=[0, 11, 12],
                       help="0=自动识别(默认) 11=Navicat 11 12=Navicat 12+")
    p_dec.add_argument("--csv", action="store_true", help="输出 密文,明文,版本 三列")
    p_dec.add_argument("--verify", action="store_true", help="附带 re-encrypt 一致性校验")

    p_enc = sub.add_parser("encrypt", help="加密")
    p_enc.add_argument("plain", nargs="+", help="明文密码，可多个")
    p_enc.add_argument("-v", "--version", type=int, default=12, choices=[11, 12])

    p_scan = sub.add_parser("scan", help="扫描本机注册表里保存的 Navicat 密码并解密（只读）")
    p_scan.add_argument("--value", default="Pwd", help="值名子串过滤，默认 Pwd")
    p_scan.add_argument("--show", action="store_true", help="输出明文（默认打码，防截图外泄）")
    p_scan.add_argument("-v", "--version", type=int, default=0, choices=[0, 11, 12])

    args = parser.parse_args()

    if args.mode == "scan":
        return scan_registry(args.value, args.show, args.version)

    if args.mode == "encrypt":
        for plain in args.plain:
            print(encrypt(plain, args.version))
        return 0

    rows = []
    for cipher_text in args.cipher:
        normalized = cipher_text.strip().replace(" ", "")
        try:
            bytes.fromhex(normalized.lower())
        except ValueError:
            print(f"{cipher_text}\t\tERROR: 不是合法的 Hex 密文", file=sys.stderr)
            continue
        if args.version:
            text = decrypt(normalized, args.version)
            version, confidence = args.version, _printable_score(text)
        else:
            text, version, confidence = decrypt_auto(normalized)
        note = ""
        if confidence < 0.95:
            note = "  (低可信：可能是乱码/版本不匹配)"
        if args.verify and text:
            re_enc = encrypt(text, version)
            note += "  [roundtrip OK]" if re_enc == normalized.upper() else "  [roundtrip DIFF]"
        if args.csv:
            rows.append(f"{normalized.upper()},{text},{version}")
        else:
            print(f"密文: {normalized.upper()}")
            print(f"明文: {text!r}" if text else "明文: (解不出)")
            print(f"版本: {version or '未知'}  可信度: {confidence:.2f}{note}")

    if args.csv:
        print("cipher,plain,version")
        print("\n".join(rows))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
