#!/usr/bin/env python3
"""Chat with configurable DingTalk bots via the dws CLI.

Bots are defined in config.json (next to this script). Each bot entry has an
open_dingtalk_id and, for group mode, a group_id/group_name. Pick a bot with
--bot <key>; the default is config["default_bot"].

Modes:
  single (default) -- send a 1:1 message to the bot as the current user, then
                      try to read its reply. NOTE: reading a cross-org 1:1
                      history needs a host-owned PAT; in a plain CLI env the
                      read is denied, so the reply may be unavailable. The
                      script detects this and tells you to use --mode group.
  group            -- @mention the bot inside an internal group, then poll the
                      group history for the bot's new reply. This path works in
                      a plain CLI env (internal group, no cross-org read).

The DingTalk "通过AI发送" corner tag is OFF by default (--ai-tag=false).
Use --ai-tag to re-enable it.

Examples:
  python chat_with_bot.py --list-bots
  python chat_with_bot.py --message "hi"
  python chat_with_bot.py --bot 告警监控排查 --mode group --message "查 xxx 告警"
"""
import argparse
import json
import os
import subprocess
import sys
import time

# Windows consoles default to GBK; force UTF-8 so emoji/Chinese print safely.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

FALLBACK_CONFIG = {
    "default_bot": "告警监控排查",
    "ai_tag": False,
    "bots": {
        "告警监控排查": {
            "open_dingtalk_id": "D9GBiiNCobX3uyBHgWQjEEtVF9FhdV5nH5",
            "group_id": "cidP4LVW+aXVBDMTkcv67QWJA==",
            "group_name": "小助手",
        }
    },
}


def load_config():
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARN: bad config.json ({exc}); using fallback defaults.")
    return FALLBACK_CONFIG


def find_dws():
    env = os.environ.get("DWS_BIN")
    if env:
        return env
    home = os.path.expanduser("~")
    for cand in (
        os.path.join(home, ".local", "bin", "dws.exe"),
        os.path.join(home, ".local", "bin", "dws"),
        os.path.join(home, ".qoder", "bin", "dws.exe"),
        os.path.join(home, ".qoder", "bin", "dws"),
    ):
        if os.path.isfile(cand):
            return cand
    return "dws"


DWS = find_dws()


def run(args):
    """Run a dws command, return parsed JSON dict.

    dws may emit its JSON error envelope on stdout OR stderr, so parse whichever
    stream carries JSON and keep the raw text for substring-based detection.
    """
    cmd = [DWS] + args + ["--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    out = (proc.stdout or "").strip()
    errtext = (proc.stderr or "").strip()
    for blob in (out, errtext):
        if not blob:
            continue
        try:
            parsed = json.loads(blob)
            if isinstance(parsed, dict):
                parsed["_raw"] = (out + "\n" + errtext).strip()
                return parsed
        except json.JSONDecodeError:
            continue
    combined = (out + "\n" + errtext).strip()
    return {"success": False, "errorMsg": combined[:800] or "empty output", "_raw": combined}


def die(msg, code=1):
    print(f"ERROR: {msg}")
    sys.exit(code)


def send_single(bot_id, message, ai_tag):
    args = ["chat", "message", "send", "--open-dingtalk-id", bot_id, "--content", message]
    if not ai_tag:
        args.append("--ai-tag=false")
    return run(args)


def send_group(group_id, bot_id, message, ai_tag):
    args = [
        "chat", "message", "send",
        "--conversation-id", group_id,
        "--at-open-dingtalk-ids", bot_id,
        "--content", f"<@{bot_id}> {message}",
    ]
    if not ai_tag:
        args.append("--ai-tag=false")
    return run(args)


def list_group(group_id, limit=25):
    r = run(["chat", "message", "list", "--conversation-id", group_id, "--limit", str(limit)])
    return r.get("messages", []) if isinstance(r, dict) else []


def list_single(bot_id, limit=10):
    return run(["chat", "message", "list", "--open-dingtalk-id", bot_id, "--limit", str(limit)])


def bot_message_ids(messages, bot_id):
    return {
        (m.get("messageId") or m.get("openMessageId"))
        for m in messages
        if m.get("sendType") == "robot" and m.get("senderId") == bot_id
    }


def is_cross_org_denied(resp):
    if not isinstance(resp, dict):
        return False
    err = resp.get("error") or {}
    raw = resp.get("_raw") or ""
    if err.get("server_error_code") == "CrossOrgPermissionDenied":
        return True
    return ("CrossOrgPermissionDenied" in raw
            or "跨组织" in raw
            or "没有跨组织拉取权限" in (err.get("message") or ""))


def poll_group_reply(group_id, bot_id, seen_ids, wait, quiet=6, interval=3):
    """Poll group history until the bot posts new message(s) and goes quiet."""
    deadline = time.time() + wait
    collected = []
    collected_ids = set()
    last_new = time.time()
    while time.time() < deadline:
        time.sleep(interval)
        msgs = list_group(group_id, limit=25)
        fresh = [
            m for m in msgs
            if m.get("sendType") == "robot"
            and m.get("senderId") == bot_id
            and (m.get("messageId") or m.get("openMessageId")) not in seen_ids
            and (m.get("messageId") or m.get("openMessageId")) not in collected_ids
        ]
        if fresh:
            collected.extend(fresh)
            collected_ids |= {(m.get("messageId") or m.get("openMessageId")) for m in fresh}
            seen_ids |= collected_ids
            last_new = time.time()
        elif collected and (time.time() - last_new) >= quiet:
            break
    collected.sort(key=lambda m: m.get("createTime", ""))
    return collected


def main():
    cfg = load_config()
    bots = cfg.get("bots", {}) or {}
    default_bot = cfg.get("default_bot") or (next(iter(bots), None))

    ap = argparse.ArgumentParser(description="Chat with configurable DingTalk bots via dws CLI.")
    ap.add_argument("--message", "-m", help="message content to send")
    ap.add_argument("--mode", choices=["single", "group"], default="single",
                    help="single = 1:1 (default); group = @bot in an internal group")
    ap.add_argument("--bot", default=default_bot, help=f"bot key from config.json (default: {default_bot})")
    ap.add_argument("--bot-id", help="override bot openDingTalkId")
    ap.add_argument("--group-id", help="override group openConversationId (group mode)")
    ap.add_argument("--wait", type=int, default=30, help="max seconds to wait for reply (group mode)")
    ap.add_argument("--send-only", action="store_true", help="send but do not read a reply")
    ap.add_argument("--ai-tag", action="store_true",
                    help="enable the DingTalk 通过AI发送 corner tag (off by default)")
    ap.add_argument("--list-bots", action="store_true", help="list configured bots and exit")
    args = ap.parse_args()

    if args.list_bots:
        print(f"default_bot: {default_bot}")
        for key, b in bots.items():
            mark = "*" if key == default_bot else " "
            print(f"{mark} {key}: id={b.get('open_dingtalk_id')} group={b.get('group_name','')}({b.get('group_id','')})")
        return

    if not args.message:
        die("--message is required (or use --list-bots)")
    if args.bot not in bots:
        die(f"unknown bot '{args.bot}'. Known: {', '.join(bots) or '(none)'}")

    entry = bots[args.bot]
    bot_id = args.bot_id or entry.get("open_dingtalk_id")
    group_id = args.group_id or entry.get("group_id")
    ai_tag = args.ai_tag or bool(cfg.get("ai_tag", False))

    if not bot_id:
        die(f"bot '{args.bot}' has no open_dingtalk_id in config.json")

    print(f"[dws] {DWS}")
    print(f"[bot] {args.bot} ({bot_id})  [mode] {args.mode}  [ai_tag] {ai_tag}")

    if args.mode == "single":
        resp = send_single(bot_id, args.message, ai_tag)
        if not resp.get("success"):
            die(f"send failed: {json.dumps(resp, ensure_ascii=False)[:500]}")
        print(f"[sent] single-chat message delivered. openTaskId={(resp.get('result') or {}).get('openTaskId')}")
        if args.send_only:
            return
        print("[read] attempting to fetch the bot's 1:1 reply ...")
        r = list_single(bot_id, limit=10)
        if is_cross_org_denied(r):
            print()
            print("REPLY UNAVAILABLE (cross-org restriction):")
            print("  Reading a 1:1 history with this cross-org bot needs a host-owned")
            print("  PAT/agentCode that a plain CLI session does not have. The message")
            print("  WAS sent; only the reply cannot be read here.")
            print("  -> Re-run with:  --mode group   (internal group read works).")
            return
        msgs = r.get("messages", []) if isinstance(r, dict) else []
        bot_msgs = [m for m in msgs if m.get("sendType") == "robot" and m.get("senderId") == bot_id]
        if bot_msgs:
            print()
            print("REPLY (latest bot message in 1:1):")
            print(bot_msgs[0].get("text", ""))
        else:
            print("[read] no bot reply found in 1:1 history yet.")
        return

    if not group_id:
        die(f"bot '{args.bot}' has no group_id; group mode needs one (or pass --group-id)")
    seen = bot_message_ids(list_group(group_id, limit=25), bot_id)
    resp = send_group(group_id, bot_id, args.message, ai_tag)
    if not resp.get("success"):
        die(f"send failed: {json.dumps(resp, ensure_ascii=False)[:500]}")
    print(f"[sent] @{args.bot} in group {group_id}. openTaskId={(resp.get('result') or {}).get('openTaskId')}")
    if args.send_only:
        return
    print(f"[read] polling group history up to {args.wait}s for the bot's reply ...")
    replies = poll_group_reply(group_id, bot_id, seen, wait=args.wait)
    if not replies:
        print("[read] no bot reply within the wait window.")
        return
    print()
    print(f"REPLY ({len(replies)} message(s) from {args.bot}):")
    for m in replies:
        print(f"--- [{m.get('createTime','')}] ---")
        print(m.get("text", ""))


if __name__ == "__main__":
    main()
