#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阿里云 SLS 通用日志查询（test/prod 双环境）。

依赖: pip install aliyun-log-python-sdk
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

try:
    from aliyun.log import LogClient, GetLogsRequest
except ImportError:
    sys.stderr.write("缺少依赖，请先执行: pip install aliyun-log-python-sdk\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

REL_RE = re.compile(r"^-(\d+)([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
PAGE_SIZE = 100


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.stderr.write(
            "缺少 %s。请先: cp config.example.json config.json 并填入真实 AccessKey\n" % CONFIG_PATH
        )
        sys.exit(2)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_envs(cfg, name):
    """返回 [(env_name, env_cfg)]。--env all 时返回全部环境。"""
    envs = cfg.get("envs") or {}
    if name == "all":
        return list(envs.items())
    if name not in envs:
        raise SystemExit("未配置环境 '%s'，可选: %s" % (name, ", ".join(envs.keys())))
    return [(name, envs[name])]


def make_client(cfg, env_cfg, endpoint_override):
    endpoint = endpoint_override or env_cfg.get("endpoint") or cfg.get("endpoint")
    ak = env_cfg.get("accessKeyId")
    sk = env_cfg.get("access_key")
    if not endpoint or not ak or not sk:
        raise SystemExit("配置缺少 endpoint / accessKeyId / access_key")
    return LogClient(endpoint, ak, sk)


def parse_time(value, now):
    """支持: now / -1h -30m -2d / unix 时间戳 / 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD'。"""
    if value is None:
        return None
    v = str(value).strip()
    if v.lower() == "now":
        return int(now)
    m = REL_RE.match(v)
    if m:
        return int(now - int(m.group(1)) * UNIT_SECONDS[m.group(2)])
    if v.isdigit():
        return int(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(v, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError("无法解析时间: %s" % value)


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def list_projects(client):
    resp = client.list_project(size=500)
    return [p["projectName"] for p in resp.get_projects()]


def list_stores(client, project):
    return client.list_logstore(project).get_logstores()


def fetch_logs(client, project, logstore, from_t, to_t, query, topic, line, offset, reverse):
    """普通检索按 100 条/页翻页取满 line 条；含 '|' 的分析语句单次请求。"""
    if "|" in query:
        req = GetLogsRequest(project, logstore, from_t, to_t, topic=topic, query=query,
                             line=line, offset=offset, reverse=reverse)
        return client.get_logs(req).get_logs()

    logs = []
    while len(logs) < line:
        n = min(PAGE_SIZE, line - len(logs))
        req = GetLogsRequest(project, logstore, from_t, to_t, topic=topic, query=query,
                             line=n, offset=offset + len(logs), reverse=reverse)
        got = client.get_logs(req).get_logs()
        logs.extend(got)
        if len(got) < n:
            break
    return logs


def fetch_topics(client, project, logstore, from_t, to_t):
    """优先用 SQL 去重；未开启 SQL 时回退为抽样 1000 条统计 __topic__。"""
    try:
        req = GetLogsRequest(project, logstore, from_t, to_t,
                             query='* | SELECT DISTINCT "__topic__" LIMIT 1000', line=1000)
        logs = client.get_logs(req).get_logs()
        return sorted({dict(l.contents).get("__topic__", "") for l in logs} - {""})
    except Exception:
        logs = fetch_logs(client, project, logstore, from_t, to_t, "*", "", 1000, 0, False)
        return sorted({dict(l.contents).get("__topic__", "") for l in logs} - {""})


def dump_json(logs):
    return [
        {
            "time": fmt_ts(l.timestamp),
            "topic": dict(l.contents).get("__topic__", ""),
            "contents": dict(l.contents),
        }
        for l in logs
    ]


def run_query(client, env_name, args, cfg, from_t, to_t, line):
    logs = fetch_logs(client, args.project, args.logstore, from_t, to_t,
                      args.query, args.topic, line, args.offset, args.reverse)
    if args.json:
        return dump_json(logs)
    sys.stderr.write(
        "[%s] project=%s logstore=%s topic=%s 时间[%s ~ %s] 命中 %d 条\n"
        % (env_name, args.project, args.logstore, args.topic or "(全部)",
           fmt_ts(from_t), fmt_ts(to_t), len(logs))
    )
    for l in logs:
        c = dict(l.contents)
        print("[%s][topic=%s] %s" % (fmt_ts(l.timestamp), c.get("__topic__", ""),
                                     json.dumps(c, ensure_ascii=False)))
    return None


def main():
    ap = argparse.ArgumentParser(description="查询阿里云 SLS 日志（test/prod 双环境）")
    ap.add_argument("--env", default=None, help="环境: test | prod | all，默认取配置 default_env(test)")
    ap.add_argument("-p", "--project", help="project 名")
    ap.add_argument("-l", "--logstore", help="logstore 名")
    ap.add_argument("--topic", default="", help="按 __topic__ 过滤")
    ap.add_argument("-q", "--query", default="*", help="查询语句/SPL，默认 * (全部)")
    ap.add_argument("--from", dest="from_t", help="起始时间: -1h/-30m/-2d/now/时间戳/'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--to", dest="to_t", default="now", help="结束时间，默认 now")
    ap.add_argument("-n", "--line", type=int, help="返回条数上限，默认取配置 (100)，超过 100 自动翻页")
    ap.add_argument("--offset", type=int, default=0, help="起始偏移，默认 0")
    ap.add_argument("--reverse", action="store_true", help="按时间倒序 (最新在前)")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--endpoint", help="覆盖接入点，如 cn-hangzhou.log.aliyuncs.com")
    ap.add_argument("--list-projects", "--discover", dest="list_projects", action="store_true",
                    help="列出所有 project 后退出")
    ap.add_argument("--list-logstores", metavar="PROJECT", help="列出指定 project 的 logstore")
    ap.add_argument("--list-topics", action="store_true", help="列出当前 project/logstore 的 __topic__ (需 -p -l)")
    args = ap.parse_args()

    cfg = load_config()
    env_name = args.env or cfg.get("default_env", "test")
    targets = resolve_envs(cfg, env_name)

    if args.list_projects:
        out = {}
        for name, env_cfg in targets:
            try:
                out[name] = list_projects(make_client(cfg, env_cfg, args.endpoint))
            except Exception as e:
                out[name] = "<失败: %s>" % e
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            for name, projects in out.items():
                print("[%s]" % name)
                if isinstance(projects, str):
                    print("  " + projects)
                else:
                    for p in projects:
                        print("  " + p)
        return

    if args.list_logstores:
        for name, env_cfg in targets:
            try:
                stores = list_stores(make_client(cfg, env_cfg, args.endpoint), args.list_logstores)
                print("[%s] %s: %s" % (name, args.list_logstores, ", ".join(stores)))
            except Exception as e:
                print("[%s] %s: <失败: %s>" % (name, args.list_logstores, e))
        return

    if not args.project or not args.logstore:
        raise SystemExit("查询/列举 topic 需要同时指定 --project 和 --logstore（可先 --list-projects）")

    now = time.time()
    from_raw = args.from_t or ("-1d" if args.list_topics else cfg.get("default_from", "-1h"))
    from_t = parse_time(from_raw, now)
    to_t = parse_time(args.to_t, now)
    line = args.line or int(cfg.get("default_line", 100))

    results = {}
    for name, env_cfg in targets:
        client = make_client(cfg, env_cfg, args.endpoint)
        if args.list_topics:
            topics = fetch_topics(client, args.project, args.logstore, from_t, to_t)
            print("[%s] topics(%s): %s" % (name, args.project, ", ".join(topics) or "(无)"))
            continue
        try:
            results[name] = run_query(client, name, args, cfg, from_t, to_t, line)
        except Exception as e:
            sys.stderr.write("[%s] 查询失败: %s\n" % (name, e))
            if len(targets) == 1:
                sys.exit(1)

    if args.json and results:
        if len(results) == 1:
            print(json.dumps(next(iter(results.values())), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
