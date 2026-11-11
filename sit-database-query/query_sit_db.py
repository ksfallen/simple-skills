#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIT 环境 MySQL 查询与受控改数据工具。

依赖: pip install pymysql
读: SELECT / SHOW / DESC / EXPLAIN / WITH
写数据: INSERT / UPDATE / DELETE / REPLACE，必须加 --write；UPDATE/DELETE 必须带 WHERE
禁止: 改表结构（ALTER/CREATE/DROP/TRUNCATE/RENAME）与改库配置（SET/GRANT/FLUSH 等）
"""
import argparse
import json
import os
import re
import sys

try:
    import pymysql
except ImportError:
    sys.stderr.write("缺少依赖，请先执行: pip install pymysql\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# 库简称 -> 全名
ALIASES = {
    "pm": "citytsm_pm",
    "equities": "sit_op_equities_manager",
    "cloud": "sit_citytsm_cloud",
}

WRITE_FIRST = {"insert", "update", "delete", "replace"}
ALLOWED_FIRST = {"select", "show", "desc", "describe", "explain", "with"} | WRITE_FIRST
# 改表结构 / 改库配置 / 管理类语句一律拒绝，不提供覆盖开关
BLOCKED = re.compile(
    r"\b(merge|drop|alter|create|truncate|rename|"
    r"grant|revoke|call|load|lock|unlock|prepare|execute|handler|do|"
    r"flush|reset|purge|kill|shutdown|analyze|optimize|repair|"
    r"install|uninstall|into\s+outfile|into\s+dumpfile|into\s+@)\b",
    re.I,
)
FORBIDDEN_NOTE = "（本工具禁止修改表结构和数据库配置）"


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.stderr.write(
            "缺少 %s。请先: cp config.example.json config.json 并填入真实账号密码\n" % CONFIG_PATH
        )
        sys.exit(2)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def connect(cfg, timeout):
    c = cfg.get("connection") or {}
    missing = [k for k in ("host", "user", "password") if not c.get(k)]
    if missing:
        raise SystemExit("config.json 的 connection 缺少: %s" % ", ".join(missing))
    conn = pymysql.connect(
        host=c["host"],
        port=int(c.get("port", 3306)),
        user=c["user"],
        password=c["password"],
        charset=c.get("charset", "utf8mb4"),
        connect_timeout=int(c.get("connect_timeout", 10)),
        read_timeout=timeout,
        autocommit=True,
        cursorclass=pymysql.cursors.Cursor,
    )
    cur = conn.cursor()
    try:
        cur.execute("SET SESSION max_execution_time = %d" % (timeout * 1000))
    except Exception:
        pass
    return conn


def resolve_db(name, cfg):
    if not name:
        return None
    n = name.strip()
    if n in ALIASES:
        return ALIASES[n]
    known = cfg.get("databases") or {}
    if n in known:
        return n
    raise SystemExit("未知库 '%s'。可用简称: %s；或 --list-dbs 查看全部库" % (
        name, ", ".join(sorted(ALIASES))))


def strip_literals(sql):
    """去掉注释与字符串字面量，用于只读校验与分号检测。"""
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            while i < n and sql[i] != "\n":
                i += 1
        elif ch == "#":
            while i < n and sql[i] != "\n":
                i += 1
        elif ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
        elif ch in ("'", '"', "`"):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def has_top_level_keyword(stripped, word):
    s = stripped.lower()
    n = len(word)
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and s.startswith(word, i):
            before = s[i - 1] if i > 0 else " "
            after = s[i + n] if i + n < len(s) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return True
        i += 1
    return False


def prepare_sql(raw, limit, allow_write=False, allow_all_rows=False):
    """校验语句、拒绝多语句、补充 LIMIT。返回 (可执行 SQL, read|write)。"""
    sql = raw.strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        raise SystemExit("SQL 为空")

    stripped = strip_literals(sql)
    if ";" in stripped:
        raise SystemExit("只允许单条语句（检测到多条 SQL）")

    first = (stripped.strip().split() or [""])[0].lower()
    if first not in ALLOWED_FIRST:
        raise SystemExit("不允许执行: %s%s" % (first.upper() or "(空)", FORBIDDEN_NOTE))
    hit = BLOCKED.search(stripped)
    if hit:
        raise SystemExit("语句包含禁止关键字: %s%s" % (hit.group(0).upper(), FORBIDDEN_NOTE))

    kind = "write" if first in WRITE_FIRST else "read"
    if kind == "write" and not allow_write:
        raise SystemExit("%s 属于写操作，需显式加 --write 才执行" % first.upper())
    if first in ("update", "delete") and not allow_all_rows \
            and not has_top_level_keyword(stripped, "where"):
        raise SystemExit("%s 必须带 WHERE 条件；确认要对全表生效请加 --all-rows" % first.upper())
    if first in ("select", "with") and not has_top_level_keyword(stripped, "limit"):
        sql = "%s LIMIT %d" % (sql, limit)
    return sql, kind


def fmt_val(v, max_cell):
    if v is None:
        return "NULL"
    if isinstance(v, (bytes, bytearray)):
        try:
            v = bytes(v).decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + bytes(v).hex()
    if isinstance(v, bool):
        v = int(v)
    s = str(v).replace("\r", " ").replace("\n", "\\n").replace("\t", "\\t")
    if max_cell and len(s) > max_cell:
        s = s[:max_cell] + "...(%d chars)" % len(s)
    return s


def to_json_val(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + bytes(v).hex()
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def print_result(cols, rows, args):
    if args.json:
        data = [dict(zip(cols, (to_json_val(v) for v in r))) for r in rows]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not rows:
        sys.stderr.write("命中 0 行\n")
        return
    if args.vertical:
        for idx, r in enumerate(rows, 1):
            print("*" * 8 + " row %d " % idx + "*" * 8)
            for c, v in zip(cols, r):
                print("%s: %s" % (c, fmt_val(v, args.max_cell)))
        return
    print(" | ".join(cols))
    print("-" * 40)
    for r in rows:
        print(" | ".join(fmt_val(v, args.max_cell) for v in r))


def run(conn, cur, sql, kind, args):
    if kind == "write":
        cur.execute("START TRANSACTION")
    cur.execute(sql)
    if kind == "write":
        affected = cur.rowcount
        if args.dry_run:
            conn.rollback()
            sys.stderr.write("[write] 影响 %d 行，已回滚（--dry-run，未提交）\n" % affected)
        else:
            conn.commit()
            sys.stderr.write("[write] 影响 %d 行，已提交\n" % affected)
        if args.json:
            print(json.dumps({"affected_rows": affected, "committed": not args.dry_run},
                             ensure_ascii=False))
        else:
            print("affected_rows=%d%s" % (affected, "" if not args.dry_run else " (rolled back)"))
        return
    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchmany(args.limit)
    more = len(cur.fetchmany(1)) > 0
    print_result(cols, rows, args)
    if not args.json:
        sys.stderr.write("命中 %d 行 (limit %d%s)\n" % (
            len(rows), args.limit, ", 还有更多" if more else ""))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_config()
    ap = argparse.ArgumentParser(description="SIT 环境 MySQL 查询与受控改数据")
    ap.add_argument("-d", "--db", help="库名或简称: pm | equities | cloud | 全名")
    ap.add_argument("-t", "--table", help="表名")
    ap.add_argument("--sql", help="直接执行 SQL（读默认允许；写需 --write）")
    ap.add_argument("--sql-file", help="从文件读取 SQL")
    ap.add_argument("-w", "--where", help="WHERE 条件，配合 -t 使用，如 \"user_id=1 AND status=1\"")
    ap.add_argument("--order-by", help="排序，如 \"create_time desc\"")
    ap.add_argument("-n", "--limit", type=int, help="返回行数上限，默认取配置 (100)")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("-E", "--vertical", action="store_true", help="竖排输出（宽表可读性好）")
    ap.add_argument("--max-cell", type=int, help="单字段截断长度，默认取配置 (200)，0 表示不截断")
    ap.add_argument("--timeout", type=int, help="查询超时秒数，默认取配置 (30)")
    ap.add_argument("--list-dbs", action="store_true", help="列出所有库")
    ap.add_argument("--list-tables", action="store_true", help="列出当前库的表（可配 --like）")
    ap.add_argument("--like", help="模糊匹配: 库名/表名 LIKE 模式，如 '%%order%%'")
    ap.add_argument("--describe", action="store_true", help="查看表结构，需 -t")
    ap.add_argument("--find", help="按关键字搜索本库的表名/表注释/字段名/字段注释")
    ap.add_argument("--write", action="store_true", help="允许执行 INSERT/UPDATE/DELETE/REPLACE")
    ap.add_argument("--dry-run", action="store_true", help="写操作执行后回滚，不提交（配合 --write）")
    ap.add_argument("--all-rows", action="store_true",
                    help="允许 UPDATE/DELETE 不带 WHERE（默认强制要求 WHERE）")
    args = ap.parse_args()

    args.limit = args.limit or int(cfg.get("default_limit", 100))
    args.max_cell = int(cfg.get("max_cell_chars", 200) if args.max_cell is None else args.max_cell)
    timeout = args.timeout or int(cfg.get("timeout", 30))
    if args.limit <= 0:
        raise SystemExit("--limit 必须为正数")

    db = resolve_db(args.db, cfg)
    conn = connect(cfg, timeout)
    cur = conn.cursor()

    try:
        if args.list_dbs:
            cur.execute("SHOW DATABASES")
            names = [r[0] for r in cur.fetchall()]
            if args.like:
                cur.execute("SHOW DATABASES LIKE %s", (args.like,))
                names = [r[0] for r in cur.fetchall()]
            known = cfg.get("databases") or {}
            for n in names:
                mark = "  <= " + known[n] if n in known else ""
                print("%s%s" % (n, mark))
            return

        if not db:
            db = cfg.get("default_db")
        if not db:
            raise SystemExit("请用 -d 指定库（或用 --list-dbs 查看）")

        if args.list_tables:
            sql = ("SELECT TABLE_NAME, TABLE_COMMENT, TABLE_ROWS FROM information_schema.TABLES "
                   "WHERE TABLE_SCHEMA=%s")
            params = [db]
            if args.like:
                sql += " AND TABLE_NAME LIKE %s"
                params.append(args.like)
            cur.execute(sql + " ORDER BY TABLE_NAME", params)
            print_result(["table_name", "comment", "rows(约)"],
                         cur.fetchall(), args)
            return

        if args.find:
            kw = "%" + args.find + "%"
            cur.execute(
                "SELECT c.TABLE_NAME, t.TABLE_COMMENT, c.COLUMN_NAME, c.COLUMN_TYPE, c.COLUMN_COMMENT "
                "FROM information_schema.COLUMNS c "
                "JOIN information_schema.TABLES t "
                "  ON t.TABLE_SCHEMA=c.TABLE_SCHEMA AND t.TABLE_NAME=c.TABLE_NAME "
                "WHERE c.TABLE_SCHEMA=%s AND "
                "(c.TABLE_NAME LIKE %s OR t.TABLE_COMMENT LIKE %s OR c.COLUMN_NAME LIKE %s OR c.COLUMN_COMMENT LIKE %s) "
                "ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION",
                (db, kw, kw, kw, kw))
            print_result(["table_name", "table_comment", "column_name", "column_type", "column_comment"],
                         cur.fetchall(), args)
            return

        cur.execute("USE `%s`" % db.replace("`", "``"))

        if args.describe:
            if not args.table:
                raise SystemExit("--describe 需要同时指定 -t 表名")
            cur.execute("SHOW FULL COLUMNS FROM `%s`" % args.table.replace("`", "``"))
            print_result(["Field", "Type", "Collation", "Null", "Key", "Default", "Extra", "Privileges", "Comment"],
                         cur.fetchall(), args)
            return

        if args.sql_file:
            with open(args.sql_file, "r", encoding="utf-8") as f:
                raw = f.read()
        elif args.sql:
            raw = args.sql
        elif args.table:
            sql = "SELECT * FROM `%s`" % args.table.replace("`", "``")
            if args.where:
                sql += " WHERE " + args.where
            if args.order_by:
                sql += " ORDER BY " + args.order_by
            raw = sql
        else:
            raise SystemExit("请指定 --sql / --sql-file / -t 表名，或 --list-tables / --describe / --find")

        sys.stderr.write("[%s] %s\n" % (db, raw if len(raw) <= 200 else raw[:200] + "..."))
        sql, kind = prepare_sql(raw, args.limit, args.write, args.all_rows)
        run(conn, cur, sql, kind, args)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except pymysql.MySQLError as e:
        code = e.args[0] if e.args else ""
        msg = e.args[1] if len(e.args) > 1 else str(e)
        sys.stderr.write("SQL 执行失败 [%s]: %s\n" % (code, msg))
        sys.exit(1)
    except KeyboardInterrupt:
        sys.stderr.write("已中断\n")
        sys.exit(130)
