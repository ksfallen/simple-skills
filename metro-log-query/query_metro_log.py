#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询阿里云 SLS 地铁日志。

依赖: pip install aliyun-log-python-sdk
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

try:
    from aliyun.log import LogClient, GetLogsRequest
except ImportError:
    sys.stderr.write("缺少依赖，请先执行: pip install aliyun-log-python-sdk\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

REL_RE = re.compile(r"^-(\d+)([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_city(cfg, metro):
    """按城市名或别名匹配 config.cities，返回 (city_name, city_dict)。未匹配返回默认城市。"""
    cities = cfg.get("cities") or {}
    if metro:
        key = metro.strip()
        if key in cities:
            return key, cities[key]
        low = key.lower()
        for name, c in cities.items():
            if name.lower() == low or low in [a.lower() for a in c.get("aliases", [])]:
                return name, c
        sys.stderr.write(
            "未识别的城市 '%s'，可选: %s；已回退默认城市。\n"
            % (metro, ", ".join(cities.keys()))
        )
    default_name = cfg.get("default_city")
    if default_name and default_name in cities:
        return default_name, cities[default_name]
    return "", {}


def resolve_topic(cfg, city, args):
    """--topic 显式指定优先；否则按 --service 取卡管/前置 topic。"""
    if args.topic:
        return args.topic
    svc = (args.service or "all").lower()
    field_map = {
        "card": "card_topic",
        "front": "front_topic",
        "getcode": "getcode_topic",
        "receipt": "receipt_topic",
        "retro": "retro_topic",
        "pay": "pay_topic",
    }
    field = field_map.get(svc)
    if not field:
        return ""
    val = city.get(field)
    if val is None:
        val = cfg.get("default_" + field, "")
    return val or ""



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


def discover_project(client, logstore):
    """遍历所有 project，找到包含该 logstore 的 project（辅助排查用）。"""
    resp = client.list_project(size=500)
    for proj in [p["projectName"] for p in resp.get_projects()]:
        try:
            if logstore in client.list_logstore(proj).get_logstores():
                return proj
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description="查询阿里云 SLS 地铁日志")
    ap.add_argument("--metro", help="城市: 北京/成都/重庆/南京/... (见 config.cities)，默认取 default_city")
    ap.add_argument("--logstore", help="直接指定 logstore，覆盖城市配置")
    ap.add_argument("--project", help="直接指定 project，覆盖城市配置")
    ap.add_argument("-q", "--query", default="*", help="查询语句/SPL，默认 * (全部)")
    ap.add_argument("--service", choices=["card", "front", "getcode", "receipt", "retro", "pay", "all"], default="all",
                    help="按链路环节选 topic: card=卡管, front=前置, getcode=生码, receipt=收单, retro=补登, pay=支付(ace-api), all=全部(默认)")
    ap.add_argument("--topic", default="", help="直接指定 __topic__，覆盖 --service")
    ap.add_argument("--from", dest="from_t", help="起始时间: -1h/-30m/-2d/now/时间戳/'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--to", dest="to_t", default="now", help="结束时间，默认 now")
    ap.add_argument("-n", "--line", type=int, help="返回条数上限，默认取配置 (100)")
    ap.add_argument("--reverse", action="store_true", help="按时间倒序 (最新在前)")
    ap.add_argument("--json", action="store_true", help="以 JSON 数组输出")
    ap.add_argument("--discover", action="store_true", help="仅列出 project 及其 logstore 后退出")
    args = ap.parse_args()

    cfg = load_config()
    client = LogClient(cfg["endpoint"], cfg["accessKeyId"], cfg["access_key"])

    if args.discover:
        resp = client.list_project(size=500)
        for p in resp.get_projects():
            name = p["projectName"]
            try:
                stores = client.list_logstore(name).get_logstores()
            except Exception as e:
                stores = ["<读取失败: %s>" % e]
            print("%s: %s" % (name, ", ".join(stores)))
        return

    city_name, city = resolve_city(cfg, args.metro)
    project = args.project or city.get("project") or ""
    logstore = args.logstore or city.get("logstore") or ""
    topic = resolve_topic(cfg, city, args)
    if not project or not logstore:
        raise SystemExit("城市 '%s' 未配置 project/logstore，请用 --project/--logstore 指定。" % (city_name or args.metro))

    now = time.time()
    from_t = parse_time(args.from_t if args.from_t else cfg.get("default_from", "-1h"), now)
    to_t = parse_time(args.to_t, now)
    line = args.line or int(cfg.get("default_line", 100))

    req = GetLogsRequest(
        project, logstore, from_t, to_t,
        topic=topic, query=args.query, line=line, offset=0, reverse=args.reverse,
    )
    res = client.get_logs(req)
    logs = res.get_logs()

    if args.json:
        out = [
            {"time": datetime.fromtimestamp(l.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
             "topic": dict(l.contents).get("__topic__", ""),
             "contents": dict(l.contents)}
            for l in logs
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    sys.stderr.write(
        "城市=%s project=%s logstore=%s topic=%s 时间[%s ~ %s] 命中 %d 条\n"
        % (city_name or "-", project, logstore, topic or "(全部)",
           datetime.fromtimestamp(from_t).strftime("%Y-%m-%d %H:%M:%S"),
           datetime.fromtimestamp(to_t).strftime("%Y-%m-%d %H:%M:%S"),
           len(logs))
    )
    for l in logs:
        ts = datetime.fromtimestamp(l.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        c = dict(l.contents)
        tp = c.get("__topic__", "")
        print("[%s][topic=%s] %s" % (ts, tp, json.dumps(c, ensure_ascii=False)))


if __name__ == "__main__":
    main()
