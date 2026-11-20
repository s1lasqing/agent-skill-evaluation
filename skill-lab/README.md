# RSI Flow Skill 注册与执行实验

本模块在 `rsi-flow-spring-boot` 的 `11b418d3068343d0430e46a58650f97d189159d5` 上增设独立 Maven 工程。原工程通过 `FlowEngineFacade` 以服务名发起 Feign 调用，其 dev 配置指向远端 Eureka。本实验复用这种服务发现方式，在本机创建独立 Eureka 和三个应用服务。

| 服务 | 本机端口 | 职责 |
| --- | ---: | --- |
| Eureka | 18761 | 保存应用服务实例，供 Feign 客户端按名称发现 |
| Skill Registry | 18881 | 校验与保存技能定义、查询、计数、卸载 |
| Skill Worker | 18882 | 执行已实现的文本变换 |
| Skill Flow | 18883 | 通过 Feign 查询技能、调用 Worker，并逐步传递文本 |

Eureka 的三条注册记录对应三个应用服务。可注册技能数由 Skill Registry 的 `/skills/stats` 单独统计。数据集技能遵循一目录一 `SKILL.md` 的格式，保留 YAML 的 `name`、`description` 和 Markdown 正文，实验扩展字段 `operation` 与 `suffix` 用于绑定 Worker 实现。脚本生成的可选 `skill.manifest.yaml` 用作样本说明，Registry 的 HTTP 接口读取 `SKILL.md` 文本。

## 运行

需要 Java 17、Maven、启用 Linux 容器的 Docker Desktop 和 Python 3。实验模块使用 Spring Boot 3.5.15 和 Spring Cloud 2025.0.3。以下 PowerShell 命令从本成果仓库根目录运行。

```powershell
mvn -B -ntp -f skill-lab/pom.xml package
docker compose -f skill-lab/compose.yaml build eureka
docker compose -f skill-lab/compose.yaml up -d
docker compose -f skill-lab/compose.yaml ps
```

打开本机 Eureka 仪表盘 `http://127.0.0.1:18761/`，等 `SKILL-REGISTRY`、`SKILL-WORKER` 和 `SKILL-FLOW` 均为 UP，再等一个 3 秒的发现刷新周期。压测要求空注册表。若需复跑，可以先重启本实验的 Registry 容器清空其内存数据，再等待服务恢复。

有此前下载的 SkillRet 数据时，将 `--dataset` 指向该版本的 `skills/test.jsonl`。也可以直接下载固定版本的技能测试集。

```powershell
New-Item -ItemType Directory -Force -Path .\data\skillret\skills | Out-Null
$skillretUrl = 'https://huggingface.co/datasets/ThakiCloud/SKILLRET/resolve/6583d7d2ed07644d0fb8938ed8178f3a7dc42a12/data/skills/test.jsonl?download=true'
Invoke-WebRequest -Uri $skillretUrl -OutFile .\data\skillret\skills\test.jsonl
python skill-lab/bench.py --dataset .\data\skillret\skills\test.jsonl --output .\data\spring-skill-lab-run
```

脚本按 SkillRet 样本 UID 读取 `text-cleanup`，生成 49 个带唯一名称和输出标记的合成技能，注册后验证逐步输出。随后以 8 个并发客户端持续调用两技能流程，至少运行 60 秒，并循环热加载、执行、卸载同一探针技能 60 次。最后注册容量样本，检查越界请求和满载调用。原始结果写入输出目录中的 `results.json`。

[已完成的实验报告](../docs/spring-skill-lab-report.md) · [已完成的实验指标](../results/spring-skill-lab.json)

## 接口与生命周期

| 请求 | 含义 |
| --- | --- |
| `POST /skills/batch` | 在 18881 上发送包含 1–1,000 个 Markdown 字符串的 JSON 数组。整批校验，重复名称或超出容量返回 409 |
| `GET /skills/stats` | 在 18881 上查看已注册数量、配置上限和 Registry 启动时生成的 UUID |
| `GET /skills/{name}` | 在 18881 上获取已登记定义 |
| `DELETE /skills/{name}` | 在 18881 上卸载，成功返回 204 |
| `POST /flow` | 在 18883 上发送 `{"skills":["text-cleanup","marker-01"],"input":"Certainly! Hello"}`，期望 `output` 为 `Hello\|marker-01\|` |

加载、卸载提交后，下一次查找直接读取新状态。已经获取技能定义的在途请求可能继续完成。Registry 使用单实例内存存储，重启会清空。Worker 目前运行清理或追加标记两种 Java 操作，动态加载针对技能定义。原工程的流程引擎、持久化、资源脚本执行和高可用属于后续集成范围。

```powershell
docker compose -f skill-lab/compose.yaml down
```
