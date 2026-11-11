---
name: code-review
description: 代码审查：对比 master 与待审分支或 commitId（默认当前分支），逐文件分析合入后会引入的问题，按 P0-P3 分级并给出可执行的修改建议。默认直接比较两侧最新提交（A..B）并排除 src/test 单元测试目录。当用户要求"代码审查""review 代码""看看这个分支/这个提交合入有什么问题""对比 master 改动""只审核 A 和 B 之间的改动""合并前检查""合入评估"时使用。
version: 1.3.0
---

# 代码审查（master ↔ 待审分支/commit）

对待审侧（当前分支、手动指定的分支或 commitId）相对基线分支（默认 master）的改动做合入前审查：找出会引入的缺陷、兼容性/配置/数据问题，给出优先级和修改方式。默认**只读**，不改代码。

## 参数

对比的两侧都可以是**当前分支、其他分支名、tag 或 commitId**：

| 参数 | 默认 | 说明 |
|---|---|---|
| 仓库路径 | 当前工作区 | 不在 git 仓库内时先问用户 |
| 待审侧 `--branch` | `HEAD`（当前分支） | 用户指定后填分支名、tag 或 commitId（短/长均可） |
| 基线侧 `--base` | `origin/master` → `master` → `origin/main` → `main` | 也可填分支名、tag 或 commitId |
| 差异口径 `--diff-mode` | `direct` | `direct`=直接比较两侧最新提交（A..B，含双方各自的改动）；`merge-base`=只看待审侧相对分叉点的新增 |
| 方向 | 双向 | 正向=待审侧合入基线会引入的问题；反向=基线合回待审侧会引入的问题 |
| 单元测试 | 排除 | 默认跳过任何 `src/test/...`（含多模块 `module/src/test/...`）；加 `--include-tests` 纳入 |
| 工作区改动 | 不纳入 | 加 `--include-worktree` 把未提交改动（含已暂存）与未跟踪文件并入待审侧；只在待审侧＝当前 HEAD 时可用 |
| 路径范围 | 全部 | `--path` / `--exclude` 过滤文件（glob，`*` 可跨 `/`，可重复或逗号分隔） |

用户说"和最新 master 比"时加 `--fetch`（会访问远端）；否则用本地已有引用，并在报告中注明两侧的实际提交号。

用户说"只审核 A 和 B 之间的改动"（A=基线最新提交、B=待审侧最新提交）时，用 `--diff-mode direct`（默认）。注意：若基线不是待审侧祖先，直接差异会把基线独有的改动反向显示成"删除"，脚本会在 summary 里给出信号；只想看待审侧新增时改用 `--diff-mode merge-base`。

用户没指定时用当前分支；**用户指定了分支/commitId 就严格按指定值比较，校验失败时列候选让用户重选，不要静默回落到当前分支**。

## 执行流程

### Step 0：确认范围

- 待审侧：未指定则当前分支；指定了分支/commitId 时先确认该引用存在。
- 基线侧：默认自动识别；用户指定（如 `--base 3f2a1bc`）时按指定值。
- 差异口径：默认 `direct`（直接比两侧最新提交 A..B）；用户要求"只看当前分支新增/相对分叉点"时用 `--diff-mode merge-base`。
- 单元测试：默认排除 `src/test`，用户要求一起审时加 `--include-tests`；报告里写清该选择。
- 引用不存在或不知道有哪些分支/commit 时，先列候选再问用户：

```bash
python <本技能目录>/review_diff.py --repo <仓库> --list-refs
# 等价于
git branch -a --sort=-committerdate
git log --all --oneline -20 --decorate
```

- 工作区有未提交改动/未跟踪文件时：默认只审已提交内容，并在报告"未覆盖范围"注明；用户要求连工作区一起审时加 `--include-worktree`（仅当待审侧是当前 HEAD）。
- 用户指定了文件/模块时，用 `--path`/`--exclude` 收窄范围，并在报告中写清审查范围。

### Step 1：采集差异

```bash
# 当前分支 vs 自动识别的 master
python <本技能目录>/review_diff.py --repo <仓库路径>

# 指定待审分支 vs master
python <本技能目录>/review_diff.py --repo <仓库路径> --branch feature/xxx

# 指定 commitId 作为待审侧
python <本技能目录>/review_diff.py --repo <仓库路径> --branch 3f2a1bc

# 指定基线为某个 commitId / 分支
python <本技能目录>/review_diff.py --repo <仓库路径> --base a1b2c3d

# 两个任意引用比较（与当前所在分支无关）
python <本技能目录>/review_diff.py --repo <仓库路径> --branch feature/a --base 0d9f2c1

# 只审核 A、B 两个最新提交之间的改动（默认 direct 口径，默认排除 src/test）
python <本技能目录>/review_diff.py --repo <仓库路径> --base <A> --branch <B>

# 只想看待审侧相对分叉点的新增（不含基线独有改动）
python <本技能目录>/review_diff.py --repo <仓库路径> --base origin/master --diff-mode merge-base

# 连单元测试目录 src/test 一起审
python <本技能目录>/review_diff.py --repo <仓库路径> --include-tests

# 需要最新远端 master 时
python <本技能目录>/review_diff.py --repo <仓库路径> --base origin/master --fetch

# 连当前工作区未提交改动、未跟踪文件一起审
python <本技能目录>/review_diff.py --repo <仓库路径> --include-worktree

# 只看某些路径（排除测试/生成物）
python <本技能目录>/review_diff.py --repo <仓库路径> --path "src/**" --exclude "**/*.min.js,**/dist/**"
```

脚本只执行 git 查询和 `merge-tree` 冲突预演，不改工作区。产出：

| 文件 | 内容 |
|---|---|
| `summary.md` | 提交清单、改动规模、文件风险清单、阅读顺序、双向冲突预演、自动信号 |
| `report.md` | 审查报告骨架（结论/P0-P3/反向风险/已验证/未覆盖/待确认） |
| `diff-forward.patch` | 待审侧原始 patch（direct 为 A..B；merge-base 为分叉点..B，未解码字节，可直接 `git apply`） |
| `diff-reverse.patch` | 基线侧原始 patch（B..A） |
| `files/NNN-xxx.diff` | 待审侧逐文件 diff，新增行带 `+[L123]` 新文件行号标注 |
| `files-reverse/NNN-xxx.diff` | 基线侧逐文件 diff（反向审查用） |
| `index.json` | 结构化数据，每个文件带 `flags`/`score`/`diff_file` |

常用参数：

```bash
--base master             # 强制用本地 master
--diff-mode direct        # 默认：直接比较两侧最新提交（A..B）
--diff-mode merge-base    # 只看待审侧相对分叉点的新增
--include-tests           # 把 src/test 单元测试目录纳入审查（默认排除）
--direction forward       # 只关心"合入基线"时，跳过反向采集
--direction reverse       # 只评估"把基线合回当前分支"
--include-worktree        # 纳入未提交改动与未跟踪文件（待审侧须为当前 HEAD）
--path / --exclude        # 路径过滤（glob）
--limit 300               # 最多生成多少个逐文件 diff（0=不限）
--max-untracked-size      # 未跟踪文件展开上限，默认 262144 字节
--raw-diff                # 不要 [L行号] 标注，保留标准 patch
--out <目录>              # 指定输出目录（默认系统临时目录）
```

### Step 2：读总览，建立改动意图

1. 读 `summary.md`：提交列表 → 判断这组改动声称做了什么；文件清单 → 判断实际改了什么。两者不一致（如提交说修 A 却改了 B、混入调试代码/无关格式化）就是一条 finding。
2. 先看"自动信号"：敏感信息、残留冲突标记、删除文件、配置/依赖/SQL 变更、无测试改动、大改动文件、工作区未纳入、`src/test` 被跳过、基线不是待审侧祖先。
3. 看"合入冲突预演"：脚本会分别预演"待审合入基线"和"基线合回待审"两个方向；有冲突时把冲突文件与解决口径写入报告，冲突解决方式必须人工确认。

### Step 3：逐文件审查

按 `summary.md` 的阅读顺序读 `files/*.diff`；基线有独有提交时，同时读 `files-reverse/*.diff` 评估合回风险。以下情况必须 `Read` 源文件全文/大段上下文，不能只看 diff：

- 删除、重命名、文件移动
- 配置、依赖、SQL/DDL、启动类、公共工具类、接口定义
- `大改动` 标记（diff > 800 行）或 `新增行多`
- 修改了方法签名、返回值、序列化字段、异常类型
- diff 中看不到调用方（需要 Grep 找调用点确认影响面）

审查维度见 [references/checklist.md](references/checklist.md)。不要抽样：所有改动文件都要过一遍，大文件按模块分段读。

### Step 4：核实证据

- `+[L123]` 是新增行在**新文件**中的行号，可直接引用；删除行和上下文行必须 `Read` 源文件核对。
- 每条问题给出：`文件:行` + 关键代码（≤3 行）+ 触发条件 + 后果 + 修改方式。
- 不能确定是不是 bug 的，放"待确认"并说明需要什么信息（配置值、调用方、数据分布），**不要臆测**。
- 同一根因只报一条，合并多个文件的表现，避免刷条数。

### Step 5：输出报告

脚本已在 `<输出目录>/report.md` 生成骨架（结论、审查范围、改动概览、问题清单、详细分析、反向风险、已验证、未覆盖、待确认）。在骨架上填写，结构参照 [references/report-template.md](references/report-template.md)；聊天里给"结论 + P0/P1 摘要 + 报告路径"。

结论三选一：

- **可合入**：无 P0/P1，P2/P3 可留待后续
- **修复后合入**：存在 P1，或 P2 涉及主链路
- **不可合入**：存在 P0（资损/安全/编译失败/接口不兼容/数据不可回滚）

### Step 6：修复（仅当用户明确要求）

默认只给建议不动代码。用户要求修复时：

1. 按 P0 → P1 → P2 顺序，一次只改一个根因；
2. 每处修改说明验证方式（单测、接口回归、`EXPLAIN`、配置缺失时的降级行为）；
3. 不顺手重构、不扩大改动面；改完重新跑一次采集脚本确认 diff 范围。

## 优先级定义

| 级别 | 判定 | 典型例子 |
|---|---|---|
| **P0 阻断** | 合入即故障、资损、安全事故，或让构建/启动失败 | 密钥/口令入库；接口字段删除或语义变更导致调用方解析失败；DDL 不可回滚且无备份；空指针在启动路径必现；并发扣款无幂等 |
| **P1 严重** | 主链路逻辑错误、数据不一致、故障难恢复 | 事务边界错误/漏回滚；重复消费；金额计算精度/币种错误；异常被吞导致静默失败；连接/流/线程池泄漏；分页丢失导致全量加载；越权访问 |
| **P2 一般** | 边界与异常分支、性能隐患、可观测性缺失 | 空值/空集合未处理（非主链路）；N+1 查询、缺索引的大表扫描；新配置缺失时行为不明；日志缺 traceId/关键入参；重试无退避 |
| **P3 建议** | 可读性、命名、重复代码、注释 | 命名不一致、魔法值、无用 import、注释过期 |

判定口径：**先看触发条件是否在主链路上、后果是否可恢复**。只影响内部工具/日志格式的，不拔高到 P0/P1。

## 硬性约束

- 默认不修改代码、不提交、不切换/合并/重置分支，不执行 `git checkout/reset/merge/clean`。
- 默认只审已提交内容；只有加 `--include-worktree` 时才把未提交改动/未跟踪文件纳入，且必须在报告中注明。
- 默认排除 `src/test`；报告中必须写明测试目录是否纳入（含跳过数量），不能默认忽略这一点。
- 不把 `summary.md` 的自动信号直接当结论，信号只是线索；报告里每条问题都要回到源码确认。
- 不把 diff 里出现的密钥/口令明文写进报告或聊天；只写"文件:行 + 命中类型"。
- 不在报告里省略"未覆盖范围"（未提交改动、二进制、超限未展开、生成代码、未运行的测试）。
- 不凭文件名或提交信息推断逻辑，必须看 diff 和源码。
- `*.patch` 是原始字节，不要用文本编辑器改写后声称与 git 输出等价；逐文件 diff 才是解码后的阅读版。

## 常见场景

- **只审 A..B 两个最新提交之间**（A=基线最新提交、B=待审侧最新提交）：用 `--base <A> --branch <B>`，默认 `direct` 口径。若 A 不是 B 的祖先（两侧各自前进），直接差异会把 A 独有的改动反向显示为删除，需在报告中区分"待审侧新增"与"基线侧改动"；只要看后者请改 `--diff-mode merge-base` 或读 `files-reverse/`。
- **默认排除单元测试**：`src/test/**`（含多模块）不计入审查，跳过数量记在 summary；需要一起看时加 `--include-tests`。注意 `src/main/**/XxxTest.java` 不算测试目录，仍会审查。
- **分支落后基线很多**：正向改动可能已经包含在基线里；重点看 `files-reverse/`、反向冲突预演和"待审侧落后基线"信号，评估合回时的覆盖/回退风险。
- **工作区还没提交**：加 `--include-worktree` 一起审；未跟踪文件超过 `--max-untracked-size` 或为二进制时只会被记录、不展开，报告中列入"未覆盖范围"。
- **只想看某个模块**：用 `--path "module/**"` 收窄，配合 `--exclude` 去掉生成物/测试；报告里写明这是局部审查。
- **纯新增模块**：重点看依赖版本、配置项默认值、对外接口契约、异常路径，而不是逐行挑风格。
- **大量格式化/重命名**：先确认是否有真实逻辑改动（用 `--raw-diff` 或 `git diff -w`），把噪音和逻辑改动分开报。
- **脚本/技能仓库**（本仓库）：重点看密钥是否入库、路径硬编码、跨平台兼容（Windows/Linux）、脚本是否具备幂等和失败回滚。
