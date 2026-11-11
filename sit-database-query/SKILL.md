---
name: sit-database-query
description: 查询和修改测试库 / SIT 数据库 / sityun 数据库记录，MySQL 地址 sit-yunrds.mysql.rds.aliyuncs.com:3306，内置 citytsm_pm(项目管理)、sit_op_equities_manager(权益中心)、sit_citytsm_cloud(云枢平台) 三个库。支持列出数据库、列出/搜索表、查看表结构、按关键字定位字段、执行 SELECT/SHOW/EXPLAIN，以及 INSERT/UPDATE/DELETE/REPLACE 改数据（需 --write，默认要求 WHERE，可 --dry-run 回滚）。禁止修改表结构和数据库配置。当用户说"查询测试库""查 sit 数据库""sityun数据库""sityun 数据库""测试环境数据库""SIT 库""test 库""改测试库数据""更新/删除某条测试数据""按订单号/手机号/用户ID 查某张表""看表结构/字段含义/表在哪"时使用。
version: 1.1.0
---

# SIT 数据库查询与受控改数据

用 pymysql 直连 SIT MySQL（5.7.44）。读操作默认可用；改数据必须显式加 `--write`。输出为管道分隔的文本表格，或 `--json`。

用户口头说的「**查询测试库**」「**sit 数据库**」「**sityun 数据库**」「sit 库」「测试环境数据库」「test 库」指的都是本技能；「云数据库 / 云枢库」通常指 `sit_citytsm_cloud`。

## 读写边界

**读**（无需开关）：`SELECT` / `SHOW` / `DESC` / `DESCRIBE` / `EXPLAIN` / `WITH`。

**改数据**（必须加 `--write`）：
- `INSERT` / `UPDATE` / `DELETE` / `REPLACE` 允许执行，脚本先 `START TRANSACTION`，成功后 `COMMIT`。
- `UPDATE` / `DELETE` **强制要求 WHERE**；确需全表操作才加 `--all-rows`。
- 加 `--dry-run` 执行后回滚，用于先看影响行数再正式跑。
- 只允许单条语句；写操作会打印 `affected_rows`。

**仍然禁止（无覆盖开关）**：
1. **改表结构**：`ALTER` / `CREATE` / `DROP` / `TRUNCATE` / `RENAME` / `ANALYZE` / `OPTIMIZE` / `REPAIR`。
2. **改数据库配置**：`SET` / `FLUSH` / `RESET` / `PURGE` / `KILL` / `GRANT` / `REVOKE` / `LOAD` / `CALL`；不改 `config.json` 的连接信息与账号密码（除非用户明确要求更换账号）；不把配置类表当业务数据改（`infra_config`、`system_dict_data`、`biz_config`、`sys_config` 等）。
3. `INTO OUTFILE/DUMPFILE`、`INTO @var`、多语句。

用户要求改表结构或库配置时，明确拒绝并建议走发布/工单流程。

## 文件位置

```
skills/sit-database-query/
├── SKILL.md
├── query_sit_db.py              # 主程序
├── config.example.json          # 脱敏模板（可提交）
├── config.json                  # 真实账号密码（已 .gitignore，不提交）
└── references/table-catalog.md  # 三个库的表清单与注释
```

## 依赖

```bash
pip install pymysql
```

## 首次使用

`config.json` 不入库，新环境先复制模板再填账号：

```bash
cd skills/sit-database-query
cp config.example.json config.json
```

## 运行方式

```bash
cd skills/sit-database-query

# 列出所有库（配置里的三个业务库会标注中文名）
python query_sit_db.py --list-dbs

# 列表 / 按名字模糊筛表
python query_sit_db.py -d pm --list-tables
python query_sit_db.py -d pm --list-tables --like '%order%'

# 看表结构（字段、类型、注释）
python query_sit_db.py -d pm -t project --describe

# 不知道字段在哪：按关键字搜表名/表注释/字段名/字段注释
python query_sit_db.py -d equities --find '手机'
python query_sit_db.py -d pm --find '订单'

# 直接查整表，可带条件/排序/条数
python query_sit_db.py -d pm -t city -n 10
python query_sit_db.py -d equities -t benefit_record -w "mobile='13800000000'" -n 5
python query_sit_db.py -d pm -t project --where "project_no='XXX'" --order-by "id desc" -n 20

# 自定义 SQL（自动补 LIMIT，已有 LIMIT 则不改）
python query_sit_db.py -d cloud --sql "SELECT id,username,nickname FROM system_users" -n 5
python query_sit_db.py -d equities --sql "SELECT status, COUNT(*) c FROM benefit_record GROUP BY status"

# 从文件读 SQL（长语句/多行）
python query_sit_db.py -d pm --sql-file ./q.sql

# 宽表竖排输出：一列一行
python query_sit_db.py -d cloud -t infra_api_error_log -n 2 -E

# JSON 输出（Windows 建议重定向到文件）
PYTHONIOENCODING=utf-8 python query_sit_db.py -d pm -t city -n 100 --json > rows.json
```

### 改数据（先 dry-run 再提交）

```bash
# UPDATE：必须带 WHERE；先回滚看影响行数
python query_sit_db.py -d pm --write --dry-run --sql \
  "UPDATE project SET remark='测试备注' WHERE project_no='2026020133010003'"

# 确认行数无误后正式提交
python query_sit_db.py -d pm --write --sql \
  "UPDATE project SET remark='测试备注' WHERE project_no='2026020133010003'"

# DELETE：同样强制 WHERE
python query_sit_db.py -d pm --write --sql "DELETE FROM project WHERE id=999999"

# INSERT / REPLACE
python query_sit_db.py -d pm --write --sql \
  "INSERT INTO city(area, province, city_code, city_name) VALUES('东区','江苏','320299','测试市')"

# 从文件执行多条改动前，建议拆成单条逐条跑（脚本只接受单条语句）
python query_sit_db.py -d pm --write --sql-file ./update.sql
```

写操作成功输出 `[write] 影响 N 行，已提交` 与 `affected_rows=N`；`--dry-run` 时显示 `已回滚（--dry-run，未提交）`。

## 参数说明

- `-d/--db`：库名或简称 **pm**=citytsm_pm、**equities**=sit_op_equities_manager、**cloud**=sit_citytsm_cloud；不填取 `default_db`。
- `-t/--table`：表名，配合 `--describe`、`-w`、`--order-by` 使用。
- `--sql` / `--sql-file`：直接执行 SQL；写语句需额外加 `--write`。
- `-w/--where`、`--order-by`：拼在 `SELECT * FROM 表` 后面（原样拼接，引号自行处理）。
- `-n/--limit`：返回行数上限，默认 100；SQL 无顶层 LIMIT 时自动追加。
- `--write`：允许 `INSERT/UPDATE/DELETE/REPLACE`；不加则写语句直接拒绝。
- `--dry-run`：写操作执行后回滚，只看影响行数。
- `--all-rows`：允许 `UPDATE/DELETE` 不带 WHERE（默认强制 WHERE）。
- `--json`：数组输出，字段名即列名；`-E/--vertical`：竖排，宽表更易读。
- `--max-cell`：单字段截断长度，默认 200（0 不截断），超长文本如 JSON 配置会自动截断。
- `--timeout`：查询超时秒数，默认 30（连接后设置 `max_execution_time`）。
- `--list-dbs [--like]`、`--list-tables [--like]`、`--describe`、`--find <kw>`：元数据类命令。

## 三个库

| 简称 | 库名 | 说明 | 常用表 |
| --- | --- | --- | --- |
| pm | citytsm_pm | 项目管理 | project / contract / cooperator / expense / fund / yy_* 结算报表 / sys_user |
| equities | sit_op_equities_manager | 权益中心 | benefit / benefit_record / benefit_record_fail / benefit_record_used / benefit_rule / prize / lucky_draw_record |
| cloud | sit_citytsm_cloud | 云枢平台 | system_users / system_user_role / system_tenant / system_oauth2_* / infra_api_access_log / system_login_log |

完整表清单见 `references/table-catalog.md`（快照，实际以 `--list-tables` 为准）。

## 安全与限制

- 读：`SELECT` / `SHOW` / `DESC` / `DESCRIBE` / `EXPLAIN`（`WITH` 放行但服务端为 MySQL 5.7，不支持 CTE）。
- 写数据：`INSERT/UPDATE/DELETE/REPLACE` 必须 `--write`；`UPDATE/DELETE` 无 WHERE 会被拒绝（除非 `--all-rows`）；单条语句限制依然生效。
- 写操作在显式事务中执行，成功即 `COMMIT`；`--dry-run` 则 `ROLLBACK`。没有跨语句事务，多条改动需逐条执行并自行判断。
- 改表结构与改库配置始终禁止，无绕过参数。
- 大表统计先加 `-n` 限制或用 `COUNT(*)`/`GROUP BY`，避免拉全量：`infra_api_access_log`、`system_oauth2_access_token`、`dwd_trans_info_32020002`、`benefit_record`、`lucky_draw_record` 都是十万级以上。
- 查询按 `gmt_create`/`create_time` 之类时间字段加条件时，注意字段是否有索引，否则易触发 `max_execution_time`。

## 排查技巧

1. 不知道表名：先 `--find 关键字`（按业务中文名搜字段注释命中率最高），再 `--describe`。
2. 查不到记录：确认 `-d` 选对库（`citytsm_pm` 与 `sit_citytsm_pm` 是两个库，业务在 `citytsm_pm`），再确认逻辑删除字段（如 `del_flag`）与租户字段（`tenant_id`）。
3. `Unknown column`：先 `--describe` 核对字段；`_copy1` 结尾的是历史备份表，一般不用。
4. 输出乱码：设置 `PYTHONIOENCODING=utf-8`；重定向到文件时同样需要。
5. 连接超时/拒绝：确认当前网络在 SIT 白名单内；`--timeout` 只影响查询，不影响连接（连接超时 10s，见 config）。

## 安全提示

- `config.json` 含数据库账号密码明文，已在 `.gitignore` 中排除，**不要提交**；仓库只保留占位模板 `config.example.json`。
- 该账号仅用于 SIT 环境，勿指向生产库。
- 改数据前先 `--dry-run` 确认影响行数；`DELETE/UPDATE` 务必核对 WHERE 条件与 `affected_rows`。该账号具备写权限，误操作无法自动回滚。
