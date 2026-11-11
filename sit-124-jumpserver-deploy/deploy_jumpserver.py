#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跳板机服务部署工具 (JumpServer 版)
通过 JumpServer 堡垒机 SSH 到目标服务器，列出服务并执行部署操作。

连接策略：
  本地 → paramiko SSH → JumpServer 堡垒机 → 交互式菜单选择 → 目标服务器
  通过 JumpServer 交互菜单搜索目标 IP，自动连接后在同一 channel 执行命令。

用法:
    python deploy_jumpserver.py                     # 交互式部署
    python deploy_jumpserver.py -l                  # 仅列出服务
    python deploy_jumpserver.py -s <服务名>          # 直接部署指定服务
    python deploy_jumpserver.py -s <服务名> -a <操作> # 直接执行指定操作

deploy_config.json配置：
"服务名": {
  "script_name": "脚本相对路径",
  "script_path": "/opt/xxx",
  "code_path": "/opt/xxx/code",
  "branch": "develop",
  "label": "中文名"
}
"""

import paramiko
import argparse
import re
import sys
import os
import socket
import time
import json

# ─── 跳板机和目标服务器配置 ───────────────────────────
# 跳板机地址与凭据从 deploy_config.json 的 jump 节点读取（该文件不入库，模板见 deploy_config.example.json）
JUMP_HOST = ""
JUMP_PORT = 2222
JUMP_USER = ""
JUMP_PASS = ""

TARGET_HOST = "sityun124"
TARGET_USER = "tsm"

SERVICES_DIR = "/opt"

# 配置文件路径（与脚本同目录）
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_config.json")

# 常见的部署脚本名称优先级
DEPLOY_SCRIPT_PRIORITY = [
    "deploy.sh", "start.sh", "restart.sh", "run.sh",
    "publish.sh", "build.sh", "install.sh",
]

# ─── 服务注册表 & 通用命令模板 ─────────────────────────
# 所有服务共享同一套子命令，脚本名自动替换
# {script} 会在运行时被替换为实际的脚本名（如 ./equities-core, ./citytsm-pm）
COMMON_COMMANDS = {
    "deploy":  {"cmd": "./{script} deploy",       "desc": "打包和部署服务"},
    "issue":   {"cmd": "./{script} issue",         "desc": "发布服务"},
    "restart": {"cmd": "./{script} rcmd restart",  "desc": "重启服务"},
    "stop":    {"cmd": "./{script} rcmd stop",     "desc": "停止服务"},
    "start":   {"cmd": "./{script} rcmd start",    "desc": "启动服务"},
    "verify":  {"cmd": "./{script} rcmd verify",   "desc": "验证服务运行状态"},
}
COMMAND_ORDER = ["deploy", "issue", "start", "stop", "restart", "verify"]


def _build_svc(script_name, script_path, code_path=None, branch="develop", label=None):
    """用通用命令模板构建单个服务的配置"""
    commands = {}
    for key, tpl in COMMON_COMMANDS.items():
        commands[key] = {"cmd": tpl["cmd"].format(script=script_name), "desc": tpl["desc"]}
    return {
        "script_name": script_name,
        "script_path": script_path,
        "code_path": code_path or script_path,
        "branch": branch,
        "label": label,
        "commands": commands,
        "command_order": COMMAND_ORDER[:],
    }


# 服务注册表：从 deploy_config.json 加载，新增服务编辑 JSON 文件即可
SERVICE_REGISTRY = {}


def load_service_registry():
    """从 deploy_config.json 加载服务注册表"""
    global SERVICE_REGISTRY
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    for name, cfg in data.get("services", {}).items():
        SERVICE_REGISTRY[name] = _build_svc(
            script_name=cfg.get("script_name", name),
            script_path=cfg["script_path"],
            code_path=cfg.get("code_path"),
            branch=cfg.get("branch", "develop"),
            label=cfg.get("label"),
        )


def load_jump_settings():
    """从 deploy_config.json 的 jump 节点读取跳板机地址与凭据"""
    global JUMP_HOST, JUMP_PORT, JUMP_USER, JUMP_PASS
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            jump = json.load(f).get("jump", {})
    except Exception:
        return
    JUMP_HOST = jump.get("host", JUMP_HOST)
    JUMP_PORT = int(jump.get("port") or JUMP_PORT)
    JUMP_USER = jump.get("user", JUMP_USER)
    JUMP_PASS = jump.get("password", JUMP_PASS)


load_jump_settings()


# ─── 终端颜色 ─────────────────────────────────────────

class Colors:
    ENABLED = os.environ.get("TERM") or (
        sys.platform == "win32" and os.environ.get("WT_SESSION")
    )
    GREEN  = "\033[92m" if ENABLED else ""
    YELLOW = "\033[93m" if ENABLED else ""
    RED    = "\033[91m" if ENABLED else ""
    CYAN   = "\033[96m" if ENABLED else ""
    BOLD   = "\033[1m"  if ENABLED else ""
    RESET  = "\033[0m"  if ENABLED else ""


def color(text, c):
    return f"{c}{text}{Colors.RESET}"


def log_info(msg):
    print(f"  {color('[INFO]', Colors.CYAN)} {msg}")

def log_ok(msg):
    print(f"  {color('[OK]', Colors.GREEN)} {msg}")

def log_warn(msg):
    print(f"  {color('[WARN]', Colors.YELLOW)} {msg}")

def log_err(msg):
    print(f"  {color('[ERR]', Colors.RED)} {msg}")


# ─── 配置持久化 ────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"scripts": {}}


def save_config(cfg):
    # 保留 services 配置不被覆盖
    existing = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(cfg)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ─── ANSI 工具函数 ─────────────────────────────────────

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]|\x07|\x1b\[[\?]?[0-9;]*[hlm]')

def strip_ansi(text):
    """移除 ANSI 转义序列"""
    return _ANSI_RE.sub('', text)


# ─── JumpServer 会话 ───────────────────────────────────

class JumpServerSession:
    """
    通过 JumpServer 堡垒机连接目标服务器的会话。

    流程:
      1. paramiko SSH 到 JumpServer
      2. 获取交互式 shell (伪终端)
      3. 读取 JumpServer 菜单
      4. 发送 /IP 搜索并选择目标资产
      5. 建立到目标的 SSH 连接
      6. 通过同一 channel 在目标上执行命令
    """

    def __init__(self, jump_host, jump_port, jump_user, jump_pass,
                 target_host, target_user):
        self.jump_host = jump_host
        self.jump_port = jump_port
        self.jump_user = jump_user
        self.jump_pass = jump_pass
        self.target_host = target_host
        self.target_user = target_user
        self._client = None
        self._chan = None

    # ── 连接与关闭 ──

    def connect(self):
        """连接到 JumpServer 堡垒机"""
        log_info(f"连接 JumpServer {self.jump_host}:{self.jump_port} ...")
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self.jump_host,
            port=self.jump_port,
            username=self.jump_user,
            password=self.jump_pass,
            timeout=30,
            banner_timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )
        log_ok("已连接 JumpServer")

    def close(self):
        """关闭会话"""
        if self._chan:
            try:
                self._chan.close()
            except Exception:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    # ── 交互式 Shell 底层操作 ──

    def _open_shell(self):
        """打开交互式伪终端"""
        self._chan = self._client.get_transport().open_session()
        self._chan.get_pty(term='xterm', width=200, height=50)
        self._chan.invoke_shell()
        self._chan.setblocking(0)

    def _send(self, text):
        """向 channel 发送文本"""
        self._chan.sendall(text.encode('utf-8'))

    def _sendline(self, text=""):
        """向 channel 发送一行（带换行）"""
        self._chan.sendall((text + '\n').encode('utf-8'))

    def _recv(self, max_bytes=4096):
        """非阻塞读取，返回解码后的字符串"""
        if self._chan.recv_ready():
            return self._chan.recv(max_bytes).decode('utf-8', errors='replace')
        return ""

    def _read_until(self, patterns, timeout=30, show=False, idle_gap=3):
        """
        持续读取直到匹配某个模式，或超时。

        参数:
            patterns: 字符串或正则列表，任一匹配即停止
            timeout:  最大等待秒数
            show:     是否实时打印到终端
            idle_gap: 无新数据超过此秒数也停止（用于长命令）

        返回: (累积的原始输出, 停止原因)
              原因: 'match' | 'idle' | 'timeout'
        """
        if isinstance(patterns, str):
            patterns = [re.escape(patterns)]
        compiled = [re.compile(p) for p in patterns]

        buf = ""
        start = time.time()
        last_data = time.time()

        while True:
            chunk = self._recv()
            if chunk:
                buf += chunk
                if show:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                last_data = time.time()

                # 检查模式匹配
                clean = strip_ansi(buf)
                for pat in compiled:
                    if pat.search(clean):
                        return buf, 'match'
            else:
                # 无数据时检查空闲超时
                if buf and (time.time() - last_data > idle_gap):
                    return buf, 'idle'
                time.sleep(0.05)

            # 检查总超时
            if time.time() - start > timeout:
                return buf, 'timeout'

    # ── 连接目标服务器 ──

    def connect_target(self):
        """通过 JumpServer 菜单连接到目标服务器"""
        self._open_shell()

        # 1) 读取 JumpServer 欢迎信息（等到 Opt> 提示符出现）
        log_info("读取 JumpServer 菜单 ...")
        banner, _ = self._read_until(["Opt>"], timeout=20, idle_gap=8)

        # 2) 搜索目标 IP
        log_info(f"搜索目标: {self.target_host}")
        self._sendline(f"/{self.target_host}")
        # 等待搜索完成：直到再次出现 Opt> 提示符
        result, reason = self._read_until(
            ["Opt>"],
            timeout=20,
            idle_gap=10,
        )
        clean_result = strip_ansi(result)
        log_info(f"搜索完成 (原因: {reason})")

        # 调试：打印搜索结果关键行
        for dl in [l.strip() for l in clean_result.splitlines() if l.strip()][:12]:
            print(f"    | {dl}")

        # 3) 判断搜索结果
        if '没有匹配' in clean_result or '无数据' in clean_result or 'No matching' in clean_result:
            log_err(f"JumpServer 中未找到匹配 {self.target_host} 的资产")
            return False

        # 检查是否自动连接（唯一匹配时 JumpServer 会直接连接）
        if '开始连接' in clean_result or 'Connecting' in clean_result:
            log_ok("唯一匹配，JumpServer 自动连接中 ...")
            return self._wait_for_target_shell()

        # 4) 解析搜索结果中的资产列表
        #    JumpServer 管道分隔格式: "  1 | sityun124 | 10.0.89.124 | ..."
        entries = re.findall(
            r'^\s*(\d+)\s*\|\s*(\S+)\s*\|\s*(\d+\.\d+\.\d+\.\d+)',
            clean_result, re.MULTILINE
        )
        if not entries:
            # 空格分隔格式: "  1  sityun124  10.0.89.124"
            entries = re.findall(
                r'^\s*(\d+)\s+(\S+)\s+(\d+\.\d+\.\d+\.\d+)',
                clean_result, re.MULTILINE
            )
        if not entries:
            # 编号格式: "1) hostname  ip"
            entries = re.findall(
                r'(\d+)\)\s+(\S+)\s+(\d+\.\d+\.\d+\.\d+)',
                clean_result, re.MULTILINE
            )

        matching = []
        for entry in entries:
            n, name, ip = entry[0], entry[1], entry[2]
            if self.target_host in ip or self.target_host in name:
                matching.append((n, name, ip))

        if not matching:
            log_warn("无法从 JumpServer 输出中解析资产列表")
            log_info("原始输出:")
            print(clean_result)
            return False

        if len(matching) == 1:
            num, name, ip = matching[0]
            log_info(f"选中: {name} ({ip})")
            self._sendline(num)
        else:
            print(f"\n  找到多个匹配:")
            for num, name, ip in matching:
                print(f"    {num}) {name} ({ip})")
            choice = input("  输入编号: ").strip()
            if not choice:
                log_err("未选择")
                return False
            self._sendline(choice)

        # 5) 等待连接建立
        return self._wait_for_target_shell()

    def _wait_for_target_shell(self):
        """等待目标服务器的 shell 就绪"""
        # 读取连接过程中的输出
        log_info("等待目标 shell 就绪 ...")
        output, reason = self._read_until(
            [r'\$\s*$', r'#\s*$', r'>\s*$',
             '选择账号', 'Select account',
             '账号ID', 'ID>',
             'Are you sure', '继续连接'],
            timeout=30, idle_gap=8,
        )
        clean = strip_ansi(output)
        log_info(f"连接输出 (原因: {reason}):")
        for dl in [l.strip() for l in clean.splitlines() if l.strip()][:10]:
            print(f"    | {dl}")

        # 需要选择账号（JumpServer 账号选择提示）
        if any(kw in clean for kw in ['选择账号', 'Select account', '账号ID', 'ID>']):
            log_info("需要选择登录账号 ...")

            # 解析 JumpServer 管道分隔账号表: "1 | loguser模板 | loguser"
            accounts = re.findall(
                r'^\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\S+)',
                clean, re.MULTILINE
            )
            if not accounts:
                accounts = re.findall(
                    r'^\s*(\d+)\s+(\S+)\s+(\S+)\s*$',
                    clean, re.MULTILINE
                )

            selected = None
            if accounts:
                log_info(f"可用账号: {', '.join(f'{n}({u})' for n, _, u in accounts)}")
                for num, desc, username in accounts:
                    if self.target_user in username or self.target_user in desc:
                        selected = num
                        break
                if not selected:
                    for num, desc, username in accounts:
                        if '模板' not in desc and 'template' not in desc.lower():
                            selected = num
                            break
                if not selected and accounts:
                    selected = accounts[0][0]

            if selected:
                log_info(f"选择账号: {selected}")
                self._sendline(selected)
                time.sleep(2)
                output2, _ = self._read_until(
                    [r'\$\s*$', r'#\s*$', r'>\s*$', 'ID>'],
                    timeout=15, idle_gap=5,
                )
                clean2 = strip_ansi(output2)
                log_info(f"账号选择后输出: {clean2.strip()[:200]}")
            else:
                log_warn("未找到可选账号")

        # 验证是否已连接到目标（发一个测试命令）
        log_info("发送验证命令 ...")
        self._sendline("echo __JUMPBOX_CONNECTED__")
        verify, vreason = self._read_until(
            ["__JUMPBOX_CONNECTED__"],
            timeout=10, idle_gap=3,
        )
        clean_verify = strip_ansi(verify)
        log_info(f"验证输出 (原因: {vreason}): {clean_verify.strip()[:200]}")
        if "__JUMPBOX_CONNECTED__" in clean_verify:
            log_ok(f"已连接到目标服务器 {self.target_host}")
            return True

        log_warn("连接验证未通过，尝试继续 ...")
        return True

    # ── 在目标上执行命令 ──

    def exec_on_target(self, cmd, show_output=True, timeout=300):
        """
        在目标服务器上执行命令。
        通过已建立的 JumpServer 交互式 channel 发送命令。
        返回 (estimated_exit_code, full_output)。
        """
        # 使用哨兵标记来检测命令结束
        sentinel = f"__CMD_END_{id(cmd)}_{int(time.time())}__"
        # 拆分哨兵：echo 'part1''part2' 输出完整哨兵，但命令回显不包含完整串
        half = len(sentinel) // 2
        part1, part2 = sentinel[:half], sentinel[half:]
        # 发送命令 + 哨兵
        self._sendline(cmd)
        self._sendline(f"echo '{part1}''{part2}';")

        # 读取直到哨兵出现
        buf = ""
        start = time.time()
        last_data = time.time()
        idle_timeout = 8 if timeout <= 60 else 60  # 长命令用更长的空闲超时

        while True:
            chunk = self._recv()
            if chunk:
                buf += chunk
                if show_output:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                last_data = time.time()

                clean = strip_ansi(buf)
                if sentinel in clean:
                    break
            else:
                if buf and (time.time() - last_data > idle_timeout):
                    # 空闲超时 — 可能命令已结束
                    break
                time.sleep(0.05)

            if time.time() - start > timeout:
                log_warn(f"命令超时 ({timeout}s)")
                break

        # 清理输出：去掉哨兵行和命令回显
        clean = strip_ansi(buf)
        # 移除命令回显（第一行通常是命令本身）
        lines = clean.splitlines()
        output_lines = []
        skip_first_cmd = True
        for line in lines:
            if skip_first_cmd and cmd.strip() in line:
                skip_first_cmd = False
                continue
            if sentinel in line:
                continue
            if 'echo ' + repr(sentinel) in line or f"echo '{sentinel}'" in line:
                continue
            output_lines.append(line)

        output = "\n".join(output_lines).strip()

        # 无法从交互式 shell 获取真实退出码，返回 0（依赖输出判断）
        return 0, output

    def test_target_connection(self):
        """测试能否在目标上执行命令"""
        code, out = self.exec_on_target("echo __CONNECT_OK__", show_output=False, timeout=15)
        return "__CONNECT_OK__" in out


# ─── 服务发现 ─────────────────────────────────────────

def list_services(session):
    """列出已注册的服务"""
    services = []
    for name, cfg in SERVICE_REGISTRY.items():
        services.append({
            "path": cfg["code_path"],
            "name": name,
            "registered": True,
        })
    return services


def is_git_repo(session, path):
    """检查远程路径是否为 git 仓库"""
    code, out = session.exec_on_target(
        f"test -d {path}/.git && echo yes || echo no",
        show_output=False,
    )
    return "yes" in out


def get_git_branches(session, path):
    """获取仓库的分支列表（本地 + 远程）"""
    code, out = session.exec_on_target(
        f"cd {path} && git branch --list --no-color 2>/dev/null",
        show_output=False,
    )
    local_branches = []
    current = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("* "):
            current = line[2:].strip()
            local_branches.append(current)
        else:
            local_branches.append(line.strip())

    code2, out2 = session.exec_on_target(
        f"cd {path} && git branch -r --no-color 2>/dev/null | grep -v HEAD",
        show_output=False,
    )
    remote_branches = []
    for line in out2.splitlines():
        b = line.strip()
        if b and "/" in b:
            b = b.split("/", 1)[1]
            remote_branches.append(b)

    all_branches = list(dict.fromkeys(local_branches + remote_branches))
    return all_branches, current


def find_deploy_scripts(session, service_path):
    """在目标目录中查找部署脚本"""
    code, out = session.exec_on_target(
        f"ls -1 {service_path}/*.sh {service_path}/scripts/*.sh 2>/dev/null",
        show_output=False,
    )
    scripts = [s.strip() for s in out.splitlines() if s.strip() and s.strip().endswith(".sh")]

    def priority(s):
        basename = os.path.basename(s)
        try:
            return DEPLOY_SCRIPT_PRIORITY.index(basename)
        except ValueError:
            return 999

    scripts.sort(key=priority)
    return scripts


# ─── 交互选择 ─────────────────────────────────────────

def choose_from_list(items, prompt="请选择", show_func=None):
    """通用交互式选择"""
    for i, item in enumerate(items, 1):
        label = show_func(item) if show_func else str(item)
        print(f"    {color(str(i).rjust(3), Colors.BOLD)}) {label}")

    while True:
        try:
            raw = input(f"\n  {prompt} (输入序号, q退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw.lower() == "q":
            return None

        try:
            idx = int(raw)
            if 1 <= idx <= len(items):
                return items[idx - 1]
        except ValueError:
            pass

        log_warn("无效输入，请重试")


# ─── 部署流程 ─────────────────────────────────────────

def _run_service_command(session, svc_cfg, action_key):
    """执行注册服务的指定命令"""
    cmd = svc_cfg["commands"][action_key]["cmd"]
    script_dir = svc_cfg["script_path"]
    full_cmd = f"cd {script_dir} && {cmd} 2>&1"
    return session.exec_on_target(full_cmd, show_output=True, timeout=600)


def _show_command_menu(session, service_name, svc_cfg):
    """为注册服务显示操作菜单并执行用户选择的命令"""
    commands = svc_cfg["commands"]
    order = svc_cfg.get("command_order", list(commands.keys()))

    print(f"\n{color('─── 操作菜单 ───', Colors.BOLD)}")
    for i, key in enumerate(order, 1):
        info = commands[key]
        print(f"    {color(str(i).rjust(3), Colors.BOLD)}) {color(key, Colors.CYAN):20s} {info['desc']}")

    while True:
        try:
            raw = input(f"\n  选择操作 (输入序号, 默认1-deploy, r重新选服务, q退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if raw.lower() == "q":
            return 0

        if raw.lower() == "r":
            return -1  # 返回重新选择服务

        if not raw:
            action_key = order[0]  # 默认第一个：deploy
            break

        try:
            idx = int(raw)
            if 1 <= idx <= len(order):
                action_key = order[idx - 1]
                break
        except ValueError:
            pass

        log_warn("无效输入，请重试")

    info = commands[action_key]
    label = f" ({svc_cfg['label']})" if svc_cfg.get("label") else ""
    print(f"\n{color('═══ 执行命令 ═══', Colors.BOLD)}")
    print(f"  服务:   {color(service_name, Colors.GREEN)}{color(label, Colors.YELLOW)}")
    print(f"  命令:   {color(info['cmd'], Colors.CYAN)}")
    print(f"  说明:   {info['desc']}")

    confirm = input(f"\n  确认执行? (y/n, 默认y): ").strip().lower()
    if confirm == "n":
        print("  已取消。")
        return 0

    print(f"\n  {color('─── 输出 ───', Colors.BOLD)}\n")
    code, _ = _run_service_command(session, svc_cfg, action_key)
    print()

    if code == 0:
        log_ok(f"命令执行完成")
    else:
        log_err(f"命令异常退出 (exit={code})")

    return code


def interactive_deploy(session, args, config):
    """交互式部署流程"""

    # ── Step 1: 列出服务 ──
    print(f"\n{color('═══ 扫描服务列表 ═══', Colors.BOLD)}")
    services = list_services(session)

    if not services:
        log_err(f"在 {SERVICES_DIR} 下未找到任何服务目录")
        return 1

    print(f"\n  找到 {color(str(len(services)), Colors.GREEN)} 个服务:\n")

    def show_label(s):
        if s.get("registered"):
            cfg = SERVICE_REGISTRY.get(s["name"])
            tag = color(f" [{cfg['label']}]", Colors.CYAN) if cfg and cfg.get("label") else color(" [已注册]", Colors.CYAN)
            return f"{s['name']}{tag}"
        return s["name"]

    # ── 服务选择 + 命令菜单循环（支持 r 重新选择）──
    while True:
        service = choose_from_list(services, "选择要部署的服务", show_label)
        if not service:
            print("  已取消。")
            return 0

        service_name = service["name"]
        service_path = service["path"]
        svc_cfg = SERVICE_REGISTRY.get(service_name)
        label = f" ({svc_cfg['label']})" if svc_cfg and svc_cfg.get("label") else ""
        print(f"\n  已选择: {color(service_name, Colors.GREEN)}{color(label, Colors.YELLOW)}")

        # ── Step 2: 检查是否为注册服务 ──
        if svc_cfg:
            # 注册服务：Git 分支 + 命令菜单
            if is_git_repo(session, svc_cfg["code_path"]):
                _handle_git_branch(session, svc_cfg["code_path"], default_branch=svc_cfg.get("branch"))
            result = _show_command_menu(session, service_name, svc_cfg)
            if result == -1:
                # 按了 r，重新选择服务
                print(f"\n{color('═══ 重新选择服务 ═══', Colors.BOLD)}")
                continue
            return result

        # ── 未注册服务：通用流程 ──
        if is_git_repo(session, service_path):
            _handle_git_branch(session, service_path)

        print(f"\n{color('─── 部署脚本 ───', Colors.BOLD)}")
        script = _choose_script(session, service_path, config, service_name)

        if not script:
            print("  未选择脚本，已取消。")
            return 1

        print(f"\n{color('═══ 部署确认 ═══', Colors.BOLD)}")
        print(f"  服务:   {color(service_name, Colors.GREEN)}")
        print(f"  路径:   {service_path}")
        print(f"  脚本:   {color(script, Colors.CYAN)}")

        confirm = input(f"\n  确认执行部署? (y/n, 默认n): ").strip().lower()
        if confirm != "y":
            print("  已取消部署。")
            return 0

        print(f"\n{color('═══ 开始部署 ═══', Colors.BOLD)}\n")
        print(f"  $ bash {script}\n")
        print("  " + "─" * 60)

        code, _ = session.exec_on_target(
            f"cd {service_path} && bash {script} 2>&1",
            timeout=600,
        )

        print("  " + "─" * 60)
        log_ok("部署完成") if code == 0 else log_err(f"部署异常退出 (exit={code})")
        return code


def _handle_git_branch(session, code_path, default_branch=None):
    """处理 Git 分支切换（公共逻辑）"""
    all_branches, current = get_git_branches(session, code_path)
    if not all_branches:
        log_warn("无法获取分支列表")
        return

    print(f"\n{color('─── Git 分支 ───', Colors.BOLD)}")
    print(f"  当前分支: {color(current or '未知', Colors.YELLOW)}")
    if default_branch:
        print(f"  默认分支: {color(default_branch, Colors.CYAN)}")

    switch = None

    # 有默认分支且当前不在默认分支上 → 自动切换
    if default_branch and current != default_branch:
        log_info(f"自动切换到默认分支 {default_branch}")
        switch = default_branch
    elif default_branch and current == default_branch:
        log_ok(f"已在默认分支 {default_branch}")
        return
    else:
        # 无默认分支 → 交互式输入
        raw = input(f"\n  是否切换分支? (直接回车跳过, 输入分支名切换): ").strip()
        if not raw or raw == current:
            return
        switch = raw

    if switch not in all_branches:
        log_warn(f"分支 '{switch}' 不在列表中，仍尝试切换...")

    log_info(f"git fetch + checkout {switch}")
    code, _ = session.exec_on_target(
        f"cd {code_path} && git fetch --all --prune 2>&1 && git checkout {switch} 2>&1",
        show_output=True,
    )
    if code == 0:
        log_ok(f"已切换到分支 {switch}")
        log_info("git pull ...")
        session.exec_on_target(f"cd {code_path} && git pull 2>&1", show_output=True)
    else:
        log_err(f"分支切换失败 (exit={code})")


def _choose_script(session, service_path, config, service_name):
    """交互式选择部署脚本"""
    remembered = config.get("scripts", {}).get(service_name)
    if remembered:
        code, _ = session.exec_on_target(f"test -f {remembered}", show_output=False)
        if code == 0:
            print(f"  上次使用的脚本: {color(remembered, Colors.CYAN)}")
            use_other = input("  换其他脚本? (直接回车使用记住的, y换): ").strip().lower()
            if use_other != "y":
                return remembered

    scripts = find_deploy_scripts(session, service_path)

    if not scripts:
        log_warn(f"在 {service_path} 下未找到 .sh 脚本")
        custom = input("  请输入脚本的完整路径 (留空取消): ").strip()
        if custom:
            config.setdefault("scripts", {})[service_name] = custom
            save_config(config)
            return custom
        return None

    print(f"  找到 {len(scripts)} 个脚本:\n")
    script = choose_from_list(scripts, "选择部署脚本", lambda s: os.path.basename(s))

    if script:
        config.setdefault("scripts", {})[service_name] = script
        save_config(config)

    return script


def direct_deploy(session, service_name, branch, action, config):
    """非交互模式：直接部署指定服务"""
    svc_cfg = SERVICE_REGISTRY.get(service_name)

    if svc_cfg:
        log_info(f"目标服务: {color(service_name, Colors.GREEN)} (已注册)")

        # 分支处理：优先用 -b 参数，其次用服务配置的默认分支
        target_branch = branch or svc_cfg.get("branch")
        if target_branch and is_git_repo(session, svc_cfg["code_path"]):
            log_info(f"切换到分支 {target_branch} ...")
            code, _ = session.exec_on_target(
                f"cd {svc_cfg['code_path']} && git fetch --all --prune 2>&1 "
                f"&& git checkout {target_branch} 2>&1 && git pull 2>&1",
                show_output=True,
            )
            if code != 0:
                log_err("分支切换失败")
                return 1
            log_ok(f"已切换到 {target_branch}")

        if action:
            if action not in svc_cfg["commands"]:
                log_err(f"未知操作 '{action}'，可用: {', '.join(svc_cfg['command_order'])}")
                return 1
            info = svc_cfg["commands"][action]
            log_info(f"执行: {color(info['cmd'], Colors.CYAN)} ({info['desc']})")
            print()
            code, _ = _run_service_command(session, svc_cfg, action)
        else:
            code = _show_command_menu(session, service_name, svc_cfg)

        return code

    # 未注册服务
    service_path = f"{SERVICES_DIR}/{service_name}"
    code, _ = session.exec_on_target(f"test -d {service_path}", show_output=False)
    if code != 0:
        log_err(f"服务目录不存在: {service_path}")
        return 1

    log_info(f"目标服务: {service_name}")

    if branch and is_git_repo(session, service_path):
        log_info(f"切换到分支 {branch} ...")
        session.exec_on_target(
            f"cd {service_path} && git fetch --all --prune 2>&1 "
            f"&& git checkout {branch} 2>&1 && git pull 2>&1",
            show_output=True,
        )

    remembered = config.get("scripts", {}).get(service_name)
    if remembered:
        script = remembered
    else:
        scripts = find_deploy_scripts(session, service_path)
        if not scripts:
            log_err("未找到部署脚本")
            return 1
        script = scripts[0]

    log_info(f"执行脚本: {script}")
    print()
    session.exec_on_target(f"cd {service_path} && bash {script} 2>&1", timeout=600)
    print()
    log_ok("部署完成")
    return 0


def list_only(session):
    """仅列出服务"""
    print(f"\n{color('═══ 服务列表 ═══', Colors.BOLD)}\n")
    services = list_services(session)

    for s in services:
        git = is_git_repo(session, s["path"])
        registered = color(" [已注册]", Colors.CYAN) if s.get("registered") else ""
        git_tag = color(" [git]", Colors.GREEN) if git else ""
        print(f"    {s['name']}{registered}{git_tag}")

    print(f"\n  共 {len(services)} 个服务")
    return 0


# ─── CLI 入口 ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="跳板机服务部署工具 (JumpServer 版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                                  交互式部署
  %(prog)s -l                               列出所有服务
  %(prog)s -s equities-core                 部署指定服务（显示操作菜单）
  %(prog)s -s equities-core -a deploy       直接执行打包部署
  %(prog)s -s equities-core -a restart      直接重启服务
  %(prog)s -s equities-core -a verify       验证服务状态
  %(prog)s -s equities-core -b develop -a deploy  切换分支后部署

通用操作: deploy/issue/start/stop/restart/verify

新增服务 (编辑 deploy_config.json):
  "服务名": {
    "script_name": "脚本相对路径",
    "script_path": "/opt/xxx",
    "code_path": "/opt/xxx/code",
    "branch": "develop",
    "label": "中文名"
  }
        """,
    )
    parser.add_argument("-l", "--list", action="store_true", help="仅列出服务列表")
    parser.add_argument("-s", "--service", help="指定要部署的服务名称")
    parser.add_argument("-a", "--action", help="指定操作（注册服务可用，如 deploy/issue/restart/stop/start/verify）")
    parser.add_argument("-b", "--branch", help="部署前切换到指定 git 分支")
    parser.add_argument("-H", "--host", default=TARGET_HOST, help=f"目标服务器地址 (默认 {TARGET_HOST})")
    parser.add_argument("-u", "--user", default=TARGET_USER, help=f"目标服务器用户名 (默认 {TARGET_USER})")
    parser.add_argument("--jump-host", default=JUMP_HOST, help=f"跳板机地址 (默认 {JUMP_HOST})")
    parser.add_argument("--jump-port", type=int, default=JUMP_PORT, help=f"跳板机端口 (默认 {JUMP_PORT})")
    parser.add_argument("--timeout", type=int, default=600, help="部署命令超时秒数 (默认 600)")

    args = parser.parse_args()

    load_service_registry()

    print(f"""
{color('╔══════════════════════════════════════════╗', Colors.BOLD)}
{color('║   跳板机服务部署工具 v1.1 (JumpServer)   ║', Colors.BOLD)}
{color('╚══════════════════════════════════════════╝', Colors.BOLD)}
""")

    # -l 不带 -s 时：仅列出本地已注册的服务，不连接跳板机
    if args.list and not args.service:
        print(f"{color('═══ 服务列表 ═══', Colors.BOLD)}\n")
        if not SERVICE_REGISTRY:
            print("  (无)\n")
            return 0
        for name, cfg in SERVICE_REGISTRY.items():
            label = color(f" ({cfg['label']})", Colors.YELLOW) if cfg.get("label") else ""
            branch_tag = color(f" [{cfg['branch']}]", Colors.CYAN) if cfg.get("branch") else ""
            print(f"  {color(name, Colors.GREEN)}{label}{branch_tag}")
        print()
        print(f"  共 {len(SERVICE_REGISTRY)} 个服务")
        return 0

    config = load_config()

    if not JUMP_PASS:
        log_err("缺少跳板机凭据：请 cp deploy_config.example.json deploy_config.json 并填入 jump.password")
        return 1

    session = JumpServerSession(
        jump_host=args.jump_host,
        jump_port=args.jump_port,
        jump_user=JUMP_USER,
        jump_pass=JUMP_PASS,
        target_host=args.host,
        target_user=args.user,
    )

    try:
        session.connect()

        # 通过 JumpServer 菜单连接到目标
        log_info(f"通过 JumpServer 连接目标 {args.host} ...")
        if not session.connect_target():
            log_err("无法通过 JumpServer 连接到目标服务器")
            return 1

        # 验证命令执行能力
        log_info("验证目标服务器命令执行 ...")
        if session.test_target_connection():
            log_ok("目标服务器就绪")
        else:
            log_warn("命令执行验证失败，可能连接不稳定")
            if not args.list:
                cont = input("  是否继续? (y/n): ").strip().lower()
                if cont != "y":
                    return 1

        # 显示已注册服务
        if SERVICE_REGISTRY:
            log_info(f"已注册 {len(SERVICE_REGISTRY)} 个服务: {', '.join(SERVICE_REGISTRY.keys())}")

        if args.list:
            return list_only(session)
        elif args.service:
            return direct_deploy(session, args.service, args.branch, args.action, config)
        else:
            return interactive_deploy(session, args, config)

    except paramiko.AuthenticationException as e:
        log_err(f"JumpServer 认证失败: {e}")
        return 1
    except paramiko.SSHException as e:
        log_err(f"SSH 错误: {e}")
        return 1
    except socket.timeout:
        log_err("连接超时，请检查网络或 JumpServer 状态")
        return 1
    except socket.error as e:
        log_err(f"网络错误: {e}")
        return 1
    except KeyboardInterrupt:
        print(f"\n\n  {color('用户中断', Colors.YELLOW)}")
        return 130
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
