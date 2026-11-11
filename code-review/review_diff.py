#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集"待审引用 vs 基线引用"的差异，生成代码审查材料（只读，不改工作区）。

默认差异口径为 direct：直接比较 A..B（两个 commit / 分支最新提交之间的全部差异）；
需要"只看待审侧自基线分叉后的新增"时用 --diff-mode merge-base。
默认排除 src/test 单元测试目录，需要纳入时用 --include-tests。

产出：
  summary.md                 总览（提交、规模、文件清单、风险标记、双向冲突预演、阅读顺序）
  report.md                  审查报告骨架（结论 / P0-P3 / 反向风险 / 未覆盖）
  index.json                 结构化结果（每个文件带 flags / score / diff_file）
  diff-forward.patch         待审侧相对分叉点的原始 patch（字节级，不经解码）
  diff-reverse.patch         基线侧相对分叉点的原始 patch
  files/NNN-*.diff           待审侧逐文件 diff（新增行标注 +[L行号]）
  files-reverse/NNN-*.diff   基线侧逐文件 diff

只执行 git 查询与 merge-tree 预演：不 checkout / reset / merge / clean，不写仓库。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

STATUS_LABEL = {
    "A": "新增", "M": "修改", "D": "删除", "R": "重命名",
    "C": "复制", "T": "类型变更", "U": "冲突", "X": "未知", "?": "未知",
}
DIRECTION_LABEL = {"both": "双向", "forward": "仅待审→基线", "reverse": "仅基线→待审"}

CONFIG_RE = re.compile(
    r"(^|/)(application[^/]*\.(ya?ml|properties)|bootstrap[^/]*\.(ya?ml|properties)"
    r"|[^/]*\.(ya?ml|yml|properties|conf|ini|toml)|[^/]*config[^/]*\.json|\.env[^/]*)$", re.I)
CODE_RE = re.compile(
    r"\.(java|kt|kts|groovy|py|js|jsx|ts|tsx|vue|go|php|cs|rb|rs|c|cc|cpp|h|hpp|"
    r"scala|sh|ps1|sql)$", re.I)
SRC_CODE_RE = re.compile(
    r"\.(java|kt|kts|groovy|py|js|jsx|ts|tsx|vue|go|php|cs|rb|rs|c|cc|cpp|h|hpp|scala)$",
    re.I)
BUILD_RE = re.compile(
    r"(^|/)(pom\.xml|build\.gradle(\.kts)?|settings\.gradle|package\.json|"
    r"package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.mod|go\.sum|"
    r"requirements[^/]*\.txt|Cargo\.toml)$", re.I)
SQL_RE = re.compile(r"(\.sql$|\.ddl$|/mapper/[^/]*\.xml$|mapper[^/]*\.xml$)", re.I)
DEPLOY_RE = re.compile(
    r"(^|/)(Dockerfile[^/]*|docker-compose[^/]*|Jenkinsfile|nginx[^/]*\.conf|"
    r"k8s/|deploy/|helm/)", re.I)
# 只有落在测试目录下，或带明确测试后缀的文件才算测试；src/main 下的 XxxTest.java 不算
TEST_PATH_RE = re.compile(r"(^|/)(src/test|test|tests|__tests__|spec)/", re.I)
TEST_SUFFIX_RE = re.compile(r"(_test\.\w+|\.spec\.\w+|\.test\.\w+|Tests?\.(java|kt|cs|scala))$", re.I)
GENERATED_RE = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|composer\.lock|go\.sum|"
    r"poetry\.lock|Gemfile\.lock|\.DS_Store|Thumbs\.db|__pycache__/|node_modules/|"
    r"dist/|target/|\.min\.(js|css)$|\.map$)|\.pyc$", re.I)
SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|access[_-]?key(?:id)?|private[_-]?key|token)"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9/+_\-=]{8,}")
PRIVATE_KEY_RE = re.compile(r"BEGIN (?:RSA|EC|DSA|OPENSSH) PRIVATE KEY")
DEBUG_RE = re.compile(
    r"(System\.out\.print|System\.err\.print|printStackTrace|console\.log|println!\()")
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})")
# 必须锚定行首：文件内容里出现 "Binary files" 不能算二进制
BINARY_BLOCK_RE = re.compile(r"(?m)^Binary files .* differ$")

MAX_SCAN_LINES = 5000


class GitError(RuntimeError):
    pass


# ---------------------------------------------------------------- git 与解码

def decode_bytes(raw: bytes) -> str:
    """单行/小块解码：UTF-8 严格优先，失败退 GB18030，最后替换。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def decode_block(raw: bytes) -> str:
    """按行解码一个 diff 块，避免整份输出被单一编码判定带偏。"""
    if not raw:
        return ""
    return "\n".join(decode_bytes(line) for line in raw.split(b"\n"))


def git_raw(repo: Path, args: list[str], check: bool = True) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        detail = decode_bytes(proc.stderr).strip() or decode_bytes(proc.stdout).strip()
        raise GitError(f"git {' '.join(args)} 失败：\n{detail}")
    return proc.returncode, proc.stdout, proc.stderr


def rev_parse(repo: Path, ref: str) -> str:
    rc, out, _ = git_raw(repo, ["rev-parse", "--verify", "--quiet", ref], check=False)
    return decode_bytes(out).strip() if rc == 0 else ""


def ref_exists(repo: Path, ref: str) -> bool:
    return bool(rev_parse(repo, ref + "^{commit}"))


def is_ancestor(repo: Path, maybe_ancestor: str, descendant: str) -> bool:
    rc, _, _ = git_raw(repo, ["merge-base", "--is-ancestor", maybe_ancestor, descendant],
                       check=False)
    return rc == 0


def resolve_repo(path_arg: str) -> Path:
    start = Path(path_arg).expanduser().resolve()
    rc, out, _ = git_raw(start, ["rev-parse", "--show-toplevel"], check=False)
    if rc != 0:
        raise GitError(f"{start} 不是 git 仓库（或其子目录）")
    return Path(decode_bytes(out).strip())


def resolve_branch(repo: Path, branch_arg: str) -> str:
    if branch_arg != "HEAD":
        if not ref_exists(repo, branch_arg):
            raise GitError(
                f"分支/引用不存在：{branch_arg}\n"
                "可用 `--list-refs` 查看候选分支与近期提交，或确认分支是否已 fetch。")
        return branch_arg
    rc, out, _ = git_raw(repo, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    name = decode_bytes(out).strip()
    return name if name and name != "HEAD" else "HEAD"


def ref_kind(repo: Path, ref: str) -> str:
    if ref == "HEAD":
        return "当前 HEAD"
    for prefix, label in (("refs/heads/", "本地分支"), ("refs/remotes/", "远程分支"),
                          ("refs/tags/", "tag")):
        rc, _, _ = git_raw(repo, ["show-ref", "--verify", "--quiet", prefix + ref], check=False)
        if rc == 0:
            return label
    return "commit"


def resolve_base(repo: Path, base_arg: str | None) -> str:
    if base_arg:
        if not ref_exists(repo, base_arg):
            raise GitError(f"基线分支不存在：{base_arg}（可用 --base 指定，如 origin/master）")
        return base_arg
    for cand in ("origin/master", "master", "origin/main", "main"):
        if ref_exists(repo, cand):
            return cand
    raise GitError("找不到 master/main 基线，请用 --base 显式指定")


def log_commits(repo: Path, rev_range: str) -> list[dict]:
    rc, raw, _ = git_raw(repo, [
        "log", "--no-color", "--no-decorate",
        "--pretty=format:%h\t%ad\t%an\t%s", "--date=short", rev_range,
    ], check=False)
    commits = []
    for line in decode_block(raw).split("\n"):
        parts = line.split("\t", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "date": parts[1],
                            "author": parts[2], "subject": parts[3]})
    return commits


# ------------------------------------------------------------ 文件清单与块

def collect_entries(repo: Path, specs: list[str]) -> list[dict]:
    """用 -z 取 name-status，避免文件名空白/特殊字符错位。"""
    rc, raw, _ = git_raw(repo, ["diff", "--name-status", "-M", "-z", "--no-color", *specs])
    tokens = raw.split(b"\0")
    entries: list[dict] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        status_raw = decode_bytes(tok).strip()
        st = status_raw[:1] or "?"
        if st in ("R", "C"):
            if i + 2 >= len(tokens):
                break
            old_path = decode_bytes(tokens[i + 1])
            path = decode_bytes(tokens[i + 2])
            i += 3
        else:
            if i + 1 >= len(tokens):
                break
            path = decode_bytes(tokens[i + 1])
            old_path = path
            i += 2
        entries.append({
            "status": st,
            "status_raw": status_raw,
            "old_path": old_path,
            "path": path,
        })
    return entries


def split_raw_diff(raw: bytes) -> list[bytes]:
    if not raw.strip():
        return []
    parts = raw.split(b"\ndiff --git ")
    blocks: list[bytes] = []
    for i, part in enumerate(parts):
        if i == 0:
            if part.startswith(b"diff --git "):
                blocks.append(part)
        else:
            blocks.append(b"diff --git " + part)
    return [b for b in blocks if b.strip()]


def _unquote_path(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        body = text[1:-1]
        return (body.replace('\\"', '"').replace("\\\\", "\\")
                .replace("\\t", "\t").replace("\\n", "\n"))
    return text


def _strip_prefix(text: str) -> str:
    text = _unquote_path(text)
    if text.startswith("a/") or text.startswith("b/"):
        return text[2:]
    return text


def block_paths(raw_block: bytes) -> tuple[str, str]:
    """返回 (old_path, new_path)，/dev/null 侧返回空串。"""
    text = decode_block(raw_block)
    head = text.split("\n@@", 1)[0]
    old = new = ""
    m = re.search(r"(?m)^--- (.+)$", head)
    if m and m.group(1).strip() != "/dev/null":
        old = _strip_prefix(m.group(1))
    m = re.search(r"(?m)^\+\+\+ (.+)$", head)
    if m and m.group(1).strip() != "/dev/null":
        new = _strip_prefix(m.group(1))
    if old or new:
        return old, new
    # 100% 相似度的重命名没有 ---/+++，只有 rename from/to
    m_from = re.search(r"(?m)^rename from (.+)$", head)
    m_to = re.search(r"(?m)^rename to (.+)$", head)
    if m_from and m_to:
        return _strip_prefix(m_from.group(1)), _strip_prefix(m_to.group(1))
    first = text.split("\n", 1)[0]
    rest = first[len("diff --git "):] if first.startswith("diff --git ") else ""
    if not rest:
        return "", ""
    if rest.startswith('"'):
        quoted = re.findall(r'"(?:[^"\\]|\\.)*"', rest)
        if len(quoted) >= 2:
            return _strip_prefix(quoted[0]), _strip_prefix(quoted[1])
        return "", ""
    positions = [m.start() for m in re.finditer(r" b/", rest)]
    for i in positions:
        left, right = rest[2:i], rest[i + 3:]
        if left == right:
            return left, right
    if positions:
        i = positions[-1]
        return rest[2:i], rest[i + 3:]
    return "", ""


def match_blocks(entries: list[dict], blocks: list[bytes]) -> tuple[dict[int, bytes], list[str], list[str]]:
    """按路径把 diff 块对到文件清单，避免"按序号对齐"在过滤/重命名时错配。"""
    remaining = list(range(len(entries)))
    mapping: dict[int, bytes] = {}
    leftovers: list[str] = []
    for block in blocks:
        old, new = block_paths(block)
        hit: int | None = None
        if new:
            for idx in remaining:
                if entries[idx]["path"] == new:
                    hit = idx
                    break
        if hit is None and old:
            for idx in remaining:
                if entries[idx]["old_path"] == old:
                    hit = idx
                    break
        if hit is None:
            if not old and not new and remaining:
                hit = remaining[0]
            else:
                leftovers.append(old or new or "?")
                continue
        mapping[hit] = block
        remaining.remove(hit)
    missing = [entries[i]["path"] for i in remaining]
    return mapping, leftovers, missing


# ------------------------------------------------------------ diff 文本处理

def annotate_added(text: str) -> str:
    """给新增行打上新文件行号：+[L123] 代码。仅用于阅读。"""
    out: list[str] = []
    new_ln: int | None = None
    for line in text.split("\n"):
        m = HUNK_RE.match(line)
        if m:
            new_ln = int(m.group(1))
            out.append(line)
            continue
        if new_ln is None:
            out.append(line)
            continue
        if line.startswith("+++") or line.startswith("---"):
            out.append(line)
        elif line.startswith("+"):
            out.append(f"+[L{new_ln}] {line[1:]}")
            new_ln += 1
        elif line.startswith("-"):
            out.append(line)
        elif line.startswith(" "):
            out.append(line)
            new_ln += 1
        else:
            out.append(line)
    return "\n".join(out)


def added_lines(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    new_ln: int | None = None
    for line in text.split("\n"):
        m = HUNK_RE.match(line)
        if m:
            new_ln = int(m.group(1))
            continue
        if new_ln is None or line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            result.append((new_ln, line[1:]))
            new_ln += 1
        elif line.startswith(" "):
            new_ln += 1
    return result


def removed_count(text: str) -> int:
    return sum(1 for line in text.split("\n")
               if line.startswith("-") and not line.startswith("---"))


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    if TEST_PATH_RE.search(p):
        return True
    # src/main 下的 XxxTest.java 多为手工验证类，不计入"测试文件"
    if p.startswith("src/main/") or "/src/main/" in p:
        return False
    return bool(TEST_SUFFIX_RE.search(p))


def is_test_source_dir(path: str) -> bool:
    """是否位于 src/test 单元测试目录（含多模块 module/src/test/...）。"""
    parts = path.replace("\\", "/").lower().split("/")
    return any(parts[i] == "src" and i + 1 < len(parts) and parts[i + 1] == "test"
               for i in range(len(parts) - 1))


# ------------------------------------------------------------ 风险标记

def risk_flags(entry: dict, text: str, add: int | None) -> tuple[list[str], list[str]]:
    path = entry["path"] or entry.get("old_path", "")
    flags: list[str] = []
    signals: list[str] = []
    st = entry.get("status", "?")

    if entry.get("untracked"):
        flags.append("未跟踪")
    if st == "D":
        flags.append("删除文件")
    elif st == "A":
        flags.append("新增文件")
    elif st == "R":
        flags.append("重命名")
    elif st == "C":
        flags.append("复制")

    binary = bool(entry.get("binary")) or bool(BINARY_BLOCK_RE.search(text))
    if binary:
        flags.append("二进制")
    if entry.get("unexpanded"):
        flags.append("未展开（超限）")
        signals.append(f"`{path}` 未展开：{entry.get('unexpanded_reason', '超出大小限制')}")
    if GENERATED_RE.search(path):
        flags.append("生成物")
    if CONFIG_RE.search(path):
        flags.append("配置变更")
    if BUILD_RE.search(path):
        flags.append("依赖/构建")
    if SQL_RE.search(path):
        flags.append("数据库/SQL")
    if DEPLOY_RE.search(path):
        flags.append("部署")
    if is_test_path(path):
        flags.append("测试")
    if add is not None and add > 300:
        flags.append("新增行多")
    if len(text.split("\n")) > 800:
        flags.append("大改动")

    if binary or not text:
        return flags, signals

    added = added_lines(text)
    scan = added[:MAX_SCAN_LINES]
    if any(CONFLICT_RE.match(body) for _, body in scan):
        flags.append("残留冲突标记")
        signals.append(f"`{path}` 新增行含冲突标记（<<<<<<< / ======= / >>>>>>>）")
    secret_hits = [(ln, body) for ln, body in scan
                   if SENSITIVE_RE.search(body) or PRIVATE_KEY_RE.search(body)]
    if secret_hits:
        flags.append("疑似敏感信息")
        lns = "、".join(f"L{ln}" for ln, _ in secret_hits[:5])
        signals.append(f"`{path}` {lns} 疑似密钥/口令（值已省略，报告中不要粘贴明文）")
    if any(DEBUG_RE.search(body) for _, body in scan):
        flags.append("调试输出")
        signals.append(f"`{path}` 新增调试输出语句")
    if any(TODO_RE.search(body) for _, body in scan):
        flags.append("TODO/FIXME")
    return flags, signals


def risk_score(flags: list[str]) -> int:
    if "残留冲突标记" in flags:
        return 100
    if "疑似敏感信息" in flags:
        return 95
    if "生成物" in flags or "二进制" in flags:
        return 0
    weights = {
        "删除文件": 60,
        "配置变更": 50,
        "依赖/构建": 50,
        "数据库/SQL": 45,
        "部署": 40,
        "大改动": 30,
        "重命名": 25,
        "调试输出": 20,
        "新增文件": 10,
        "未跟踪": 5,
    }
    return max((weights.get(f, 0) for f in flags), default=0)


# ------------------------------------------------------------ 工作区未跟踪文件

def path_selected(path: str, includes: list[str], excludes: list[str]) -> bool:
    p = path.replace("\\", "/")
    base = posixpath.basename(p)
    if includes and not any(fnmatch.fnmatchcase(p, pat) or fnmatch.fnmatchcase(base, pat)
                            for pat in includes):
        return False
    if excludes and any(fnmatch.fnmatchcase(p, pat) or fnmatch.fnmatchcase(base, pat)
                        for pat in excludes):
        return False
    return True


def looks_binary(data: bytes) -> bool:
    if b"\0" in data[:8000]:
        return True
    for enc in ("utf-8", "gb18030"):
        try:
            data.decode(enc)
            return False
        except UnicodeDecodeError:
            continue
    return True


def synthetic_untracked_block(rel: str, full: Path, max_size: int) -> tuple[bytes, dict]:
    p = rel.replace("\\", "/")
    meta = {"binary": False, "unexpanded": False, "size": 0, "reason": ""}
    header = [f"diff --git a/{p} b/{p}".encode("utf-8")]
    mode = "100644"
    data = b""

    if full.is_symlink():
        mode = "120000"
        try:
            data = os.readlink(full).encode("utf-8")
        except OSError as exc:
            meta.update(unexpanded=True, binary=True, reason=f"读取符号链接失败：{exc}")
            header += [b"new file mode 120000", b"index 0000000..0000000",
                       f"Binary files /dev/null and b/{p} differ".encode("utf-8")]
            return b"\n".join(header) + b"\n", meta
    else:
        try:
            size = full.stat().st_size
        except OSError as exc:
            meta.update(unexpanded=True, binary=True, reason=f"读取文件信息失败：{exc}")
            header += [b"new file mode 100644", b"index 0000000..0000000",
                       f"Binary files /dev/null and b/{p} differ".encode("utf-8")]
            return b"\n".join(header) + b"\n", meta
        meta["size"] = size
        if size > max_size:
            meta.update(unexpanded=True, binary=True,
                        reason=f"{size} 字节超过 --max-untracked-size={max_size}")
            header += [b"new file mode 100644", b"index 0000000..0000000",
                       f"Binary files /dev/null and b/{p} differ".encode("utf-8")]
            return b"\n".join(header) + b"\n", meta
        try:
            data = full.read_bytes()
        except OSError as exc:
            meta.update(unexpanded=True, binary=True, reason=f"读取文件失败：{exc}")
            header += [b"new file mode 100644", b"index 0000000..0000000",
                       f"Binary files /dev/null and b/{p} differ".encode("utf-8")]
            return b"\n".join(header) + b"\n", meta
        meta["size"] = len(data)

    if looks_binary(data) and not full.is_symlink():
        meta["binary"] = True
        header += [f"new file mode {mode}".encode(), b"index 0000000..0000000",
                   f"Binary files /dev/null and b/{p} differ".encode("utf-8")]
        return b"\n".join(header) + b"\n", meta

    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    header += [f"new file mode {mode}".encode(), b"index 0000000..0000000",
               b"--- /dev/null", f"+++ b/{p}".encode("utf-8")]
    hunk = f"@@ -0,0 +1,{len(lines)} @@\n".encode("utf-8") if lines else b""
    body = b"".join(b"+" + line + b"\n" for line in lines)
    return b"\n".join(header) + b"\n" + hunk + body, meta


def collect_untracked(repo: Path, max_size: int,
                      includes: list[str], excludes: list[str],
                      skip_prefixes: tuple[str, ...] = ()) -> tuple[list[dict], list[bytes], list[str]]:
    rc, raw, _ = git_raw(repo, ["ls-files", "--others", "--exclude-standard", "-z"], check=False)
    entries: list[dict] = []
    blocks: list[bytes] = []
    signals: list[str] = []
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = decode_bytes(token)
        posix_rel = rel.replace("\\", "/")
        if any(posix_rel == p or posix_rel.startswith(p + "/") for p in skip_prefixes):
            continue
        if "\n" in rel:
            signals.append(f"未跟踪文件路径含换行，无法生成 diff 块：`{rel!r}`")
            continue
        if not path_selected(rel, includes, excludes):
            continue
        block, meta = synthetic_untracked_block(rel, repo / rel, max_size)
        entries.append({
            "status": "A",
            "status_raw": "A",
            "old_path": rel,
            "path": rel,
            "untracked": True,
            "binary": meta["binary"],
            "unexpanded": meta["unexpanded"],
            "unexpanded_reason": meta.get("reason", ""),
        })
        blocks.append(block)
        if meta["unexpanded"]:
            signals.append(f"未跟踪文件未展开：`{rel}`（{meta.get('reason', '')}）")
    return entries, blocks, signals


# ------------------------------------------------------------ 合并预演

def merge_preview(repo: Path, target: str, incoming: str) -> dict:
    """预演把 incoming 合入 target（不修改工作区）。"""
    rc, out, err = git_raw(repo, ["merge-tree", "--write-tree", "--name-only",
                                  "--no-messages", target, incoming], check=False)
    if rc == 0:
        return {"supported": True, "clean": True, "conflicts": [], "detail": "无冲突"}
    if rc == 1:
        conflicts: list[str] = []
        for line in decode_block(out).split("\n"):
            line = line.strip()
            if not line or re.fullmatch(r"[0-9a-f]{40,64}", line):
                continue
            if re.match(r"(Auto-merging|CONFLICT|Merge conflict|Automatic merge|changed in both)",
                        line):
                continue
            conflicts.append(line)
        return {
            "supported": True, "clean": False, "conflicts": conflicts,
            "detail": "存在冲突" if conflicts else "合并存在冲突（git 标注为 conflicted）",
        }
    detail = (decode_bytes(err) or decode_bytes(out)).strip()
    return {"supported": False, "clean": None, "conflicts": [],
            "detail": f"当前 Git 不支持冲突预演：{detail}"}


def diff_check(repo: Path, specs: list[str]) -> str:
    rc, out, _ = git_raw(repo, ["diff", "--check", "-M", "--no-color", *specs], check=False)
    return decode_block(out).strip()


# ------------------------------------------------------------ 单侧构建

def sanitize(name: str, limit: int = 80) -> str:
    safe = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", name or "file").strip("_")
    return (safe or "file")[:limit]


def fmt_num(value: int | None) -> str:
    return "-" if value is None else str(value)


def empty_side() -> dict:
    return {
        "enabled": False, "range": "", "commits": [], "files": [],
        "total_add": 0, "total_del": 0, "filtered_out": 0,
        "test_dir_skipped": 0, "test_files_total": 0,
        "expanded": 0, "not_expanded": 0, "signals": [],
    }


def build_side(repo: Path, specs: list[str], commits: list[dict], files_dir: Path,
               dir_label: str, limit: int, annotate: bool,
               includes: list[str], excludes: list[str],
               exclude_tests: bool = True,
               extra_entries: list[dict] | None = None,
               extra_blocks: list[bytes] | None = None) -> tuple[dict, list[dict], bytes]:
    entries = collect_entries(repo, specs) + list(extra_entries or [])
    rc, raw, _ = git_raw(repo, ["diff", "--no-color", "--no-ext-diff", "-M", *specs], check=False)
    blocks = split_raw_diff(raw) + list(extra_blocks or [])
    mapping, leftovers, missing = match_blocks(entries, blocks)

    signals: list[str] = []
    for path in missing[:8]:
        signals.append(f"`{path}` 未匹配到 diff 块（路径含特殊字符时可能出现），已按无内容处理")
    if leftovers:
        signals.append("有 " + str(len(leftovers)) + " 个 diff 块未匹配到文件清单："
                       + "、".join(f"`{p}`" for p in leftovers[:8])
                       + (" 等" if len(leftovers) > 8 else ""))

    # 测试文件总数（在默认排除 src/test 之前统计，用于"是否改了测试"判断）
    test_files_total = sum(1 for e in entries if is_test_path(e["path"]))

    rows: list[dict] = []
    filtered_out = 0
    test_dir_skipped = 0
    for idx, entry in enumerate(entries):
        block = mapping.get(idx, b"")
        text = decode_block(block)
        if entry.get("binary") or BINARY_BLOCK_RE.search(text):
            add = del_ = None
        else:
            add = len(added_lines(text)) if block else None
            del_ = removed_count(text) if block else None

        flags, file_signals = risk_flags(entry, text, add)
        signals.extend(file_signals)

        row = {
            "status": entry["status"],
            "old_path": entry["old_path"],
            "path": entry["path"],
            "add": add,
            "del": del_,
            "flags": flags,
            "score": risk_score(flags),
            "diff_file": None,
            "untracked": bool(entry.get("untracked")),
            "text": text,
            "block": block,
            "matched": idx in mapping,
        }
        if exclude_tests and is_test_source_dir(entry["path"]):
            test_dir_skipped += 1
            continue
        if not path_selected(entry["path"], includes, excludes):
            filtered_out += 1
            continue
        rows.append(row)

    total_add = sum(r["add"] or 0 for r in rows)
    total_del = sum(r["del"] or 0 for r in rows)

    expand_positions: set[int] = set()
    if limit <= 0 or len(rows) <= limit:
        expand_positions = set(range(1, len(rows) + 1))
    else:
        ranked = sorted(range(len(rows)),
                        key=lambda i: (-rows[i]["score"], -(rows[i]["add"] or 0), rows[i]["path"]))
        expand_positions = {i + 1 for i in ranked[:limit]}
        signals.append(f"仅展开前 {limit} 个文件（--limit），其余 "
                       f"{len(rows) - limit} 个未生成逐文件 diff")

    patch_parts: list[bytes] = []
    for pos, row in enumerate(rows, 1):
        row["index"] = pos
        block = row.pop("block")
        if block:
            patch_parts.append(block if block.endswith(b"\n") else block + b"\n")
        if pos not in expand_positions:
            continue
        text = row["text"]
        if not row["matched"]:
            text = "# git 未输出该文件的 diff 块（路径可能含特殊字符），请直接读源码核对\n"
        body = text if not annotate else annotate_added(text)
        if not body.endswith("\n"):
            body += "\n"
        name = f"{pos:03d}-{sanitize(row['path'])}.diff"
        (files_dir / name).write_text(body, encoding="utf-8", newline="\n")
        row["diff_file"] = f"{dir_label}/{name}"

    return {
        "enabled": True,
        "range": " ".join(specs),
        "commits": commits,
        "files": [{k: r[k] for k in ("index", "status", "old_path", "path", "add", "del",
                                     "flags", "score", "diff_file", "untracked")}
                  for r in rows],
        "total_add": total_add,
        "total_del": total_del,
        "filtered_out": filtered_out,
        "test_dir_skipped": test_dir_skipped,
        "test_files_total": test_files_total,
        "expanded": len(expand_positions),
        "not_expanded": len(rows) - len(expand_positions),
        "signals": signals,
    }, rows, b"".join(patch_parts)


# ------------------------------------------------------------ 输出

def write_summary(path: Path, data: dict, fwd_rows: list[dict], rev_rows: list[dict]) -> None:
    lines: list[str] = []
    add = lines.append
    add(f"# 代码审查材料：{data['branch']} ↔ {data['base']}")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 仓库 | `{data['repo']}` |")
    add(f"| 待审引用 | `{data['branch']}`（{data['branch_kind']}，`{data['branch_head']}`） |")
    add(f"| 基线引用 | `{data['base']}`（{data['base_kind']}，`{data['base_head']}`） |")
    add(f"| 分叉点 merge-base | `{data['merge_base_short']}` |")
    add(f"| 差异口径 | {'直接比较 A..B（全部差异）' if data['diff_mode'] == 'direct' else '分叉点..待审（只看待审新增）'} |")
    add(f"| 单元测试 | {'已排除 `src/test`（--include-tests 可纳入）' if data['test_dir_excluded'] else '已纳入 `src/test`'} |")
    add(f"| 方向 | {DIRECTION_LABEL.get(data['direction'], data['direction'])} |")
    add(f"| 生成时间 | {data['generated_at']} |")
    add(f"| 工作区 | {data['worktree_note']} |")
    if data["filters"]["path"] or data["filters"]["exclude"]:
        add(f"| 路径过滤 | 仅含 {data['filters']['path'] or '-'}；排除 {data['filters']['exclude'] or '-'} |")
    add("")
    add("> 逐文件 diff 中新增行带 `+[L行号]` 标注；`*.patch` 为未经解码的原始字节，可直接 `git apply`。")
    if data["filters"]["path"] or data["filters"]["exclude"]:
        add("> 路径过滤只影响清单、逐文件 diff 与 patch，提交列表仍是完整范围。")
    add("")

    fwd, rev = data["forward"], data["reverse"]
    add("## 一、改动规模")
    add("")
    add("| 方向 | 提交数 | 文件数 | +行 | -行 | 过滤掉 | 跳过测试 |")
    add("|---|---|---|---|---|---|---|")
    for label, side in (("待审相对基线（合入基线将包含）", fwd),
                        ("基线相对待审（合回待审会引入）", rev)):
        if side["enabled"]:
            add(f"| {label} | {len(side['commits'])} | {len(side['files'])} | "
                f"{side['total_add']} | {side['total_del']} | {side['filtered_out']} | "
                f"{side['test_dir_skipped']} |")
        else:
            add(f"| {label} | - | - | - | - | 已跳过 | - |")
    add("")

    add("## 二、待审侧提交（合入基线将包含）")
    add("")
    if not fwd["enabled"]:
        add("- 已跳过（--direction 未包含 forward）")
    elif fwd["commits"]:
        for c in fwd["commits"]:
            add(f"- `{c['hash']}` {c['date']} {c['author']}：{c['subject']}")
    else:
        add("- 无（待审侧与基线在分叉点后没有差异）")
    add("")

    add("## 三、基线独有提交（合回待审会引入）")
    add("")
    if not rev["enabled"]:
        add("- 已跳过（--direction 未包含 reverse）")
    elif rev["commits"]:
        for c in rev["commits"]:
            add(f"- `{c['hash']}` {c['date']} {c['author']}：{c['subject']}")
        add("")
        add("> 这些改动合回待审侧时，可能覆盖已有修改、引入基线侧行为变化或产生冲突。")
    else:
        add("- 无（基线没有领先待审侧的提交）")
    add("")

    add("## 四、合入冲突预演（merge-tree，不改工作区）")
    add("")
    previews = data.get("merge_previews", {})
    if not previews:
        add("- 已跳过")
    for key, label in (("forward", f"待审合入基线（`{data['branch']}` → `{data['base']}`）"),
                       ("reverse", f"基线合回待审（`{data['base']}` → `{data['branch']}`）")):
        if key not in previews:
            continue
        mp = previews[key]
        if not mp["supported"]:
            add(f"- {label}：{mp['detail']}")
        elif mp["clean"]:
            add(f"- {label}：无冲突")
        else:
            add(f"- {label}：**存在冲突**")
            for c in mp["conflicts"]:
                add(f"  - `{c}`")
    add("")

    add("## 五、文件清单（待审侧，按原顺序）")
    add("")
    if fwd_rows:
        add("| # | 状态 | 文件 | + | - | 风险标记 | diff |")
        add("|---|---|---|---|---|---|---|")
        for row in fwd_rows:
            link = f"[{row['diff_file']}]({row['diff_file']})" if row["diff_file"] else "-"
            add(f"| {row['index']} | {STATUS_LABEL.get(row['status'], row['status'])} | "
                f"`{row['path']}` | {fmt_num(row['add'])} | {fmt_num(row['del'])} | "
                f"{'、'.join(row['flags']) or '-'} | {link} |")
    else:
        add("- 无文件改动")
    add("")

    add("## 六、反向文件清单（基线侧）")
    add("")
    if not rev["enabled"]:
        add("- 已跳过（--direction 未包含 reverse）")
    elif rev_rows:
        add("| # | 状态 | 文件 | + | - | 风险标记 | diff |")
        add("|---|---|---|---|---|---|---|")
        for row in rev_rows:
            link = f"[{row['diff_file']}]({row['diff_file']})" if row["diff_file"] else "-"
            add(f"| {row['index']} | {STATUS_LABEL.get(row['status'], row['status'])} | "
                f"`{row['path']}` | {fmt_num(row['add'])} | {fmt_num(row['del'])} | "
                f"{'、'.join(row['flags']) or '-'} | {link} |")
    else:
        add("- 无文件改动")
    add("")

    add("## 七、自动信号")
    add("")
    if data["signals"]:
        for s in data["signals"]:
            add(f"- {s}")
    else:
        add("- 无")
    add("")

    add("## 八、建议阅读顺序")
    add("")
    ordered = sorted([r for r in fwd_rows if r["diff_file"]],
                     key=lambda r: (-r["score"], -(r["add"] or 0)))
    if ordered:
        for i, row in enumerate(ordered[:15], 1):
            add(f"{i}. `{row['diff_file']}` —— {row['path']}"
                + ("（生成物/二进制，只需确认是否应入库）" if row["score"] == 0 else ""))
        if len(ordered) > 15:
            add(f"... 其余 {len(ordered) - 15} 个文件见上表")
        if fwd["not_expanded"]:
            add(f"（另有 {fwd['not_expanded']} 个文件受 --limit 限制未生成逐文件 diff）")
    else:
        add("- 无")
    add("")

    add("## 九、其他检查输出")
    add("")
    add("```text")
    add(data["diff_check"] or "git diff --check：无空白/冲突标记问题")
    add("```")
    add("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_report(path: Path, data: dict, fwd_rows: list[dict], rev_rows: list[dict]) -> None:
    fwd, rev = data["forward"], data["reverse"]
    lines: list[str] = []
    add = lines.append
    add(f"# 代码审查报告：`{data['branch']}` → `{data['base']}`")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 仓库 | `{data['repo']}` |")
    add(f"| 待审引用 | `{data['branch']}`（{data['branch_kind']}，`{data['branch_head']}`） |")
    add(f"| 基线引用 | `{data['base']}`（{data['base_kind']}，`{data['base_head']}`） |")
    add(f"| 分叉点 | `{data['merge_base_short']}` |")
    add(f"| 生成时间 | {data['generated_at']} |")
    add(f"| 材料目录 | `{Path(data['paths']['summary']).parent}` |")
    add("")
    add("## 结论")
    add("")
    add("**<可合入 / 修复后合入 / 不可合入>**")
    add("")
    add("> 一句话理由：<例如：存在 1 个 P1（重复消费导致重复记账）与 2 个 P2，建议修复 P1 后合入。>")
    add("")
    add("| 级别 | 数量 | 说明 |")
    add("|---|---|---|")
    add("| P0 阻断 | 0 | |")
    add("| P1 严重 | 0 | |")
    add("| P2 一般 | 0 | |")
    add("| P3 建议 | 0 | |")
    add("")
    add("## 审查范围")
    add("")
    if fwd["enabled"]:
        add(f"- 待审侧：{len(fwd['files'])} 个文件、+{fwd['total_add']} / -{fwd['total_del']}，"
            f"展开 {fwd['expanded']} 个逐文件 diff")
    else:
        add("- 待审侧：已跳过")
    if rev["enabled"]:
        add(f"- 基线侧：{len(rev['files'])} 个文件、+{rev['total_add']} / -{rev['total_del']}")
    else:
        add("- 基线侧：已跳过")
    add(f"- 工作区：{data['worktree_note']}")
    add(f"- 差异口径：{'直接比较 A..B（全部差异）' if data['diff_mode'] == 'direct' else '分叉点..待审（只看待审新增）'}")
    add(f"- 单元测试：{'已排除 src/test（--include-tests 可纳入）' if data['test_dir_excluded'] else '已纳入 src/test'}")
    if data["filters"]["path"] or data["filters"]["exclude"]:
        add(f"- 路径过滤：仅含 {data['filters']['path'] or '-'}；排除 {data['filters']['exclude'] or '-'}")
    add("")
    add("## 改动概览")
    add("")
    if fwd_rows:
        add("| 文件 | +/- | 风险标记 | 改动说明 |")
        add("|---|---|---|---|")
        for row in fwd_rows[:60]:
            add(f"| `{row['path']}` | +{fmt_num(row['add'])}/-{fmt_num(row['del'])} | "
                f"{'、'.join(row['flags']) or '-'} | 待补充 |")
        if len(fwd_rows) > 60:
            add(f"| ... | | | 其余 {len(fwd_rows) - 60} 个文件见 summary.md |")
    else:
        add("- 无文件改动")
    add("")
    add("## 问题清单")
    add("")
    add("| ID | 优先级 | 类别 | 位置 | 问题 | 建议 |")
    add("|---|---|---|---|---|---|")
    add("| CR-01 | P? | <并发/幂等、边界、配置、SQL、兼容、安全…> | `path:line` | 待补充 | 待补充 |")
    add("")
    add("## 详细分析")
    add("")
    add("### CR-01 <标题>（P?）")
    add("")
    add("- **位置**：`<文件>:<行>`（新增行可用 `+[L123]` 标注定位）")
    add("- **问题**：<技术原因，说明为什么不正确>")
    add("- **触发条件**：<什么请求/数据/时序下会发生；主链路还是边缘>")
    add("- **影响**：<报错、数据不一致、资损、性能下降、无法回滚…>")
    add("- **修改建议**：<可直接落地的改法>")
    add("- **验证方式**：<单测/接口回归/SQL 校验/配置缺失演练>")
    add("")
    add("## 反向合并风险")
    add("")
    if rev["enabled"]:
        if rev["commits"]:
            add(f"- 基线领先 {len(rev['commits'])} 个提交、{len(rev['files'])} 个文件：")
            for c in rev["commits"][:20]:
                add(f"  - `{c['hash']}` {c['subject']}")
            add("- 逐文件见 `files-reverse/`；冲突与反向文件的冲突预演见 summary.md 第四节")
            add("- 需逐项确认：基线侧行为变化、当前分支被覆盖的文件、冲突解决口径")
        else:
            add("- 无（基线未领先待审侧）")
    else:
        add("- 已跳过（--direction 未包含 reverse）")
    add("")
    add("## 已验证项")
    add("")
    add("- [ ] 代码可编译/启动（<命令或说明>）")
    add("- [ ] 单测通过（<命令>）")
    add("- [ ] 关键接口回归（<接口/用例>）")
    add("- [ ] DDL 可在 SIT 执行且可回滚")
    add("- [ ] 新增配置在缺失时有明确兜底")
    add("")
    add("> 未实际执行的项不要勾选，改写\"未执行\"。")
    add("")
    add("## 未覆盖范围")
    add("")
    uncovered: list[str] = []
    for label, side in (("待审侧", fwd), ("基线侧", rev)):
        if not side["enabled"]:
            continue
        for row in (fwd_rows if side is fwd else rev_rows):
            if "二进制" in row["flags"] or "未展开（超限）" in row["flags"] or not row["matched"]:
                uncovered.append(f"- {label} `{row['path']}`："
                                 f"{'、'.join(row['flags']) or '未匹配到 diff'}")
    if uncovered:
        lines.extend(uncovered[:50])
        if len(uncovered) > 50:
            add(f"- ... 其余 {len(uncovered) - 50} 个未覆盖文件见 summary.md")
    else:
        add("- 无（所有文本改动均已生成逐文件 diff）")
    if not data["worktree_included"] and "未纳入" in data["worktree_note"]:
        add(f"- 未提交改动/未跟踪文件未纳入：{data['worktree_note']}")
    add("")
    add("## 待确认")
    add("")
    add("| 事项 | 需要的信息 | 找谁/怎么确认 |")
    add("|---|---|---|")
    add("| 是否包含 DDL 及执行顺序 | | |")
    add("| 是否需要配置/开关同步上线 | | |")
    add("| 是否存在跨服务/跨仓库配套改动 | | |")
    add("")
    add("## 附：自动信号")
    add("")
    if data["signals"]:
        for s in data["signals"]:
            add(f"- {s}")
    else:
        add("- 无")
    add("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


# ------------------------------------------------------------ 入口

def flatten_patterns(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend(p.strip() for p in value.split(",") if p.strip())
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="采集待审引用与基线引用的代码差异，生成审查材料（只读）")
    parser.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    parser.add_argument("--branch", default="HEAD",
                        help="待审侧：当前分支名、其他分支名、tag 或 commitId（默认当前 HEAD）")
    parser.add_argument("--base", default=None,
                        help="基线侧：分支名、tag 或 commitId（默认 origin/master → master → origin/main → main）")
    parser.add_argument("--out", default=None, help="输出目录（默认系统临时目录）")
    parser.add_argument("--fetch", action="store_true", help="先执行 git fetch --prune origin")
    parser.add_argument("--raw-diff", action="store_true", help="逐文件 diff 不打 [L行号] 标注")
    parser.add_argument("--list-refs", action="store_true",
                        help="列出可选分支、tag 与近期提交后退出")
    parser.add_argument("--refs-limit", type=int, default=40,
                        help="--list-refs 显示的分支/tag 数量上限（默认 40）")
    parser.add_argument("--direction", choices=["both", "forward", "reverse"], default="both",
                        help="采集方向：both（默认）/ forward / reverse")
    parser.add_argument("--diff-mode", choices=["direct", "merge-base"], default="direct",
                        help="差异口径：direct（默认）=直接比较 A..B 两个引用的全部差异；"
                             "merge-base=只看待审侧自分叉点后的新增")
    parser.add_argument("--include-tests", action="store_true",
                        help="纳入 src/test 单元测试目录（默认排除）")
    parser.add_argument("--include-worktree", action="store_true",
                        help="把当前工作区未提交改动与未跟踪文件纳入待审侧（仅当待审侧是当前 HEAD）")
    parser.add_argument("--max-untracked-size", type=int, default=262144,
                        help="未跟踪文件展开上限，字节（默认 262144；超出只记录不展开）")
    parser.add_argument("--limit", type=int, default=300,
                        help="最多生成多少个逐文件 diff（默认 300，0 表示不限）")
    parser.add_argument("--path", action="append", default=[], metavar="GLOB",
                        help="只审查匹配的路径（可重复或逗号分隔，* 可跨 /）")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="排除匹配的路径（可重复或逗号分隔）")
    args = parser.parse_args()

    includes = flatten_patterns(args.path)
    excludes = flatten_patterns(args.exclude)

    try:
        repo = resolve_repo(args.repo)
        if args.list_refs:
            rc, raw, _ = git_raw(repo, [
                "for-each-ref", "--sort=-committerdate",
                "--format=%(refname:short)\t%(committerdate:short)\t%(subject)",
                "refs/heads", "refs/remotes", "refs/tags",
            ], check=False)
            rc, raw_commits, _ = git_raw(repo, ["log", "--all", "--oneline", "-20",
                                                "--decorate", "--no-color"], check=False)
            print("### 分支 / 远程分支 / tag（按提交时间倒序）")
            ref_lines = []
            for line in decode_block(raw).split("\n"):
                if not line.strip():
                    continue
                ref = line.split("\t", 1)[0]
                if ref in ("origin", "upstream") or ref.endswith("/HEAD"):
                    continue
                ref_lines.append(line)
            if args.refs_limit > 0:
                ref_lines = ref_lines[:args.refs_limit]
            print("\n".join(ref_lines) if ref_lines else "（无）")
            print("\n### 最近 20 条提交（--all）")
            print(decode_block(raw_commits).strip() or "（无）")
            return 0
        if args.fetch:
            rc, out, err = git_raw(repo, ["fetch", "--prune", "origin"], check=False)
            if rc != 0:
                print(f"[warn] git fetch 失败，继续使用本地引用："
                      f"{(decode_bytes(err) or decode_bytes(out)).strip()}", file=sys.stderr)
        branch = resolve_branch(repo, args.branch)
        base = resolve_base(repo, args.base)
        if not rev_parse(repo, base):
            raise GitError(f"无法解析基线引用：{base}")
        rc, out, err = git_raw(repo, ["merge-base", base, branch], check=False)
        merge_base = decode_bytes(out).strip()
        if (rc != 0 or not merge_base) and args.diff_mode == "merge-base":
            raise GitError(f"`{base}` 与 `{branch}` 没有共同祖先，无法按分叉点对比；"
                           f"可改用 --diff-mode direct：{decode_bytes(err).strip()}")
        if not merge_base:
            merge_base = ""
    except GitError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    use_worktree = args.include_worktree
    if use_worktree and rev_parse(repo, branch) != rev_parse(repo, "HEAD"):
        print("[error] --include-worktree 只支持待审侧为当前 HEAD（工作区改动挂在 HEAD 上）；"
              f"当前 --branch 指向 `{branch}`（{rev_parse(repo, branch)[:8]}），"
              f"HEAD 为 {rev_parse(repo, 'HEAD')[:8]}", file=sys.stderr)
        return 2

    direct = args.diff_mode == "direct"
    if direct:
        fwd_specs = [base] if use_worktree else [f"{base}..{branch}"]
        rev_specs = [f"{branch}..{base}"]
        fwd_commit_range = f"{base}..{branch}"
    else:
        fwd_specs = [merge_base] if use_worktree else [f"{merge_base}..{branch}"]
        rev_specs = [f"{merge_base}..{base}"]
        fwd_commit_range = f"{merge_base}..{branch}"

    forward_commits = log_commits(repo, fwd_commit_range)
    reverse_commits = log_commits(repo, rev_specs[0])
    base_is_ancestor = is_ancestor(repo, base, branch)

    rc, status_raw, _ = git_raw(repo, ["status", "--porcelain"], check=False)
    status_lines = [line for line in decode_block(status_raw).split("\n") if line.strip()]
    wt_changed = sum(1 for line in status_lines if not line.startswith("??"))
    wt_untracked = sum(1 for line in status_lines if line.startswith("??"))

    if use_worktree:
        worktree_note = (f"已纳入工作区改动（{wt_changed} 个已跟踪文件未提交、"
                         f"{wt_untracked} 个未跟踪文件）")
    elif wt_changed or wt_untracked:
        worktree_note = (f"{wt_changed} 个已跟踪文件有未提交改动、{wt_untracked} 个未跟踪文件"
                         f"（未纳入，可用 --include-worktree）")
    else:
        worktree_note = "干净"

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out).expanduser() if args.out else \
        Path(tempfile.gettempdir()) / "code-review" / f"{repo.name}-{ts}"
    files_dir = out_dir / "files"
    files_rev_dir = out_dir / "files-reverse"

    signals: list[str] = []
    if not use_worktree and (wt_changed or wt_untracked):
        signals.append(f"工作区存在未提交改动/未跟踪文件（{wt_changed} / {wt_untracked}），"
                       "本次未纳入；需要时加 --include-worktree")
    if direct and not base_is_ancestor:
        signals.append(f"基线 `{base}` 不是待审侧 `{branch}` 的祖先：直接差异（A..B）会把"
                       "基线侧改动按反向显示（新增/删除颠倒）；只想看待审侧新增时用 "
                       "--diff-mode merge-base")
    exclude_tests = not args.include_tests

    forward = empty_side()
    reverse = empty_side()
    fwd_rows: list[dict] = []
    rev_rows: list[dict] = []
    forward_patch = b""
    reverse_patch = b""
    diff_check_text = ""
    previews: dict[str, dict] = {}

    out_skip: tuple[str, ...] = ()
    if use_worktree:
        try:
            rel_out = out_dir.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            rel_out = ""
        if rel_out and rel_out != ".":
            out_skip = (rel_out,)
            signals.append(f"输出目录位于仓库内（`{rel_out}`），已从工作区未跟踪清单中排除")

    if args.direction in ("both", "forward"):
        extra_entries: list[dict] = []
        extra_blocks: list[bytes] = []
        if use_worktree:
            extra_entries, extra_blocks, untracked_signals = collect_untracked(
                repo, args.max_untracked_size, includes, excludes, out_skip)
            signals.extend(untracked_signals)
        files_dir.mkdir(parents=True, exist_ok=True)
        forward, fwd_rows, forward_patch = build_side(
            repo, fwd_specs, forward_commits, files_dir, "files",
            args.limit, not args.raw_diff, includes, excludes, exclude_tests,
            extra_entries, extra_blocks)
        signals.extend(forward["signals"])
        (out_dir / "diff-forward.patch").write_bytes(forward_patch)
        diff_check_text = diff_check(repo, fwd_specs)
        previews["forward"] = merge_preview(repo, base, branch)

    if args.direction in ("both", "reverse"):
        files_rev_dir.mkdir(parents=True, exist_ok=True)
        reverse, rev_rows, reverse_patch = build_side(
            repo, rev_specs, reverse_commits, files_rev_dir, "files-reverse",
            args.limit, not args.raw_diff, includes, excludes, exclude_tests)
        signals.extend(reverse["signals"])
        (out_dir / "diff-reverse.patch").write_bytes(reverse_patch)
        if not diff_check_text:
            diff_check_text = diff_check(repo, rev_specs)
        previews["reverse"] = merge_preview(repo, branch, base)

    # ---- 汇总信号（在单侧信号之后补充全局判断）
    src_changed = [r for r in fwd_rows
                   if SRC_CODE_RE.search(r["path"]) and not is_test_path(r["path"])
                   and r["status"] != "D"]
    if forward["enabled"] and src_changed and forward["test_files_total"] == 0:
        signals.append("代码文件有改动但未改动任何测试文件（`src/test/**`、`*.spec.*`、`*_test.*` 等）")

    for label, side in (("待审侧", forward), ("基线侧", reverse)):
        if side["enabled"] and side["test_dir_skipped"]:
            signals.append(f"{label}默认排除 `src/test` 单元测试目录 "
                           f"{side['test_dir_skipped']} 个文件（--include-tests 可纳入）")

    binary = [r["path"] for r in fwd_rows
              if "二进制" in r["flags"] or "生成物" in r["flags"]]
    if binary:
        signals.append("二进制/生成物不进入逐行审查，只需确认是否应入库、体积是否合理："
                       + "、".join(f"`{p}`" for p in binary[:8])
                       + (" 等" if len(binary) > 8 else ""))

    for flag, label in (("配置变更", "配置"), ("依赖/构建", "依赖/构建"),
                        ("数据库/SQL", "数据库/SQL"), ("部署", "部署"),
                        ("删除文件", "删除"), ("疑似敏感信息", "疑似密钥/口令"),
                        ("残留冲突标记", "残留冲突标记")):
        hit = [r["path"] for r in fwd_rows if flag in r["flags"]]
        if hit:
            signals.append(f"{label}类改动 {len(hit)} 个："
                           + "、".join(f"`{p}`" for p in hit[:8])
                           + (" 等" if len(hit) > 8 else ""))

    large = [r["path"] for r in fwd_rows if "大改动" in r["flags"]]
    if large:
        signals.append("大改动文件（diff > 800 行，必须读源码全文核对上下文）："
                       + "、".join(f"`{p}`" for p in large[:8]))

    if reverse["commits"]:
        signals.append(f"待审侧缺少基线侧 {len(reverse['commits'])} 个提交，"
                       "合回/对齐时需评估覆盖风险（见 summary.md 第三、四节）")

    base_parent = base.split("/", 1)[-1]
    if base.startswith("origin/") and ref_exists(repo, base_parent):
        local_head = rev_parse(repo, base_parent)
        remote_head = rev_parse(repo, base)
        if local_head and remote_head and local_head != remote_head:
            signals.append(f"本地 `{base_parent}`（{local_head[:8]}）与 `{base}`"
                           f"（{remote_head[:8]}）不一致，确认审查基线是否最新")

    duplicated = len(signals) - len(set(signals))
    if duplicated > 0:
        seen: set[str] = set()
        unique: list[str] = []
        for s in signals:
            if s in seen:
                continue
            seen.add(s)
            unique.append(s)
        signals = unique

    def side_json(side: dict) -> dict:
        return {k: side[k] for k in ("enabled", "range", "commits", "files", "total_add",
                                     "total_del", "filtered_out", "test_dir_skipped",
                                     "test_files_total", "expanded", "not_expanded")}

    branch_head = rev_parse(repo, branch)[:8]
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": str(repo),
        "branch": branch,
        "branch_kind": ref_kind(repo, branch),
        "branch_head": branch_head,
        "base": base,
        "base_kind": ref_kind(repo, base),
        "base_head": rev_parse(repo, base)[:8],
        "merge_base": merge_base,
        "merge_base_short": merge_base[:8] if merge_base else "-",
        "diff_mode": args.diff_mode,
        "direction": args.direction,
        "test_dir_excluded": exclude_tests,
        "worktree_included": use_worktree,
        "worktree_note": worktree_note,
        "filters": {"path": includes, "exclude": excludes},
        "forward": side_json(forward),
        "reverse": side_json(reverse),
        "merge_preview": previews.get("forward"),
        "merge_previews": previews,
        "signals": signals,
        "diff_check": diff_check_text,
        "paths": {
            "summary": str(out_dir / "summary.md"),
            "report": str(out_dir / "report.md"),
            "index": str(out_dir / "index.json"),
            "files_dir": str(files_dir) if forward["enabled"] else "",
            "files_reverse_dir": str(files_rev_dir) if reverse["enabled"] else "",
            "forward_patch": str(out_dir / "diff-forward.patch") if forward["enabled"] else "",
            "reverse_patch": str(out_dir / "diff-reverse.patch") if reverse["enabled"] else "",
        },
    }

    write_summary(out_dir / "summary.md", data, fwd_rows, rev_rows)
    write_report(out_dir / "report.md", data, fwd_rows, rev_rows)
    (out_dir / "index.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print(f"审查材料已生成：{out_dir}")
    print(f"待审 {branch}（{data['branch_kind']}，{branch_head}） vs "
          f"基线 {base}（{data['base_kind']}，{data['base_head']}）")
    if forward["enabled"]:
        print(f"改动：{len(forward['commits'])} 提交 / {len(forward['files'])} 文件 / "
              f"+{forward['total_add']} -{forward['total_del']}")
        if forward["filtered_out"]:
            print(f"路径过滤：跳过 {forward['filtered_out']} 个文件")
        if forward["not_expanded"]:
            print(f"逐文件 diff：展开 {forward['expanded']} 个，"
                  f"其余 {forward['not_expanded']} 个受 --limit 限制")
    if reverse["commits"]:
        print(f"基线领先：{len(reverse['commits'])} 提交（合回待审会引入，见 files-reverse/）")
    for key, label in (("forward", "待审→基线"), ("reverse", "基线→待审")):
        mp = previews.get(key)
        if mp and mp.get("supported") and not mp.get("clean"):
            print(f"冲突预演（{label}）：{len(mp.get('conflicts', []))} 个冲突文件")
    print(f"先读：{out_dir / 'summary.md'}；报告骨架：{out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
