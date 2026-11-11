#!/usr/bin/env bash
# 技能同步：本仓库 -> ~/.qoder/skills 的独立副本
#
#   ./sync_skill.sh --check            只报漂移，不写任何东西
#   ./sync_skill.sh --all              同步全部技能
#   ./sync_skill.sh sit-database-query 只同步指定技能（按仓库目录名或 name 字段都行）
#   ./sync_skill.sh --all --force      连「安装侧更新」的文件也覆盖（覆盖前逐个备份）
#
# 安全约定：
#   - 永不删除目标侧文件；只在目标侧多出来的文件会列出来让你自己判断
#   - 目标是联接/junction 时拒绝写入（先手工 cmd //c rmdir 摘链，别用 rm -rf）
#   - 目标文件比仓库新 => 视为安装侧有未回灌的改动，默认跳过该文件

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="${SKILLS_DEST:-$HOME/.qoder/skills}"
CHECK=0
FORCE=0
WANT=()

for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --force) FORCE=1 ;;
    --all) : ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    --*) echo "未知选项: $a" >&2; exit 2 ;;
    *) WANT+=("$a") ;;
  esac
done

ALL=0
[ ${#WANT[@]} -eq 0 ] && ALL=1
[ "$ALL" = 1 ] || for a in "$@"; do [ "$a" = "--all" ] && ALL=1; done

EXCLUDE='__pycache__|\.pyc$|\.sync_backups/'
drift=0
refused=0
matched=""

skill_dirs() {
  local d
  for d in "$REPO"/*/; do
    [ -f "$d/SKILL.md" ] || continue
    printf '%s\n' "${d%/}"
  done
}

selected() {  # 按仓库目录名或 name 字段匹配用户给的名字
  local dir="$1" base nm
  base="$(basename "$dir")"
  nm="$(sed -n 's/^name:[[:space:]]*//p' "$dir/SKILL.md" | head -1 | tr -d '\r')"
  if [ "$ALL" = 1 ]; then return 0; fi
  for w in "${WANT[@]}"; do
    if [ "$w" = "$base" ] || [ "$w" = "$nm" ]; then
      matched="$matched
$w"
      return 0
    fi
  done
  return 1
}

echo "仓库: $REPO"
echo "目标: $DEST_ROOT"
[ "$CHECK" = 1 ] && echo "模式: 只检查" || { [ "$FORCE" = 1 ] && echo "模式: 同步(--force)" || echo "模式: 同步(跳过安装侧更新的文件)"; }
echo

while IFS= read -r dir; do
  selected "$dir" || continue
  base="$(basename "$dir")"
  name="$(sed -n 's/^name:[[:space:]]*//p' "$dir/SKILL.md" | head -1 | tr -d '\r')"
  [ -n "$name" ] || name="$base"
  dest="$DEST_ROOT/$name"

  if [ -L "$dest" ]; then
    printf '%-30s 拒绝：目标是联接 -> %s\n' "$base" "$(readlink "$dest")"
    printf '%-30s   先摘链: cmd //c rmdir "%s"，再重跑本脚本\n' "" "$(cygpath -w "$dest")"
    refused=$((refused+1)); drift=$((drift+1)); continue
  fi

  new=0; same=0; changed=0; held=0; extra=0
  while IFS= read -r rel; do
    src_f="$dir/$rel"
    dst_f="$dest/$rel"
    if [ ! -f "$dst_f" ]; then
      new=$((new+1))
      if [ "$CHECK" = 0 ]; then
        mkdir -p "$(dirname "$dst_f")"; cp -f "$src_f" "$dst_f"
      fi
      echo "    + 新增  $rel"
      continue
    fi
    if cmp -s "$src_f" "$dst_f"; then same=$((same+1)); continue; fi
    # 内容不同：比较时间戳，安装侧更新则默认不动
    s_m=$(stat -c %Y "$src_f"); d_m=$(stat -c %Y "$dst_f")
    if [ "$d_m" -gt "$s_m" ] && [ "$FORCE" = 0 ]; then
      held=$((held+1))
      echo "    ! 跳过  $rel（安装侧 $(date -d "@$d_m" '+%m-%d %H:%M') 比仓库 $(date -d "@$s_m" '+%m-%d %H:%M') 新，先回灌仓库或用 --force）"
      continue
    fi
    changed=$((changed+1))
    if [ "$CHECK" = 0 ]; then
      if [ "$d_m" -gt "$s_m" ]; then
        bk="$dest/.sync_backups/$rel.$(date '+%Y%m%d-%H%M%S')"
        mkdir -p "$(dirname "$bk")"; cp -p "$dst_f" "$bk"
        echo "      备份 -> ${bk#"$dest"/}"
      fi
      cp -f "$src_f" "$dst_f"
    fi
    echo "    ~ 覆盖  $rel"
  done < <(cd "$dir" && find . -type f \
            | sed 's|^\./||' \
            | grep -Ev "($EXCLUDE)" | sort)

  # 目标侧独有文件（只报告，不删）
  if [ -d "$dest" ]; then
    while IFS= read -r rel; do
      [ -f "$dir/$rel" ] && continue
      extra=$((extra+1)); echo "    ? 仅在安装侧  $rel"
    done < <(cd "$dest" && find . -type f | sed 's|^\./||' | grep -Ev "($EXCLUDE)" | sort)
  fi

  total=$((new+same+changed+held))
  status="一致"
  { [ $new -gt 0 ] || [ $changed -gt 0 ] || [ $held -gt 0 ] || [ $extra -gt 0 ]; } && status="有变动"
  [ "$status" = "有变动" ] && drift=$((drift+1))
  printf '%-30s -> %-28s %s  共%d 同%d 新增%d 覆盖%d 跳过%d 仅目标%d\n' \
    "$base" "$name" "$status" "$total" "$same" "$new" "$changed" "$held" "$extra"
done < <(skill_dirs)

echo
if [ "$ALL" = 0 ]; then
  missing=""
  for w in "${WANT[@]}"; do
    case "
$matched" in
      *"
$w"*) : ;;
      *) missing="$missing $w" ;;
    esac
  done
  if [ -n "${missing# }" ]; then
    echo "未找到技能:${missing}" >&2
    echo "  仓库里可用的技能目录: $(while IFS= read -r d3; do basename "$d3"; done < <(skill_dirs) | tr '\n' ' ')" >&2
    exit 2
  fi
fi

if [ "$CHECK" = 1 ]; then
  [ $drift -gt 0 ] && echo "结果: $drift 个技能与安装副本不一致（未做任何修改）" || echo "结果: 全部一致"
  exit $([ $drift -gt 0 ] && echo 1 || echo 0)
fi
[ $refused -gt 0 ] && echo "结果: 有 $refused 个目标是联接，已拒绝写入" 
echo "结果: 同步完成（未删除任何文件）"
exit 0
