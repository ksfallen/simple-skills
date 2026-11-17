---
name: sit-metro-jumpserver-deploy
description: 通过 JumpServer 堡垒机部署 SIT 测试环境的地铁业务服务（metro）。当用户要求部署地铁服务、发布 metro 相关服务、重启地铁服务、查看地铁服务状态、新增地铁服务配置时使用；自有业务的 SIT 服务部署走 sit-124-jumpserver-deploy，两者跳板机与目标机不同，不可混用。支持交互式和非交互式部署。
version: 1.0.0
---

# 地铁服务 JumpServer 部署工具

> **适用范围**：SIT 测试环境的**地铁业务**服务部署。链路是本地 → `jump.unservice.net:2222` 跳板机 → `test-nanjing-tools001` 等目标机。自有业务的服务部署走 `sit-124-jumpserver-deploy`（跳板机 `8.139.6.141:2222` → 目标机 `sityun124`），跳板机和目标机都不一样，别拿本技能发。

## 操作边界（必须遵守）

本工具只做**服务部署相关操作**，不对服务器做任何修改、删除类高危动作。

- 允许的命令只有这六个子命令：`deploy` / `issue` / `start` / `stop` / `restart` / `verify`（即 `./<脚本> [rcmd] <动作>`），不要用 `bash -c` 拼别的东西。
- 允许在目标机执行的其它命令仅限**只读排查**：`ls`、`cat`、`head`、`tail`、`ps`、`ss`、`netstat`、`grep`、`git status/log/remote -v/rev-parse --abbrev-ref HEAD`、`test -d/-f/-e`。这些走 `./deploy.sh --readonly "<单条命令>"`（不执行任何部署动作）：只接受白名单开头的一条命令，含 `;` `&` `|` `$` `` ` `` `>` `<` 换行的直接拒，`git` 也只认上面那几个只读子命令。
- 禁止执行（即使用户没提到也不行，需要先取得用户明确同意并说明影响）：
  - 文件与权限：`rm`、`mv`、`cp` 覆盖、`touch`/`>` 写配置、`chmod`、`chown`、`mkdir`、建软链、改 `/etc` 下任何文件
  - 进程与服务：`kill`、`pkill`、`systemctl`、`service`、重启机器或数据库实例
  - 包与环境：`yum`/`apt`、安装或卸载 JDK/Maven/Node、改 `~/.bashrc`、改 crontab
  - Git 破坏性操作：`reset --hard`、`clean`、`checkout -- <file>`、`push`、删分支、`rebase`
  - 数据库：DDL、`UPDATE`/`DELETE`、导入导出、直接改配置中心里的值
- 不在目标机留下任何临时文件、备份或日志；本地临时探测脚本（`_probe.py` 之类）用完即删。
- 动作有破坏性后果的（`deploy`/`issue`/`restart`/`stop` 会影响 SIT 运行中的服务）只在用户明确要求时执行，绝不作为"顺手验证"或"清理"的一部分；`verify` 和 `--readonly` 是只读的，可放心使用。

## 工具位置

```
skills/sit-metro-jumpserver-deploy/
├── SKILL.md
├── deploy_jumpserver.py   # 主程序
├── deploy.sh              # 启动脚本
├── deploy_config.json     # 跳板机凭据(jump) + 服务注册表，含明文口令，不入库
└── deploy_config.example.json  # 脱敏模板（jump.password 为占位符），可提交
```

> 首次使用：`cp deploy_config.example.json deploy_config.json`，填入 `jump.password`（口令已不再硬编码在脚本里，缺失时工具会直接报错提示）。

> 路径相对技能根目录，工具随技能一起分发：仓库侧技能目录直接挂在仓库根下（`<仓库根>/sit-metro-jumpserver-deploy/`，没有 `skills/` 中间层），已安装副本在 `~/.qoder/skills/sit-metro-jumpserver-deploy/`（与仓库目录同名），两边内容一致，用仓库根的 `sync_skill.sh` 同步。下面所有命令都在本技能目录下执行。

## 运行方式

```bash
./deploy.sh                                  # 交互式部署（选服务 → 选操作）
./deploy.sh -l                               # 列出已注册服务（不连接跳板机）
./deploy.sh -s metro-retro                   # 部署指定服务（显示操作菜单）
./deploy.sh -s metro-retro -a deploy         # 打包部署
./deploy.sh -s metro-retro -a issue          # 发布到运行机
./deploy.sh -s metro-retro -a restart        # 重启
./deploy.sh -s metro-retro -a stop           # 停止
./deploy.sh -s metro-retro -a start          # 启动
./deploy.sh -s metro-retro -a verify         # 验证状态
./deploy.sh -s metro-retro -b develop -a deploy  # 切分支后部署

# 南京地铁服务（服务配置里已写 target_host，自动切机）
./deploy.sh -s nanjing-metro-retro -a verify
./deploy.sh -s nanjing-metro-pay -a deploy

# 各城市前置 / 生码服务（默认机 test-tools001，命名规则 <城市拼音>-metro-pre / -metro-getcode）
./deploy.sh -s changchun-metro-pre -a verify
./deploy.sh -s fuzhou-metro-getcode -a deploy

# 南通服务（同样在 test-tools001，路径前缀 /opt/nantong，不带 target_host）
./deploy.sh -s nantong-metro-integration -a verify
./deploy.sh -s nantong-metro-pay -a deploy

# 只读排查目标机（不执行任何部署动作，命令须是白名单单条）
./deploy.sh --readonly "ls -1 /opt/receipt/metro-receipt"
./deploy.sh --readonly "cat /opt/receipt/metro-receipt/metro-receipt"
./deploy.sh -s nanjing-metro-retro --readonly "ls -1 /opt/receipt/metro-retro"
```

可用操作：deploy / issue / start / stop / restart / verify，默认 deploy。

## 目标机与登录账号

默认（脚本常量）：

```python
TARGET_HOST = "test-tools001"    # 八城 metro 构建/分发机
TARGET_USER = "tsm-local"        # JumpServer 账号名，实际系统用户 tsm
```

南京地铁的服务在 `deploy_config.json` 里单独指定：

```json
"nanjing-metro-retro": { ..., "target_host": "test-nanjing-tools001" }
```

优先级：**服务配置 > 命令行 `-H`/`-u` > 全局默认**。

注意：只有带 `-s` 时才会按服务解析目标机。不带 `-s` 的交互式流程总是连默认机（`-H` 可覆盖），列出的也是那台机 `/opt` 下的服务目录——要交互部署南京的服务请加 `-H test-nanjing-tools001`。

## 部署模型（重要）

目标机上 `<script_path>/<脚本名>` 内部区分三类主机：

- `deploy_host`（test-tools001 / test-nanjing-tools001）：只负责构建和分发，服务不在上面跑，列在 `no_start_hosts`
- `issue_hosts`（如 test-receipt001）：真正跑服务的机器，`issue` 会把 jar + 配置同步过去
- 因此 `deploy` 在 tools 机执行，`restart/verify` 等 rcmd 会由脚本自行转发到 issue 机

发布脚本对所有服务都是同一套动作，按动作理解、不要按服务找特例：

- `-a deploy`：切分支 + mvn 打包 + 把新 jar 和配置发布到 `issue_hosts` + 重启，一条就生效，不用再补 `issue`。
- `-a issue`：不重新构建，直接把 tools 机上现有的包发布到 `issue_hosts` + 重启（换了别处构建的包、或只改配置时用）。
- `-a start` / `stop` / `restart` / `verify`：走 `rcmd`，由脚本转发到 `issue_hosts` 逐台执行。
- 发布是否真的落到某台运行机，只看 verify 里那台的 jar 时间戳；时间还停在旧日期就是没发出去，别当成"这台不用发"。

## 部署完成输出（必须给这张表）

部署收尾时按下列五列逐行汇报每台运行机，缺一列就去取证，不要凭印象填：

| 运行机 | IP | 端口 | pid | 时间 |
| --- | --- | --- | --- | --- |
| test-receipt001 | 192.168.24.166 | 8081 | 2976 | 2026-11-17 10:16 |

各列来源：

- **运行机 / 端口 / pid / 时间**：全部取自 `./deploy.sh -s <服务> -a verify` 的 rcmd 输出。端口与 pid 来自 `tcp 0.0.0.0:<端口> ... LISTEN <pid>/java`；时间取 `<jar名>: YYYY-MM-DD HH:MM` 这一行，即 jar 落盘时间，不是进程启动时间。
- **IP**：`./deploy.sh -l -s <服务> -H <运行机>` 只读探测（`-l` 只列注册服务，不会执行任何部署动作），从 JumpServer 资产表拿。同一会话里每台运行机只探一次，复用结果。
- 没有 LISTEN 行（服务未启动或被权限过滤看不到）时，端口/pid 写 `—`，并在表下说明现象；`-H` 探测不到资产就写 IP `—`，不要拿邻近机器补。
- 控制台是 GBK，中文串 grep 匹配不到；取 IP 用 ASCII 正则，例如 `grep -aoE "<运行机>.*192\.168\.[0-9]+\.[0-9]+"`。

## 新增服务

编辑 `deploy_config.json`，在 `services` 下添加：

```json
"服务名": {
  "script_name": "脚本相对路径",
  "script_path": "/opt/receipt/<服务目录>",
  "code_path": "/opt/receipt/<服务目录>/code/<仓库名>",
  "branch": "stable",
  "label": "中文名",
  "target_host": "test-nanjing-tools001"
}
```

字段说明：
- `script_name`: 部署脚本相对 `script_path` 的路径
- `script_path`: 执行部署命令时 cd 到的目录
- `code_path`: git 仓库路径（用于分支管理和 mvn 构建）
- `branch`: 默认分支，不填为 `stable`
- `label`: 中文服务名，用于显示
- `target_host` / `target_user`: 可选，非默认机（如南京环境）时才写

确定字段的约定：
- `script_name` = `script_path` 目录内那个可执行部署脚本的文件名（各服务不同：`ebuscard`、`integration`、`pay`、`metro-benefit`、`settlement`、`najing`、`spi-getcode`……），先 `ls` 目录确认，不要想当然按服务名填
- `code_path` 默认取 `script_path/code/<仓库>`；若 `code` 下有多个目录，用 `git remote -v` 判断——远端为 `git@codeup.aliyun.com` 的才是正确代码目录（`gitlab.allcitygo.com` 是老仓库，`*bak`、`-all`、`-allcitygo`、尾部数字是备份或老副本，都要排除）；目录里没有 `code/` 时先找 `/opt/CODE/<仓库>`（如东莞）
- `branch` 默认取该仓库当前检出的分支（`git rev-parse --abbrev-ref HEAD`），八城机的 metro-pay / metro-settlement 在 `dev`，其余在 `stable`；南京机各仓库要单独核对，两台机器可能不一致
- 部署脚本需支持 `rcmd`（`grep -c rcmd <脚本>` ≥1），否则 `restart/verify` 无法转发到 issue 机

注意：JSON 不允许尾随逗号，改完先用 `./deploy.sh -l` 验证。

metro 服务目录分布：`/opt/little`（ech5）、`/opt/manage`（卡管）、`/opt/receipt`（收单、支付、权益、对账、补登；八城机另有 chengdu/chongqing/wuhan）、`/opt/front/<城市>`（各城市前置，含 `najing`）、`/opt/spi-getcode/<城市>`（各城市生码）。南通是独立前缀 `/opt/nantong/<同样的 front|little|manage|receipt|spi-getcode>`（在 test-tools001 上）。

南京机上同名服务的仓库挂在 `codeup.aliyun.com:.../nanjing_ext_metro/` 组下（八城是 `ext_metro/`），所以同一 `script_path` 在两台机器上的 `code_path` 目录名相同但仓库不同——必须靠 `target_host` 区分，不能混用。

## 当前已注册服务

八城（默认在 test-tools001 构建）：

| 服务 | 名称 | script_path / 脚本 | code_path [分支] | 运行机:端口 |
| --- | --- | --- | --- | --- |
| metro-retro | 补登 | /opt/receipt/metro-retro | metro-retro [stable] | test-receipt001:8083 |
| metro-ech5 | ech5 | /opt/little/ech5 · `ebuscard` | metro-ech5 [stable] | test-little001:8080 |
| metro-integration | 卡管 | /opt/manage/integration · `integration` | metro-ecard-manage [stable] | test-manage001:8087 |
| metro-receipt | 收单 | /opt/receipt/metro-receipt | metro-receipt [stable] | test-receipt001:8081 |
| metro-pay | 支付 | /opt/receipt/metro-pay/ace-pay · `pay` | /opt/receipt/metro-pay/code/metro-pay [dev] | test-receipt001:7004 |
| metro-benefit | 权益 | /opt/receipt/metro-pay/metro-benefit-core · `metro-benefit` | /opt/receipt/metro-pay/code/metro-pay [dev] | test-front001:7009 |
| metro-settlement | 对账 | /opt/receipt/metro-settlement · `settlement` | metro-settlement [dev] | test-receipt001:6002 |

南京（每条都带 `"target_host": "test-nanjing-tools001"`）：

| 服务 | 名称 | script_path / 脚本 | code_path [分支] | 运行机:端口 |
| --- | --- | --- | --- | --- |
| nanjing-metro-retro | 南京补登 | /opt/receipt/metro-retro | metro-retro [stable] | test-nanjing-receipt001:8082 |
| nanjing-metro-ech5 | 南京-ech5 | /opt/little/ech5 · `ebuscard` | metro-ech5 [stable] | test-nanjing-little001:8080 |
| nanjing-metro-integration | 南京-卡管 | /opt/manage/integration · `integration` | metro-ecard-manage [stable] | test-nanjing-manage001:8087 |
| nanjing-metro-receipt | 南京-收单 | /opt/receipt/metro-receipt | metro-receipt [stable] | test-nanjing-receipt001:8081 |
| nanjing-metro-pay | 南京-支付 | /opt/receipt/metro-pay/ace-pay · `pay` | /opt/receipt/metro-pay/code/metro-pay [dev] | test-nanjing-receipt001:7004 |
| nanjing-metro-settlement | 南京-对账 | /opt/receipt/metro-settlement · `settlement` | metro-settlement [stable] | test-nanjing-receipt001:6010 |
| nanjing-metro-pre | 南京-前置 | /opt/front/najing · `najing` | metro-pre [stable] | test-nanjing-front001:8086 |
| nanjing-metro-apply-cert | 南京生码 | /opt/spi-getcode/najing · `spi-getcode` | metro-apply-cert [stable] | test-nanjing-spi001:8085 |

南京机没有 metro-benefit（权益）目录，八城 `metro-pay` 仓库在南京的默认分支是 `dev`、对账是 `stable`，与八城机不同，改分支前先 `git rev-parse --abbrev-ref HEAD` 核对。最后一列由部署脚本的 `issue_hosts` 决定。

### 南通（`/opt/nantong/<模块>`，在 test-tools001 构建）

每条都**不带** `target_host`（南通环境就在 test-tools001 上，路径前缀是 `/opt/nantong`）。目录结构与其它机器不同：`front`（前置）、`little/ech5`、`manage/integration`、`receipt/{metro-receipt, metro-pay, metro-retro, metro-settlement}`、`spi-getcode`。

| 服务 | 名称 | script_path / 脚本 | code_path [分支] | 运行机:端口 |
| --- | --- | --- | --- | --- |
| nantong-metro-retro | 南通补登 | /opt/nantong/receipt/metro-retro · `metro-retro` | metro-retro [develop] | test-manage001 — 进程在跑（pid 4699）但 verify 无监听端口 |
| nantong-metro-ech5 | 南通-ech5 | /opt/nantong/little/ech5 · `ebuscard` | metro-ech5 [stable] | test-manage001:9880 |
| nantong-metro-integration | 南通-卡管 | /opt/nantong/manage/integration · `integration` | /opt/nantong/manage/integration/code/nantong-metro-manage [stable] | test-manage001:9887 |
| nantong-metro-receipt | 南通-收单 | /opt/nantong/receipt/metro-receipt · `metro-receipt` | metro-receipt [develop] | test02:9881 |
| nantong-metro-pay | 南通-支付 | /opt/nantong/receipt/metro-pay/ace-pay · `pay` | /opt/nantong/receipt/metro-pay/code/metro-pay [dev] | test02:9804 |
| nantong-metro-settlement | 南通-对账 | /opt/nantong/receipt/metro-settlement · `settlement` | metro-settlement [develop] | test-manage001:9810 |
| nantong-metro-pre | 南通-前置 | /opt/nantong/front · `nantong` | code/nantong-metro-pre [develop] | test01:9886 |
| nantong-metro-getcode | 南通生码 | /opt/nantong/spi-getcode · `spi-getcode` | code/nantong-metro-getcode [develop] | test01:9885 |

南通端口规律是 `98xx`（前置 9886、生码 9885、ech5 9880、收单 9881、卡管 9887、支付 9804、对账 9810），运行机只有 test01 / test02 / test-manage001 三台，同一台上跑多个南通服务，restart/stop 前先确认 `issue_hosts`。

`nantong-metro-integration` 的 `deploy` 实测已包含 mvn 构建 → 同步 jar/配置到 test-manage001 → KILL 旧进程 → 启动，所以 **deploy 之后不需要再单独 issue**。注意部署脚本里注释掉的 `code_dir=.../code/metro-ecard-manage` 是八城路径，南通生效的是 `nantong-metro-manage`，不要照抄。

南通下未纳入配置：`receipt/citytsm-receipt`、`little/invoice`、`metro-pay/ace-bm-api`、`metro-pay/ace-merchant`。

### 各城市前置（`/opt/front/<城市>`，在 test-tools001 构建）

端口规律：前置尾号 86、生码尾号 85，按城市递增分配（8086/8085 → 10486/10485）；运行机取自各部署脚本的 `issue_hosts`。

| 服务 | 名称 | 脚本 | code_path [分支] | 运行机:端口 |
| --- | --- | --- | --- | --- |
| changchun-metro-pre | 长春前置 | `changchun` | changchun-pre [stable] | test-changchun-front001:8086 |
| chengdu-metro-pre | 成都前置 | `chengdu` | chengdu-metro-pre [stable] | test01:8186 |
| chongqing-metro-pre | 重庆前置 | `chongqing` | chongqing-metro-pre [stable] | test10:8986 |
| dongguan-metro-pre | 东莞前置 | `dongguan-pre` | /opt/CODE/dongguan-metro [stable] | test03:10486 |
| foshan-metro-pre | 佛山前置 | `foshan-pre` | foshan-pre [stable] | test07:8686 |
| fuzhou-metro-pre | 福州前置 | `fuzhou` | fuzhou-pre [develop] | test04:8386 |
| hefei-metro-pre | 合肥前置 | `hefei-pre` | hefei-pre [develop] | test06:8586 |
| huhehaote-metro-pre | 呼和浩特前置 | `huhehaote-pre` | huhehaote-pre [stable] | test13:9386 |
| jinan-metro-pre | 济南前置 | `jinan-pre` | jinan-pre [stable] | test13:9186 |
| jinhua-metro-pre | 金华前置 | `jinhua-pre` | jinhua-pre [dev] | test08 + test07:8786 |
| kunming-metro-pre | 昆明前置 | `kunming` | metro-pre [stable] | test-front001:8086 |
| luoyang-metro-pre | 洛阳前置 | `luoyang-pre` | luoyang-pre [stable] | test12:9286 |
| nanping-metro-pre | 南平前置 | `nanping-pre` | nanping-pre [master] | test09:8886 |
| qingdao-metro-pre | 青岛前置 | `pre-qindao` | qingdao-metro-pre [stable] | test13 |
| shuke-metro-pre | 数科前置 | `pre-shuke` | shuke-metro-pre [master] | test13:10286 |
| taizhou-metro-pre | 台州前置 | `taizhou-pre` | taizhou-pre [dev] | test12:9086 |
| wuxi-metro-pre | 无锡前置 | `wuxi` | wuxi-pre [stable] | test03 — verify 无监听端口，当前未启动（另有 `wuxibak` 脚本，不要用） |

### 各城市生码（`/opt/spi-getcode/<城市>`，在 test-tools001 构建）

| 服务 | 名称 | 脚本 | code_path [分支] | 运行机:端口 |
| --- | --- | --- | --- | --- |
| changchun-metro-getcode | 长春生码 | `ccgetcode` | changchun-getcode [stable] | test-changchun-spi001:8085 |
| chengdu-metro-getcode | 成都生码 | `cd-getcode` | chengdu-metro-apply-cert [stable] | test01:8185 |
| chongqing-metro-getcode | 重庆生码 | `cq-getcode` | chongqing-getcode [dev] | test10:8985 |
| dongguan-metro-getcode | 东莞生码 | `dongguan-getcode` | /opt/CODE/dongguan-metro [stable] | test07:10485 |
| foshan-metro-getcode | 佛山生码 | `foshan-getcode` | foshan-getcode [stable] | test07:8685 |
| fuzhou-metro-getcode | 福州生码 | `fzspi` | fuzhou-getcode [master] | test04:8385 |
| hefei-metro-getcode | 合肥生码 | `hefei-getcode` | hefei-getcode [stable] | test06:8585 |
| huhehaote-metro-getcode | 呼和浩特生码 | `huhehaote-getcode` | huhehaote-getcode [stable] | test13:9385 |
| jinan-metro-getcode | 济南生码 | `jinan-getcode` | jinan-getcode [stable] | test13:9185 |
| jinhua-metro-getcode | 金华生码 | `jinhua-getcode` | jinhua-getcode [master] | test08:8785 |
| kunming-metro-getcode | 昆明生码 | `kmgetcodespi` | metro-apply-cert [stable] | test-spi001:8085 |
| luoyang-metro-getcode | 洛阳生码 | `luoyang-getcode` | luoyang-getcode [master] | test12:9285 |
| nanping-metro-getcode | 南平生码 | `nanping-getcode` | nanping-getcode [master] | test09:8885 |
| qingdao-metro-getcode | 青岛生码 | `qingdao-metro-getcode` | qingdao-metro-getcode [stable] | test13 |
| shuke-metro-getcode | 数科生码 | `shuke-metro-getcode` | shuke-metro-getcode [master] | test13:10285 |
| taizhou-metro-getcode | 台州生码 | `taizhou-getcode` | taizhou-getcode [master] | test12:9085 |
| wuxi-metro-getcode | 无锡生码 | `wxspi` | wuxi-getcode [stable] | test03:8285 |

城市服务的选择要点：

- 脚本名各城市不统一（`changchun`、`dongguan-pre`、`fzspi`、`kmgetcodespi`、`wxspi`、`pre-qindao`、`ccgetcode`……），必须 `ls` 目录确认可执行文件，不能按城市名猜。
- `code/` 下带 `-allcitygo`、`-all`、`-bak`、`2` 后缀的是老仓库或备份，只取 `codeup.aliyun.com` 的正主；`chengdu`/`chongqing` 的仓库在 `chengdu_ext_metro`、`chongqing_ext_metro` 组下。
- 东莞例外：服务目录下没有 `code/`，代码在独立的多模块仓库 `/opt/CODE/dongguan-metro`（模块 `dongguan-pre`、`dongguan-getcode`），前置和生码两条配置共用这一个 `code_path`，分支 `stable`。
- 一台运行机常跑多个城市（如 test13 上有呼和浩特、济南、数科、青岛），restart/stop 会连带影响同机服务，操作前先确认 `issue_hosts`。
- 未纳入配置的目录：`/opt/front/metro-apply-cert-ticket`（票根服务，脚本 `ticket`，仓库 metro-apply-cert-ticket [master]）和空的 `/opt/spi-getcode/wuhan`。

## 技术架构

```
本地 → paramiko SSH → JumpServer(jump.unservice.net:2222) → 交互菜单 → test-tools001(192.168.24.161)
                                                      └→ 南京：test-nanjing-tools001(192.168.24.176)
```

与 sit-124-jumpserver-deploy 的关键差异（已在本副本中修复）：
- **主机密钥**：这台 JumpServer 只提供 `ssh-rsa`(SHA-1)，paramiko>=4 已移除该算法。脚本顶部 `_enable_legacy_host_keys()` 会补回 `_preferred_keys` / `_key_info` / `RSAKey.HASHES`。
- **行尾符**：CoIN 交互菜单只识别 `\r`，发 `\n` 时输入仅回显、不执行。`_sendline` 统一使用 `\r`。

其余实现与 sit-124-jumpserver-deploy 一致：`get_pty + invoke_shell` 取伪终端，`/主机名` 搜索资产并解析管道分隔表格，在 `ID>` 提示符下按 `target_user`（账号名 `tsm-local`，对应系统用户 `tsm`）选择账号并发送编号，命令完成通过拆分哨兵字符串（`echo 'p1''p2'`）检测。

## 常见问题

- **"Incompatible ssh peer (no acceptable host key)"**: paramiko 版本过新，确认 `_enable_legacy_host_keys()` 未被删除
- **"无法从 JumpServer 输出中解析资产列表"**: 多为行尾符问题或资产名拼错，用 `p\r` 列出全部资产核对
- **"搜索完成 (原因: idle)"**: 正常现象，JumpServer 返回后无新数据自动结束
- **"-l 无数据 / JSON 解析失败"**: 检查 deploy_config.json 尾随逗号或缺少闭合括号
- **测试改动**: 先用 `./deploy.sh -l` 验证配置加载，再用 `./deploy.sh -s metro-retro -a verify` 验证链路
