---
name: prod-metro-log-query
description: 查询地铁业务日志的阿里云 SLS 工具，只查生产环境（metro-* project，endpoint cn-shanghai），基于 aliyun-log-python-sdk。按城市与链路环节(卡管/前置/生码/收单/补登/支付)过滤 topic，支持开卡、生码、进站出站、请款退款、退卡、单边行程退卡等全链路追踪。当用户要求"查地铁日志""查地铁生产日志""开卡链路""生码链路""进站出站""请款退款""退卡""单边行程退卡""按手机号/订单号追踪""查询阿里云日志/SLS"时使用。
version: 1.3.0
---

# 地铁日志查询工具（阿里云 SLS）

使用 `aliyun-log-python-sdk` 查询阿里云日志服务（SLS）中的地铁业务日志，支持按城市与链路环节（卡管 / 前置 / 生码 / 收单 / 补登 / 支付）过滤，追踪开卡、生码、进站出站、请款退款、退卡、单边行程退卡等链路。

> **环境：只查生产。** `config.json` 里是单一 endpoint（`cn-shanghai.log.aliyuncs.com`）配一套 AccessKey，`cities.*.project` 全是 `metro-*` 系列，没有 SIT 那套配置，脚本也没有 `--env` 开关——不要用它找测试环境数据。技能名的 `prod-` 前缀就是标明这件事。
>
> 要查测试环境：SIT 应用日志走 `aliyun-log-query --env sit`（project `sityun-logs`），SIT 数据库走 `sit-database-query`。仓库里目前没有地铁链路的 SIT 日志技能，需要的话新建 `sit-metro-log-query`，别拿本技能凑。

## 文件位置

```
skills/prod-metro-log-query/
├── query_metro_log.py    # 主程序
├── config.example.json   # 脱敏模板（占位符密钥，可提交）
└── config.json           # 真实配置（含 AccessKey 明文，已 .gitignore，不提交）
```

## 首次使用

`config.json` 内含密钥，不入库。首次使用请从模板复制并填入真实 AccessKey：

```bash
cd skills/prod-metro-log-query
cp config.example.json config.json
# 编辑 config.json，把 accessKeyId / access_key 换成真实值
```

## 依赖安装

```bash
pip install aliyun-log-python-sdk
```

## 业务链路与环节(topic)

多条链路，日志按 `__topic__` 区分环节，且**不同城市同名环节的 topic 不一样**。`--service` 直接按环节取对应 topic：

| 链路 | 走向 | 涉及环节(--service) |
| --- | --- | --- |
| 开卡 | 用户 → 支付宝 → 卡管 → 前置 | `card`(卡管) → `front`(前置) |
| 生码 | 用户 → 支付宝 → 生码服务 → 外部地铁 | `getcode`(生码) |
| 进站出站 | 外部地铁 → 前置服务 → 收单服务 → 支付宝 | `front` → `receipt`(收单) |
| 请款退款 | 外部地铁 → 前置服务 → 收单服务 → 支付服务(ace-api) → 支付宝 | `front` → `receipt`(收单) → `pay`(支付，ace-api) |
| 退卡 | 外部地铁 → 前置服务 → 卡管 → 支付宝 | `front` → `card`(卡管) |
| 单边行程 | 外部地铁 → 城市前置服务 → 补登服务 → 支付宝 | `front` → `retro`(补登) |

各城市环节 topic 对照（已实测确认；`—` 表示走默认值）：

| 城市 | project | logstore | 卡管 card | 前置 front | 生码 getcode | 收单 receipt | 补登 retro | 支付 pay |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 北京 | metro-card | metro-card | integration | beijing-pre | beijing-getcode | metro-receipt | metro-retro | ace-api |
| 昆明 | metro-card | metro-card | integration | km-metro | getcode-spi | metro-receipt | metro-retro | ace-api |
| 成都 | metro-chengdu | chengdu-metro | chengdu-integration | chengdu-front | chengdu-qrcode | chengdu-receipt | chengdu-retro | chengdu-pay |
| 重庆 | metro-chongqing | metro_chongqing | integration | chongqing-pre | spi | receipt | metro-retro | ace-pay |
| 南京 | metro-nanjing | nanjing-metro | nanjing-integration | nanjing-metro | nanjing-spi | nanjing-receipt | nanjing-retro | nanjing-ace-pay |
| 南通 | metro-card | metro-card | nantong-integration | nantong-metro-pre | nantong-metro-getcode | nantong-metro-receipt | nantong-retro | nantong-ace-pay |

> 生码服务命名最乱：有 `<city>-getcode`、`<city>-spi`、`<city>-qrcode`、裸 `spi`(重庆)、`getcode-spi`(昆明)等，但内部 app 名都是 `<city>-apply-cert`/`<city>-getcode`，日志含「支付宝申请地铁乘车码」或「请求{城市}地铁 …/qrcode/auth_apply」。其余十余城市(东莞/青岛/福州/佛山/合肥/济南/金华/洛阳/南平/泰州/长春/无锡/呼和浩特)均已写入 config，收单/补登走默认 `metro-receipt`/`metro-retro`。

> 注意：`metro-chengdu`/`metro-nanjing`/`metro-chongqing` 是 **project** 名，其下 logstore 名并不相同（如 `chengdu-metro`）。北京、昆明、东莞、南通等无独立 project 的城市，日志统一落在共享的 `metro-card` project/logstore，用 topic 区分。

## 运行方式

```bash
cd skills/prod-metro-log-query

# 默认优先查 metro-card 共享库（不知城市时，按手机号全量搜）
python query_metro_log.py -q "17755752098" --from=-2d -n 50

# 指定城市追踪开卡全链路（卡管+前置，同一 traceId 串联）
python query_metro_log.py --metro 北京 -q "17755752098" --from=-2d -n 50

# 只看卡管环节
python query_metro_log.py --metro 北京 --service card -q "17755752098" --from=-2d

# 生码链路：只看城市生码服务（按订单号/手机号）
python query_metro_log.py --metro 昆明 --service getcode -q "7CF39FE1EAFA4B3DBB2D25C414AC842B" --from="2026-10-02 00:00:00" --to="2026-10-02 23:59:59"

# 进站出站 / 请款退款：收单环节
python query_metro_log.py --metro 南京 --service receipt -q "订单号" --from=-2d

# 请款退款：支付服务环节(ace-api)
python query_metro_log.py --metro 南京 --service pay -q "订单号" --from=-2d

# 退卡：前置 → 卡管
python query_metro_log.py --metro 南京 --service card -q "订单号" --from=-2d

# 单边行程退卡：补登环节
python query_metro_log.py --metro 成都 --service retro -q "订单号" --from=-2d

# 按 traceId 串起全链路（去掉 --service 查全部环节）
python query_metro_log.py -q "d796abd521d4db66" --from="2026-10-02 12:29:00" --to="2026-10-02 12:29:30"

# 直接指定 topic / logstore / project（覆盖城市配置）
python query_metro_log.py --metro 南京 --topic nanjing-integration -q "*" -n 20

# 列出所有 project 及其 logstore
python query_metro_log.py --discover
```

> `--from=-2d` 用等号连接，否则以 `-` 开头的值会被 argparse 当成选项。

## 参数说明

- `--metro`：城市名或别名（北京/beijing、成都/chengdu…）。**不填时默认优先查共享的 `metro-card` logstore**（覆盖北京、东莞、南通、青岛等十余城市，按 topic 区分），适合不知道属于哪个城市时先按手机号/bizNo 全量搜。
- `--service`：按链路环节选 topic —— `card`(卡管) / `front`(前置) / `getcode`(生码) / `receipt`(收单) / `retro`(补登) / `pay`(支付 ace-api) / `all`(全部，默认)。环节 topic 优先取城市配置，缺省回退 `default_<环节>_topic`。
- `--topic`：直接指定 `__topic__`，优先级高于 `--service`。
- `--project` / `--logstore`：直接指定，覆盖城市配置。
- `-q/--query`：查询语句（SLS 检索/SPL），默认 `*`。
- `--from` / `--to`：时间范围。支持 `-1h`/`-30m`/`-2d`、`now`、unix 时间戳、`YYYY-MM-DD[ HH:MM:SS]`。`--from` 默认取 `default_from`(-1h)，`--to` 默认 `now`。
- `-n/--line`：返回条数上限，默认取 `default_line`(100)。
- `--reverse`：时间倒序（最新在前）。
- `--json`：JSON 数组输出（含 time / topic / contents）。
- `--discover`：列出所有 project 及 logstore 后退出。

## 配置项（config.json）

> 由 `config.example.json` 复制而来，填入真实密钥后使用；`config.json` 已加入 `.gitignore`，`config.example.json` 中的 `accessKeyId`/`access_key` 为占位符。

- `endpoint` / `accessKeyId` / `access_key`：SLS 接入点与密钥。
- `default_city`：未指定 `--metro` 时使用的城市，默认 `metro-card`（共享库，优先查）。
- `default_card_topic` / `default_front_topic` / `default_getcode_topic` / `default_receipt_topic` / `default_retro_topic` / `default_pay_topic`：各环节 topic 的全局默认（收单 `metro-receipt`、补登 `metro-retro`、卡管 `integration`、支付 `ace-api`）。
- `cities`：城市 → `{aliases, project, logstore, card_topic?, front_topic?, getcode_topic?, receipt_topic?, retro_topic?, pay_topic?}`。某环节省略则回退对应 `default_*`。新增城市加一条即可。支付(ace-api)：成都 `chengdu-pay`、重庆 `ace-pay`、南京 `nanjing-ace-pay`、南通 `nantong-ace-pay`，其余城市走默认 `ace-api`。
- `default_line` / `default_from`：默认条数与默认起始时间。

## 追踪链路的技巧

1. 不知道城市/落点时，**默认（不加 `--metro`）先查 `metro-card` 共享库**，用手机号/bizNo/订单号全量搜，从命中的 topic（如 `beijing-pre`、`km-metro`）判断城市与环节。
2. 结果里的 `traceId`（如 `e0b1eab0f54f2ddc`）可串起同链路各环节日志。
3. 确定城市后用 `--metro 城市 --service card|front|getcode|receipt|retro` 分环节细查。
4. 判定“出票/退卡是否成功”：找卡管 `购票结果：出票成功` 或外部地铁返回 `code:10000 / msg:成功`。

## 新增城市

在 `config.json` 的 `cities` 下新增：

```json
"城市名": {
  "aliases": ["pinyin"],
  "project": "metro-xxx",
  "logstore": "xxx-metro",
  "card_topic": "xxx-integration",
  "front_topic": "xxx-front",
  "getcode_topic": "xxx-spi",
  "receipt_topic": "xxx-receipt",
  "retro_topic": "xxx-retro"
}
```

不确定某环节的 topic 时：先 `--discover` 找 logstore，再 `-q '* | SELECT DISTINCT "__topic__"'` 列出全部 topic，用关键字（integration/pre/spi/getcode/receipt/retro）对应到环节。

## 安全提示

- `config.json` 内含 AccessKey 明文，已通过 `.gitignore` 排除，**不要提交**。
- 仓库只保留脱敏模板 `config.example.json`（密钥字段为占位符 `<your-access-key-id>` / `<your-access-key-secret>`），可安全提交。
- 新克隆/新环境：先 `cp config.example.json config.json` 再填入真实密钥；换密钥只改本地 `config.json`，模板保持占位符。
