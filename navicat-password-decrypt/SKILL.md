---
name: navicat-password-decrypt
description: 解密 Navicat 保存的连接密码（Pwd 密文 → 明文），支持反向加密与一键扫描本机注册表。复刻 navicat解密码.php 的两套算法：v11（Blowfish+XOR 链）与 v12（AES-128-CBC），可自动识别版本、批量解密。当用户提到"Navicat 密码""解密 Navicat 保存的密码""数据库连接密码忘了/是什么""Pwd 字段/注册表里的密文""Navicat 导出 .ncx 密码"，或贴出一串大写 Hex 要求还原 Navicat 密码时使用。
version: 1.0.0
---

# Navicat 保存密码解密

把 Navicat 存下来的大写 Hex 密文还原成明文密码，也可反向生成密文。全部本地计算，不联网；`scan` 只读注册表，不写任何东西。

## 依赖

Python 3 + `pycryptodome`（本机 3.13.13 / 3.23.0 已就绪）：

```bash
pip install pycryptodome
```

不要用 `navicat解密码.php` 跑：本机没装 PHP，那个文件只是算法出处。

## 快速使用

工具位置：`skills/navicat-password-decrypt/navicat_password.py`（在本技能目录下执行）

```bash
cd ~/.qoder/skills/navicat-password-decrypt

# 1) 解本机所有 Navicat 保存的密码（只读扫描注册表，默认打码）
python navicat_password.py scan
python navicat_password.py scan --show          # 需要看明文时

# 2) 解一条给定密文（默认自动识别版本）
python navicat_password.py decrypt 15057D7BA390 --verify

# 3) 指定版本
python navicat_password.py decrypt -v 12 5F9DD421E77777132EC4881C27E3A21C

# 4) 批量
python navicat_password.py decrypt --csv 15057D7BA390 A2B8691DCB5A0200856F

# 5) 反向加密（算出可回填的密文）
python navicat_password.py encrypt "My_P@ss123" -v 11
```

Windows 控制台中文乱码时加前缀 `PYTHONUTF8=1`（脚本内部已强制 UTF-8 输出）。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `scan` / `decrypt` / `encrypt` | — | 子命令 |
| `cipher` / `plain` | 必填（后两个子命令） | 位置参数，可给多个，空格分隔 |
| `-v` / `--version` | decrypt/scan=0(自动)，encrypt=12 | `11` / `12`；`0` 仅解密可用 |
| `--verify` | 关 | 解密后再加密比对，输出 `[roundtrip OK/DIFF]` |
| `--csv` | 关 | 输出 `cipher,plain,version` 三列，方便贴表格 |
| `scan --value` | `Pwd` | 注册表值名（精确匹配，不分大小写） |
| `scan --show` | 关 | 打印明文；默认打码成 `ab***yz (len=7)` |

## 两套算法与版本判定

| 项目 | v11 | v12 |
|---|---|---|
| 分组 | Blowfish-ECB，8 字节 | AES-128-CBC，16 字节 |
| 密钥 | `sha1("3DC5CA39", raw)`（20 字节） | `libcckeylibcckey` |
| IV | `d9c7c3c8870d64bd` | `libcciv libcciv `（末尾一个空格） |
| 填充 | 无，尾部不足 8 字节走 XOR 段 | PKCS7 |
| 密文长度 | 任意 | 必为 32 个 Hex 字符的整数倍 |
| 明文长度 | **等于密文字节数** | ≤ 密文字节数，去掉填充 |

**别拿 Navicat 版本号硬套算法。** 本机 Navicat 17 注册表里的 19 条 `Pwd`（密文 5–20 字节，均非 16 的倍数）全部由 **v11** 解出，19/19 纯 ASCII。所以判定顺序是：

1. 先 `decrypt`（auto）：脚本按"先 v12 后 v11，取可打印字符占比最高者"选，平局时优先 v12。
2. 带 `--verify` 复核：回环一致 + 可信度 1.00 才算解对。
3. 长度不是 16 倍数却按 v12 解，必然失败——这是最常见的误判来源。

## 密文在本机哪里（Windows，实测）

连接按数据库产品分开存放，产品根不止 `NavicatPremium`：

```
HKCU\Software\PremiumSoft\{Navicat, NavicatPremium, NavicatPG, NavicatOra, NavicatMSSQL,
                           NavicatMARIADB, NavicatRedis, NavicatSQLite, NavicatDAMENG,
                           NavicatSnowflake, NavicatMongoDB}\...
```

本机实测的分布规律（**整棵树约 5000–8500 个键，别猜路径，按值名递归找**）：

| 位置 | 有没有密码 |
|---|---|
| `<产品>\Servers\<连接名>` | 只有 `SavePassword_2`/`SSH_SavePassword` 等标志位，**没有** `Pwd` |
| `<产品>\CloudProjectServers\<profile-uuid>\<project-uuid>\<连接名>` | `Pwd`＝v11 密文，可解；同级 `Host`/`Port`/`UserName` 用于确认是哪个连接 |
| 同上 `Pwd_2` | 88/120 Hex（44/60 字节），**两套常量都解不出**，属另一套密钥，本技能不支持 |

手工定位（Git Bash 里 `reg.exe` 的 `/s`、`/f` 会被 MSYS 当路径转换，必须加 `MSYS_NO_PATHCONV=1`，或写成 `//s`；两者叠加用会报"无效语法"）：

```bash
MSYS_NO_PATHCONV=1 reg query "HKCU\Software\PremiumSoft" /f Pwd /t REG_SZ /s
MSYS_NO_PATHCONV=1 reg query "HKCU\Software\PremiumSoft\Navicat\Servers"      # 列连接名
MSYS_NO_PATHCONV=1 reg query "HKCU\Software\PremiumSoft\Navicat\Servers\<连接名>" /v Pwd
```

顺带记：`<产品>` 根下的 `ProfilesPath` 指向 `Documents\Navicat\<产品>\profiles\`，里面是 `.<uuid>.nsyConn` 连接副本文件——本机未验证其中是否含可用密文，别当成取密文的主路径。

**macOS**：老版本看 `~/Library/Preferences/com.prect.Navicat*.plist`，新版本看 `~/Library/Application Support/PremiumSoft CyberTech/`，字段同样叫 `Pwd`（本机未验证）。

**`.ncx` 导出文件 / 启用主密码**：容器整体加密，`Pwd` 不是裸 Hex，本技能不适用。

## 验证样例

| 密文 | 版本 | 明文 |
|---|---|---|
| `15057D7BA390` | 11 | `123456` |
| `5F9DD421E77777132EC4881C27E3A21C` | 12 | `My_P@ss123` |
| `DC2BFF20CE396F7F92E5` | 11 | `My_P@ss123` |

第一条取自 `navicat解密码.php` 的原注释，可自检移植是否正确：

```bash
python navicat_password.py decrypt 15057D7BA390 --verify   # 期望 123456 / v11 / roundtrip OK
```

## 解出乱码怎么排

1. `-v 11`、`-v 12` 各试一次，排除 auto 误判。
2. 看长度：非 32 Hex 整数倍 → 只可能是 v11。
3. 确认密文完整、没夹引号/换行（脚本会去空格，但不会补丢失字符）。
4. 若字段是 `Pwd_2` 或来自 `.ncx`／主密码存储 → 不是这两套算法，停手，别硬猜。

## 作为模块调用

```python
import sys
sys.path.insert(0, r"<技能目录>")
from navicat_password import encrypt, decrypt, decrypt_auto

decrypt("15057D7BA390", version=11)      # -> '123456'（模块版 decrypt 默认 v12，必须显式传版本）
decrypt_auto("15057D7BA390")             # -> ('123456', 11, 1.0)  自动识别，等价于 CLI 默认行为
encrypt("My_P@ss123", version=11)        # -> 'DC2BFF20CE396F7F92E5'
```

## 文件

```
navicat-password-decrypt/
├── SKILL.md
├── navicat_password.py      # decrypt / encrypt / scan
└── navicat解密码.php         # 原始算法出处，本机无 PHP 不执行
```
