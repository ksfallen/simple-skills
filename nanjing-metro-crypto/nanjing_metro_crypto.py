#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
南京地铁手机号加解密工具

复现 Java EncryptUtils 的 AES 加解密逻辑:
- 密钥派生: SHA1PRNG SecureRandom + AES KeyGenerator (128-bit)
- 加密模式: AES/ECB/PKCS5Padding
- 输出格式: Hex 编码

默认密钥: 7c5b4cbf35eb4e2db962d0702ae819a3

用法:
    python nanjing_metro_crypto.py encrypt <手机号>
    python nanjing_metro_crypto.py decrypt <密文>
    python nanjing_metro_crypto.py encrypt <手机号> --key <自定义密钥>
    python nanjing_metro_crypto.py batch encrypt <手机号列表文件>
"""

import hashlib
import argparse
import sys

from Crypto.Cipher import AES

# 默认密钥
DEFAULT_KEY = "7c5b4cbf35eb4e2db962d0702ae819a3"


# ==============================================================================
# SHA1PRNG 密钥派生 - 复现 Java sun.security.provider.SecureRandom
# ==============================================================================

def _sha1_compress(state: bytes, seed: bytes) -> bytes:
    """
    复现 Java SHA1PRNG 的 compress 函数。
    将 state (20 bytes) 和 seed 通过 SHA-1 压缩为新的 20-byte state。
    """
    sha1_block = 64
    remaining = len(seed)
    k = 0
    int_buffer = bytearray(sha1_block)

    while k < remaining:
        chunk = min(remaining - k, sha1_block)

        # 将 state 复制到 intBuffer (state 只有 20 字节，循环填充)
        for i in range(sha1_block):
            int_buffer[i] = state[i % 20]

        # 将 seed 的 chunk 与 intBuffer 前 chunk 字节做 XOR
        for i in range(chunk):
            int_buffer[i] ^= seed[k + i]

        # SHA-1 absorb: update(xor_part) + update(remaining_seed)
        h = hashlib.sha1()
        h.update(bytes(int_buffer[:chunk]))
        if k + chunk < remaining:
            h.update(seed[k + chunk:])
        # 如果 k+chunk >= remaining，则没有剩余 seed 需要吸收

        state = h.digest()  # 20 bytes
        k += chunk

    return state


def sha1prng_derive_key(seed_str: str, key_size: int = 128) -> bytes:
    """
    复现 Java 密钥派生过程:

        SecureRandom random = SecureRandom.getInstance("SHA1PRNG");
        random.setSeed(keySeed.getBytes());
        KeyGenerator g = KeyGenerator.getInstance("AES");
        g.init(128, random);
        SecretKey secretKey = g.generateKey();
        byte[] encodeKey = secretKey.getEncoded();

    步骤:
    1. setSeed: SHA-1 compress seed -> 20-byte state
    2. generateSeed(20): SHA-1(state) -> 20-byte output
    3. 取前 key_size/8 字节作为 AES 密钥
    """
    seed_bytes = seed_str.encode('utf-8')

    # Step 1: setSeed - compress seed into 20-byte state
    state = _sha1_compress(b'\x00' * 20, seed_bytes)

    # Step 2: generateSeed - SHA-1 of current state
    output = hashlib.sha1(state).digest()

    # Step 3: take first N bytes as AES key
    return output[:key_size // 8]


# ==============================================================================
# PKCS5/PKCS7 Padding
# ==============================================================================

def pkcs5_pad(data: bytes, block_size: int = 16) -> bytes:
    """PKCS5/PKCS7 填充"""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def pkcs5_unpad(data: bytes) -> bytes:
    """PKCS5/PKCS7 去填充"""
    pad_len = data[-1]
    return data[:-pad_len]


# ==============================================================================
# 加密 / 解密
# ==============================================================================

def encrypt(content: str, key: str = DEFAULT_KEY, charset: str = 'utf-8') -> str:
    """
    AES 加密 (对应 Java EncryptUtils.encrypt)

    Args:
        content: 明文内容
        key:     加密密钥 (seed)
        charset: 字符编码, 默认 utf-8

    Returns:
        Hex 编码的大写密文
    """
    aes_key = sha1prng_derive_key(key)
    cipher = AES.new(aes_key, AES.MODE_ECB)
    padded = pkcs5_pad(content.encode(charset))
    result = cipher.encrypt(padded)
    return result.hex().upper()


def decrypt(content: str, key: str = DEFAULT_KEY, charset: str = 'utf-8') -> str:
    """
    AES 解密 (对应 Java EncryptUtils.decrypt)

    Args:
        content: Hex 编码的密文
        key:     加密密钥 (seed)
        charset: 字符编码, 默认 utf-8

    Returns:
        解密后的明文
    """
    aes_key = sha1prng_derive_key(key)
    cipher = AES.new(aes_key, AES.MODE_ECB)
    encrypted = bytes.fromhex(content)
    result = cipher.decrypt(encrypted)
    return pkcs5_unpad(result).decode(charset)


def batch_encrypt(file_path: str, key: str = DEFAULT_KEY, charset: str = 'utf-8') -> list:
    """批量加密：读取文件中的每一行并加密"""
    results = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                encrypted = encrypt(line, key, charset)
                results.append((line, encrypted))
    return results


def batch_decrypt(file_path: str, key: str = DEFAULT_KEY, charset: str = 'utf-8') -> list:
    """批量解密：读取文件中的每一行并解密"""
    results = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                decrypted = decrypt(line, key, charset)
                results.append((line, decrypted))
    return results


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='南京地铁手机号加解密工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 加密单个手机号
  python nanjing_metro_crypto.py encrypt 13800138000

  # 解密密文
  python nanjing_metro_crypto.py decrypt B355BC5470870AF51DB82E05261A44D8

  # 使用自定义密钥
  python nanjing_metro_crypto.py encrypt 13800138000 --key YOUR_KEY

  # 批量加密 (每行一个手机号)
  python nanjing_metro_crypto.py batch_encrypt phones.txt

  # 批量解密 (每行一个密文)
  python nanjing_metro_crypto.py batch_decrypt encrypted.txt

  # 输出到文件
  python nanjing_metro_crypto.py batch_encrypt phones.txt -o result.txt
        """
    )
    parser.add_argument('mode',
                        choices=['encrypt', 'decrypt', 'batch_encrypt', 'batch_decrypt'],
                        help='操作模式: encrypt/decrypt/batch_encrypt/batch_decrypt')
    parser.add_argument('content',
                        help='加密/解密: 内容 | 批量: 文件路径')
    parser.add_argument('--key', '-k', default=DEFAULT_KEY,
                        help=f'密钥 (默认: {DEFAULT_KEY})')
    parser.add_argument('--charset', '-c', default='utf-8',
                        help='字符编码 (默认: utf-8)')
    parser.add_argument('--output', '-o', default=None,
                        help='输出文件路径 (批量模式)')
    parser.add_argument('--lowercase', action='store_true',
                        help='加密输出使用小写 hex')

    args = parser.parse_args()

    try:
        if args.mode == 'encrypt':
            result = encrypt(args.content, args.key, args.charset)
            if args.lowercase:
                result = result.lower()
            print(f"[+] {args.content}")
            print(f"[=] {result}")

        elif args.mode == 'decrypt':
            result = decrypt(args.content, args.key, args.charset)
            print(f"[+] {args.content}")
            print(f"[=] {result}")

        elif args.mode == 'batch_encrypt':
            results = batch_encrypt(args.content, args.key, args.charset)
            output_lines = []
            for plain, enc in results:
                if args.lowercase:
                    enc = enc.lower()
                print(f"{plain} -> {enc}")
                output_lines.append(f"{plain}\t{enc}")
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(output_lines))
                print(f"\n[*] 已保存至: {args.output}")

        elif args.mode == 'batch_decrypt':
            results = batch_decrypt(args.content, args.key, args.charset)
            output_lines = []
            for enc, plain in results:
                print(f"{enc} -> {plain}")
                output_lines.append(f"{enc}\t{plain}")
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(output_lines))
                print(f"\n[*] 已保存至: {args.output}")

    except FileNotFoundError:
        print(f"[!] 文件未找到: {args.content}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[!] 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
