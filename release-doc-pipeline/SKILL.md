---
name: release-doc-pipeline
description: 版本发布文档流水线：对比本地 develop 分支与生产分支 origin/master 的改动，在钉钉设计文档大目录按业务创建设计文档（含改动内容），在提测目录按当前月份创建符合团队模版的提测文档。当用户要求"提测"、"写设计文档"、"对比改动并输出文档"、"发布文档"、"改动对比"时触发。
---

# 版本发布文档流水线（改动对比 → 设计文档 → 提测文档）

## 输入参数

启动时先确认以下输入，缺失的用 AskUserQuestion 询问（项目名称必须问用户，不要自行推断）：

| 参数 | 必填 | 说明 |
|---|---|---|
| 项目名称 | 是 | 用于提测文档标题（如 NFC+），由用户输入 |
| 仓库路径 | 是 | 默认当前工作区，需与用户确认 |
| 本地分支 | 否 | 默认 `develop` |
| 生产分支 | 否 | 默认 `origin/master` |
| 业务名称 | 是 | 设计文档主目录下的业务子目录名（如"扫码业务"），找不到匹配时列目录让用户选 |
| 版本号 | 否 | 提测文档标题用（如 V1.8.2），未提供则询问 |

## 固定目录配置

| 用途 | 钉钉目录 URL |
|---|---|
| 设计文档大目录 | https://alidocs.dingtalk.com/i/nodes/QOG9lyrgJPw5LY6Ku2p7Y2oDVzN67Mw4 |
| 提测文档目录 | https://alidocs.dingtalk.com/i/nodes/Gl6Pm2Db8DLnQXOYH9EKnP048xLq0Ee4 |

## 前置检查

1. `dws auth login`（返回已登录即可；未登录会自动走刷新或扫码流程）
2. 所有含中文回显的 PowerShell 命令，先设置：`[Console]::OutputEncoding=[Text.Encoding]::UTF8`

## Step 1：改动对比（本地分支 vs origin/master）

```powershell
git fetch origin
git log --oneline origin/master..<本地分支>          # 待发布提交清单
git diff --stat origin/master...<本地分支>           # 文件级改动统计
git show <commit>                                    # 逐个提交看具体改动（按需）
```

要求：
- 用 `origin/master..develop`（双点）取"本地分支领先生产"的提交
- 逐提交阅读 diff，归纳出：功能点清单、影响的模块/服务、数据库变更（DDL）、配置变更、Redis/资源变更
- 部署 Commit 填本地分支 HEAD 的**完整 commitId（40 位）**：`git rev-parse HEAD`，不要用 `git rev-parse --short HEAD`（提测文档「六、部署服务」的 Commit 必须可直接用于部署平台）
- Git 地址用：`git remote get-url origin`
- **对每个功能点做影响评估**，形成"影响评估清单"，供 Step 3 提测文档「三、影响范围」直接使用：
  - 触发条件：哪些设备/渠道/请求场景才会命中该改动（如"仅 Harmony 且无 CPLC 的请求"）
  - 风险等级：P1（金额/账务/展示口径类，需业务确认）；P2（新增能力/低风险）
  - 行为变化：线上行为差异点，明确不受影响的部分
  - 注意点/兜底：新增依赖查询等潜在风险、未配置时的降级行为
- **汇总"上线注意"**：DDL/数据迁移/资源变更有无（无则注明"回滚直接回退服务版本"）；跨服务/跨仓库配套改动需提示同批发布，避免口径不一致窗口

## Step 2：设计文档（钉钉大目录 → 业务子目录 → 新建）

### 2.1 定位业务子目录

`dws drive list` 返回的文件夹 `name` 是数字 dentryId，**不是真实名称**，必须逐个用 `dws doc info` 解析：

```powershell
dws drive list --folder QOG9lyrgJPw5LY6Ku2p7Y2oDVzN67Mw4 --limit 50 --format raw
# 对每个 fileId 执行，拿真实名称：
dws doc info --node <fileId> --jq "{name, nodeId, nodeType}"
```

- 有 `nextToken` 时翻页：`--cursor <nextToken>`
- 匹配用户输入的业务名称（模糊匹配）
- **无匹配时：列出全部业务子目录名称让用户选择，不要擅自新建目录**

### 2.2 生成并写入设计文档

- 内容按 [templates.md](templates.md) 的"设计文档模版"生成，其中"改动内容"章节直接使用 Step 1 的对比结果（提交清单 + 按模块的文件改动表 + 关键代码说明）
- 先写本地 UTF-8 临时文件，再创建文档：

```powershell
dws doc create --name "<业务名>-<改动主题>-设计文档" --folder <业务子目录nodeId> --content-file <临时文件>
```

- 总是新建文档（不复用同名文档）

## Step 3：提测文档（钉钉提测目录 → 当前月份文件夹 → 新建）

### 3.1 定位当前月份文件夹

```powershell
dws drive list --folder Gl6Pm2Db8DLnQXOYH9EKnP048xLq0Ee4 --limit 50 --format raw
# 逐个 dws doc info 解析真实名称，匹配 "YYYYMM提测文档"（当前年月）
```

- 当前月份文件夹不存在时：先询问用户是否新建（`dws drive mkdir` 或直接 `dws doc create --folder 提测目录` 后提示），不要擅自决定

### 3.2 生成并写入提测文档

- 严格按 [templates.md](templates.md) 的"提测文档模版"（12 个章节）生成
- 内容来源：Step 1 的对比结果 + Step 2 的设计文档链接
- 文档头部固定写提测人、提测日期与 `[创建itop工单]` 链接；「二、交付模式」默认填「标准协作」，用户明确单人交付时填「单人交付」
- 测试用例（TC-01 起）必须从改动点推导，覆盖：主链路、边界/异常、老版本兼容、配置未生效的兜底
- 数据库变更章节必须给出可执行 DDL，并明确标注执行顺序（优先执行 / 后执行）；无变更时写"无"
- 配置更改按 Apollo配置 / 配置文件 / 其他配置 归类，配置内容用代码块；数据初始化类配置归入"其他配置"并注明库表与 SQL
- 「三、影响范围」章节在影响 bullet 后追加"影响评估"小节（直接使用 Step 1 的影响评估清单）：每个功能点一行（风险等级 + 触发条件 + 行为变化 + 注意点），末尾汇总"上线注意"（DDL/回滚方式、配套发布提示）

```powershell
dws doc create --name "<项目名称><版本号>-<功能摘要>" --folder <月份文件夹nodeId> --content-file <临时文件>
```

## Step 4：字节级回读校验（必须执行）

终端 GBK 回显会把部分汉字显示成 `?`，**显示乱码不代表文档损坏**，必须字节级校验：

```powershell
[Console]::OutputEncoding=[Text.Encoding]::UTF8
dws doc read --node <新文档nodeId> --jq .markdown --format raw | Out-File -Encoding utf8 <校验文件>
# 1. 扫描字节确认无 U+FFFD（EF BF BD）
# 2. 至少3个语义不重叠的关键词（中文术语+编号+commit哈希）用 Select-String + [regex]::Escape 逐一校验
```

校验通过后删除本地临时文件，向用户汇报两份文档的 URL。

## 注意事项

- `dws doc create` 的 `--content-file` 必须是 UTF-8 编码文件
- 写入长内容一律走 `--content-file`，不要用 `--content` 字面量（转义问题）
- 若报 `can not edit the file outside the projects`：文档目录无编辑权限，让用户检查目录归属
- 临时文件统一放仓库 `script/` 目录并在校验后清理
- 提测文档中 Git 地址、分支、Commit、开发人员必须与实际部署一致；开发人员默认询问用户
- 回读校验时若发现文档内容与写入不一致（可能被用户/他人手动修改过，如部署表服务名、开发人员），**以钉钉当前内容为基准**：先 `dws doc block list` 定位插入点，再用 `dws doc update --node <id> --content-file <临时文件> --mode append --index N` 增量插入，保留已有修改，切勿整篇覆盖
- 更新已存在的钉钉文档一律用 `dws doc update`（append/overwrite 均可，overwrite 需 `--yes`）；`dws doc create` 仅用于新建文档
