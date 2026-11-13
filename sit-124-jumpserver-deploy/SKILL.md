---
name: sit-124-jumpserver-deploy
description: 通过 JumpServer 堡垒机部署 SIT 测试环境的自有业务服务（地铁业务不在这套环境）。当用户要求部署自有业务服务、重启服务、查看服务状态、新增服务配置、修改部署工具时使用；地铁业务服务部署走 sit-metro-jumpserver-deploy，两者跳板机与目标机不同，不可混用。支持交互式和非交互式部署。
version: 1.0.0
---

# JumpServer 部署工具使用指南

> **适用范围**：SIT 测试环境的**自有业务**服务部署。链路是本地 → `8.139.6.141:2222` 跳板机 → 目标机 `sityun124`。地铁业务服务（南京地铁乘车码全链路那些）不在这套环境，走 `sit-metro-jumpserver-deploy`（跳板机 `jump.unservice.net:2222`）。两个技能的触发词很像，选错就是往另一套环境发版。

## 工具位置

```
skills/sit-124-jumpserver-deploy/
├── SKILL.md
├── deploy_jumpserver.py   # 主程序
├── deploy.sh              # 启动脚本
├── deploy_config.json     # 跳板机凭据(jump) + 服务注册表，含明文口令，不入库
└── deploy_config.example.json  # 脱敏模板（jump.password 为占位符），可提交
```

> 首次使用：`cp deploy_config.example.json deploy_config.json`，填入 `jump.password`（口令已不再硬编码在脚本里，缺失时工具会直接报错提示）。

> 路径相对技能根目录，工具随技能一起分发：仓库侧技能目录直接挂在仓库根下（`<仓库根>/sit-124-jumpserver-deploy/`，没有 `skills/` 中间层），已安装副本在 `~/.qoder/skills/sit-124-jumpserver-deploy/`，两边内容一致，用仓库根的 `sync_skill.sh` 同步。下面所有命令都在本技能目录下执行。

## 运行方式

```bash
# 交互式部署（选服务 → 选操作）
./deploy.sh

# 列出已注册服务（不连接跳板机）
./deploy.sh -l

# 部署指定服务（显示操作菜单）
./deploy.sh -s equities-core

# 直接执行操作
./deploy.sh -s equities-core -a deploy      # 打包部署
./deploy.sh -s equities-core -a restart     # 重启
./deploy.sh -s equities-core -a verify      # 验证状态
./deploy.sh -s equities-core -a stop        # 停止
./deploy.sh -s equities-core -a start       # 启动
./deploy.sh -s equities-core -a issue       # 发布

# 切换分支后部署
./deploy.sh -s equities-core -b develop -a deploy
```

## 可用操作

deploy / issue / start / stop / restart / verify

默认操作是 deploy。

## 部署完成输出（必须给这张表）

部署收尾时按下列五列逐行汇报每台运行机，缺一列就去取证，不要凭印象填：

| 运行机 | IP | 端口 | pid | 时间 |
| --- | --- | --- | --- | --- |
| sityun151 | 10.0.89.151 | 9005 | 2954091 | 2026-11-11 15:58 |

各列都在 `./deploy.sh -s <服务> -a verify` 的输出里，一次拿全：

- **运行机 / IP**：每台一个 `====<运行机>(<IP>) ...` 块头（前面还有一行裸 `<运行机>`），IP 直接读块头，不需要额外探测。
- **端口 / pid**：块内 `tcp6 0 0 :::9005 :::* LISTEN 2954091/java` 这一行，`:::` 是 IPv6 通配，端口取 `9005`、pid 取 `LISTEN` 后面那个数；再用 `<jar>.run: <pid>` 行与 `ps` 行的首列互相印证。
- **时间**：块内 `....jar (2026-11-11 15:58)` 括号里的时间，即 jar 落盘时间；不是 `ps` 行的进程启动时间（`Wed Nov 11 15:58:09 2026`）。
- **目标机自身不出块**：verify 只遍历远端 issue 机（sityun151 / sityun206），sityun124 本机没有验证块。它那一行从 deploy/issue 输出的本机块取，IP 用连接时打印的 `选中: sityun124 (10.0.89.124)`；取不到就写 `—` 并注明未覆盖，不要拿远端机器的数值顶替。
- 没有 LISTEN 行（服务未启动或被权限过滤看不到）时端口/pid 写 `—` 并在表下说明；控制台是 GBK，中文串 grep 匹配不到，取 IP 用 ASCII 正则，例如 `grep -aoE "====sityun[0-9]+\(([0-9]{1,3}\.){3}[0-9]{1,3}\)"`。

## 新增服务

编辑 `deploy_config.json`，在 `services` 下添加：

```json
"服务名": {
  "script_name": "脚本相对路径",
  "script_path": "/opt/xxx",
  "code_path": "/opt/xxx/code/仓库名",
  "branch": "develop",
  "label": "中文名"
}
```

字段说明：
- `script_name`: 部署脚本相对于 script_path 的路径（如 `equities-bm/equities-bm`）
- `script_path`: 执行部署命令时 cd 到的目录
- `code_path`: git 仓库路径（用于分支管理和 mvn 构建）
- `branch`: 默认分支，不填默认 `develop`
- `label`: 中文服务名，用于显示

## 当前已注册服务

- equities-core (权益中心) [develop] — 同步到 sityun124 + sityun151，端口 9005
- citytsm-pm (项目管理) [stable] — 同步到 sityun124 + sityun206，端口 9210
- citytsm-sys-equities (权益中心后管) [develop]
- citytsm-sys-advert (广告后管) [stable]
- citytsm-module-system (云枢系统管理) [stable]
- citytsm-tcapp-gateway (小程序网关) [stable]

## 技术架构

```
本地 → paramiko SSH → JumpServer(8.139.6.141:2222) → 交互菜单 → 目标服务器(sityun124)
```

关键实现：
- JumpServer 是开源堡垒机，登录后显示交互菜单（非普通 shell）
- 使用 `get_pty + invoke_shell` 获取伪终端
- 资产搜索：发送 `/IP` 或 `/主机名`，解析管道分隔表格（`1 | 名称 | IP`）
- 账号选择：匹配 `target_user`(tsm)，发送编号，提示符为 `ID>`
- 命令执行：通过 sentinel 标记检测命令完成
- 服务配置从 `deploy_config.json` 加载，`save_config` 会保留 services 节点

## 常见问题

- **"搜索完成 (原因: idle)"**: 正常现象，JumpServer 返回结果后 10 秒无新数据自动结束，不影响功能
- **JSON 解析失败**: 检查 deploy_config.json 是否有尾部逗号（Python json 不容忍），save_config 已改为合并写入保留 services 节点
- **`-l` 无数据**: 检查 deploy_config.json 格式是否正确
- **修改代码后测试**: 用 `./deploy.sh -l` 验证配置加载，用 `./deploy.sh -s 服务名 -a verify` 测试连接

## 安全约束（必须遵守）

本工具只做**服务部署相关操作**，不对服务器做任何修改、删除类高危动作。

- 允许的动作只有这六个：`deploy` / `issue` / `start` / `stop` / `restart` / `verify`（即 `./deploy.sh -s <服务> -a <动作>`），以及工具内置的配套 git 分支切换（fetch/checkout/pull）与 mvn 构建；不要用 `bash -c` 拼别的命令。
- 允许在目标机执行的其它命令仅限**只读排查**：`ls`、`cat`、`head`、`tail`、`ps`、`ss`、`netstat`、`grep`、`git status/log/remote -v/rev-parse --abbrev-ref HEAD`、`test -d`。
- 禁止执行（即使用户没提到也不行，需要先取得用户明确同意并说明影响）：
  - 文件与权限：`rm`、`mv`、`cp` 覆盖、`touch`/`>` 写配置、`chmod`、`chown`、`mkdir`、建软链、改 `/etc` 下任何文件
  - 进程与服务：`kill`、`pkill`、`systemctl`、`service`、重启机器或数据库实例
  - 包与环境：`yum`/`apt`、安装或卸载 JDK/Maven/Node、改 `~/.bashrc`、改 crontab
  - Git 破坏性操作：`reset --hard`、`clean`、`checkout -- <file>`、`push`、删分支、`rebase`
  - 数据库：DDL、`UPDATE`/`DELETE`、导入导出、直接改配置中心里的值
- 不在目标机留下任何临时文件、备份或日志；本地临时探测脚本（`_probe.py` 之类）用完即删。
- 动作有破坏性后果的（`deploy`/`issue`/`restart`/`stop` 会影响 SIT 运行中的服务）只在用户明确要求时执行，绝不作为"顺手验证"或"清理"的一部分；`verify` 是只读的状态检查，可放心使用。
- 范围限制：命令只作用于 `deploy_config.json` 中已注册服务对应的 `script_path` / `code_path` 目录，不得越界操作其他目录或服务。

## 已知 Bug 修复

- **哨兵提前匹配 (已修复)**: `exec_on_target` 中 `echo 'sentinel'` 的命令回显包含完整哨兵字符串，导致在命令实际输出到达前就匹配结束。修复方法：将哨兵拆分为 `echo 'part1''part2'`，回显不含完整串但 echo 输出完整。
