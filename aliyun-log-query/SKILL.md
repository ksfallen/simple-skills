---
name: aliyun-log-query
description: 阿里云日志服务(SLS)通用查询工具，基于 aliyun-log-python-sdk，内置 sit(citytsm)/prod(allcitygo) 两套 AccessKey。支持列出 project、logstore、topic，按关键词/SPL、时间范围、条数检索日志。当用户要求"查阿里云日志""查 SLS""查 SIT/生产日志""查某服务 topic 日志""列日志库""按 traceId/订单号/手机号查日志"时使用。
version: 1.0.0
---

# 阿里云日志查询（SLS）

用 `aliyun-log-python-sdk` 查询阿里云日志服务，支持 sit / prod 双环境，均可列举 project、logstore、topic 并按条件检索。

## 文件位置

```
skills/aliyun-log-query/
├── SKILL.md
├── query_aliyun_log.py   # 主程序
├── config.example.json   # 脱敏模板（占位符密钥，可提交）
└── config.json           # 真实配置（含 AccessKey 明文，已 .gitignore，不提交）
```

## 依赖

```bash
pip install aliyun-log-python-sdk
```

## 首次使用

`config.json` 不入库。新环境先复制模板再填真实 AccessKey：

```bash
cd skills/aliyun-log-query
cp config.example.json config.json
```

## 运行方式

```bash
cd skills/aliyun-log-query

# 列出环境下的所有 project（不填 --env 默认 sit）
python query_aliyun_log.py --env prod --list-projects

# 列出某 project 的 logstore
python query_aliyun_log.py --env prod -p <project> --list-logstores <project>

# 列出某 logstore 的 topic（默认统计近 1 天，可用 --from 扩大）
python query_aliyun_log.py --env prod -p <project> -l <logstore> --list-topics --from=-7d

# 按关键词查最近 2 天，最多 50 条
python query_aliyun_log.py --env prod -p <project> -l <logstore> -q "traceId" --from=-2d -n 50

# 指定绝对时间；-n 超过 100 会自动翻页取满
python query_aliyun_log.py --env prod -p <project> -l <logstore> -q "订单号" \
  --from="2026-10-29 00:00:00" --to="2026-10-29 23:59:59" -n 300

# 只看某 topic、按时间倒序
python query_aliyun_log.py --env prod -p <project> -l <logstore> --topic xxx -q "*" --from=-1h --reverse -n 20

# SPL 分析语句（含 | 时单次请求，行数受 SQL LIMIT 控制）
python query_aliyun_log.py --env prod -p <project> -l <logstore> \
  -q '* | SELECT count(*) AS c' --from=-1h

# 同时查 sit 和 prod，对比同一关键字
python query_aliyun_log.py --env all -p <project> -l <logstore> -q "traceId" --from=-1h

# JSON 输出（Windows 建议重定向到文件，避免控制台编码问题）
PYTHONIOENCODING=utf-8 python query_aliyun_log.py --env prod -p <project> -l <logstore> \
  -q "*" --from=-1h --json > logs.json
```

> `--from=-2d` 必须用等号，否则以 `-` 开头的值会被 argparse 当成选项。

## 参数说明

- `--env`：`sit` / `prod` / `all`，默认取 `default_env`（sit）。`all` 依次查两个环境，JSON 输出为 `{env: [...]}`。
- `--project` / `-p`、`--logstore` / `-l`：查询必需；列举 project 时不需要。
- `--topic`：按 `__topic__` 精确过滤。
- `-q/--query`：SLS 检索语句，默认 `*`（全部）。支持 `key:value`、`and/or`、引号短语；含 `|` 视为 SPL 分析语句。
- `--from` / `--to`：支持 `-1h`/`-30m`/`-2d`、`now`、unix 时间戳、`YYYY-MM-DD[ HH:MM:SS]`。`--from` 默认 `-1h`（`--list-topics` 默认 `-1d`），`--to` 默认 `now`。
- `-n/--line`：条数上限，默认 100。普通检索超过 100 自动按 100/页翻页；SPL 语句由 SQL `LIMIT` 控制。
- `--offset`：起始偏移。
- `--reverse`：时间倒序（最新在前）。
- `--json`：JSON 输出，单环境为数组（`time`/`topic`/`contents`），`--env all` 为按环境分组的对象。
- `--endpoint`：覆盖接入点（默认 `cn-hangzhou-finance.log.aliyuncs.com`）；project 在其他地域时可临时指定，如 `cn-hangzhou.log.aliyuncs.com`。
- `--list-projects`（别名 `--discover`）/ `--list-logstores <project>` / `--list-topics`：列举类命令。

## 配置项（config.json）

```json
{
  "endpoint": "cn-hangzhou-finance.log.aliyuncs.com",
  "default_env": "sit",
  "default_from": "-1h",
  "default_line": 100,
  "envs": {
    "sit":  { "account": "openapi@citytsm.onaliyun.com",
              "accessKeyId": "<ak>", "access_key": "<sk>",
              "endpoint": "cn-hangzhou.log.aliyuncs.com" },
    "prod": { "account": "openapi@allcitygo.onaliyun.com",
              "accessKeyId": "<ak>", "access_key": "<sk>",
              "endpoint": "cn-hangzhou-finance.log.aliyuncs.com" }
  }
}
```

- `account` 仅作备注；鉴权只用 `accessKeyId` / `access_key`。
- 环境级 `endpoint` 优先于顶层 `endpoint`，`--endpoint` 优先级最高。
- 新增环境：在 `envs` 下加一项即可，`--env` 直接可用。

## 已知日志位置

### SIT 应用日志（最常用）

```
env       sit                # 账号 openapi@citytsm，端点 cn-hangzhou
project   sityun-logs
logstore  qrcode
topic     <服务名>            # 如 equities-core、citytsm-tcapp-gateway
```

一个 logstore 承载 130+ 个服务的 topic，字段为 `content` + `__topic__`，另有 `__tag__:__hostname__` / `__tag__:__path__` 等采集标签。

```bash
# 列全部服务 topic
python query_aliyun_log.py --env sit -p sityun-logs -l qrcode --list-topics --from=-1d

# 查某服务最近 1 小时日志
python query_aliyun_log.py --env sit -p sityun-logs -l qrcode --topic citytsm-tcapp-gateway \
  -q "*" --from=-1h --reverse -n 50

# 按 traceId / 关键字 / 错误级别
python query_aliyun_log.py --env sit -p sityun-logs -l qrcode --topic equities-core \
  -q "ERROR" --from=-2h --reverse
```

### 生产应用日志

```
env       prod
endpoint  cn-hangzhou-finance.log.aliyuncs.com   # 华东1金融云(杭州)，注意不带 -1
project   ecard
logstore  citytsm-base   # 网关等：topic=citytsm-tcapp-gateway
          citytsm-oper   # 权益/运营类：topic=equities-core、equities-bm
          citytsm-qrcode # 乘车码及大批业务服务：topic=<服务名>
```

```bash
# 网关日志
python query_aliyun_log.py --env prod --endpoint cn-hangzhou-finance.log.aliyuncs.com \
  -p ecard -l citytsm-base --topic citytsm-tcapp-gateway -q "ERROR" --from=-1h --reverse

# 列某 logstore 的服务 topic
python query_aliyun_log.py --env prod --endpoint cn-hangzhou-finance.log.aliyuncs.com \
  -p ecard -l citytsm-oper --list-topics --from=-1d
```

> `ecard` 项目下有 40 个 logstore，按业务域拆分（base/oper/pay/qrcode/new-receipt/…），
> **服务日志不在固定 logstore 里**，找不到 topic 时要逐个 logstore 列 topic。

## 排查技巧

1. 不知道日志落在哪：先 `--list-projects`，再 `--list-logstores <project>`，最后 `--list-topics --from=-7d`。
2. 拿不到 topic 但确实有数据：该 logstore 可能没给 `__topic__` 建索引，直接按关键词 `-q` 查即可。
3. 返回 0 条先检查时间范围与索引（未开启查询分析/索引的字段无法检索）。
4. `SignatureNotMatch`：AccessKey ID 与 Secret 不配对（或密钥已禁用/轮换），需核对 `config.json`。
5. `ProjectNotExist`：先怀疑**端点地域不对**，再怀疑权限。金融云端点写错时同样是这个报错，且带 `-1` 的端点能解析成功但指向另一个地域。
6. 地域命名容易搞混（按阿里云规则 华东1=杭州、华东2=上海）：
   - 华东1金融云 → `cn-hangzhou-finance.log.aliyuncs.com`（**ecard 在这里**）
   - 华东2金融云 → `cn-shanghai-finance-1.log.aliyuncs.com`
   - 普通云 → `cn-hangzhou`
7. `IndexConfigNotExist`：该 logstore 未开索引，SQL 检索不可用，只能做列举或换有索引的库。

## 安全提示

- `config.json` 含 AccessKey 明文，已在 `.gitignore` 中排除，**不要提交**；仓库只保留脱敏模板 `config.example.json`。
- 密钥轮换时只改本地 `config.json`，模板保持占位符。
