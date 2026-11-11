---
name: nanjing-metro-crypto
version: 1.0.0
description: 南京地铁手机号 AES 加解密工具。复现 Java EncryptUtils（SHA1PRNG 密钥派生 + AES/ECB/PKCS5Padding），支持单条和批量加解密。当用户提到南京地铁、手机号加解密、EncryptUtils、AES 加密解密手机号时使用。
---

# 南京地铁手机号加解密

复现 Java `EncryptUtils` 的 AES 加解密逻辑，默认密钥 `7c5b4cbf35eb4e2db962d0702ae819a3`。

> 环境：**不区分**。这套密钥测试与生产通用，不需要按环境换 `--key`，也不存在"解出来是乱码是因为环境不对"这种情况——解不出就先查输入本身（是否漏字符、是否非 Hex）。

## 脚本位置

`nanjing_metro_crypto.py`（本技能目录内）

## 依赖

需要 `pycryptodome`：

```bash
pip install pycryptodome
```

## 使用方式

### 命令行

```bash
# 加密
python <技能目录>/nanjing_metro_crypto.py encrypt 13800138000

# 解密
python <技能目录>/nanjing_metro_crypto.py decrypt 2EC920FF8B690A1E8AACBB7711FAEC0E

# 自定义密钥
python <技能目录>/nanjing_metro_crypto.py encrypt 13800138000 --key YOUR_KEY

# 批量加密（文件每行一个手机号）
python <技能目录>/nanjing_metro_crypto.py batch_encrypt phones.txt -o result.txt

# 批量解密
python <技能目录>/nanjing_metro_crypto.py batch_decrypt encrypted.txt -o result.txt
```

### 作为模块导入

```python
import sys
sys.path.insert(0, r"<技能目录>")
from nanjing_metro_crypto import encrypt, decrypt

# 加密（使用默认密钥）
cipher_text = encrypt("13800138000")

# 解密
plain_text = decrypt(cipher_text)

# 自定义密钥
cipher_text = encrypt("13800138000", key="your_key_here")
plain_text = decrypt(cipher_text, key="your_key_here")
```

## 算法说明

| 项目 | 值 |
|------|-----|
| 算法 | AES-128 |
| 模式 | ECB |
| 填充 | PKCS5Padding |
| 密钥派生 | SHA1PRNG: `SHA1(SHA1(seed_bytes))[:16]` |
| 输出 | 大写 Hex |
| 默认密钥 | `7c5b4cbf35eb4e2db962d0702ae819a3` |

## 验证示例

- 密文 `2EC920FF8B690A1E8AACBB7711FAEC0E`（默认密钥）→ 明文 `15850545978`
- 密文 `252CD13AAB94D20AC72637856A9B11660FDDD0EF5DE60E4961A4EF313F79D54D`（默认密钥）→ 明文 `320381199112255279`
