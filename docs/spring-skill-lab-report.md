# Spring Skill 注册与运行实验

实验日期 2026-11-20。原仓库提交 `11b418d3068343d0430e46a58650f97d189159d5`。[rsi-flow-spring-boot](https://github.com/ymxiong/rsi-flow-spring-boot)

## 原工程与接入方式

- 原项目的 `core-starter` 启用 Feign 和服务发现，`core-flow-domain` 中的 `FlowEngineFacade` 通过服务名调用流程服务。原项目默认开发配置需要远端 Eureka 和数据库，构建还引用了公共 Maven Central 无法解析的依赖，例如 `com.horsecoder:auth:0.1.15` 和 `cc.eamon.open:flow-spring-boot-starter:0.4.14`。
- 独立的 `skill-lab` Maven 工程从原仓库实验目录整理至本成果仓库，使用 Spring Boot 3.5.15、Spring Cloud 2025.0.3、Java 17。Docker Desktop 的 Linux 引擎 29.8.1 运行四个容器。每个容器设置 768 MiB 内存限制，每个 Java 进程最大堆 256 MiB。应用仅将端口发布到宿主机回环地址。
- Eureka 为 Registry、Worker、Flow 提供服务发现。请求到达 Flow 后，每一步由 Feign 按服务名请求 Registry 查找定义，再按服务名调用 Worker。上一步的输出是下一步的输入。每个技能条目独立保存在 Registry 中。[基线代码与复跑命令](../skill-lab/README.md)

## Skill 样本

从 SkillRet 测试集取出 `text-cleanup`，样本 UID 为 `76d3bc58-1295-44b4-ac92-30295cac13c3`，数据集标注许可证为 MIT。保留样本指令正文，按已有规范提供 `SKILL.md` 的 `name`、`description` 和 Markdown 正文。实验通过 Java 实现移除开头的部分客套语和空白归一化。例如输入 `Certainly!   Prepare the table.`，预期输出 `Prepare the table.`。已有 Python Skill Registry 通过目录扫描成功识别该样本及 49 个合成样本。[SkillRet 论文](https://arxiv.org/abs/2605.05726) · [原技能来源](https://github.com/majiayu000/claude-skill-registry/tree/main/skills/data/text-cleanup)

50 步调用链依次执行 `text-cleanup` 和 49 个带唯一名称及输出标记的合成技能。测试比对完整最终输出，能发现步骤缺失、顺序错误和重复执行。

## 实测结果

| 验收项 | 第二轮实测 |
| --- | --- |
| 服务发现 | Eureka 中三个应用实例均为 UP，Feign 日志确认按服务名选择实例 |
| 数据集技能 | `text-cleanup` 单技能执行结果与预期一致 |
| 50 技能串联 | 50 个技能按顺序执行，完整输出匹配，单次耗时 452.50 ms |
| 热加载与卸载 | 60 轮全部完成，加载后的执行均成功，卸载后的 60 次调用均返回预期的 404 |
| 并发稳定性 | 8 路调用持续 60.01 秒，58,899 次两技能流程输出正确，意外错误 0，端到端 P95 17.71 ms，P99 27.67 ms |
| 热操作延迟 | 一轮注册与卸载两次 HTTP 请求的耗时之和 P95 为 26.88 ms，P99 为 34.36 ms |
| 配置下最大注册量 | 100,000 条，从 50 条批量补到上限耗时 3.02 秒，超出 1 条返回 409，计数仍为 100,000 |
| 满载执行 | 50 步链再次通过，耗时 138.10 ms。容量样本的首、中、尾三个技能可执行。另有 1,000 次两技能调用全部通过，P95 22.19 ms，P99 30.03 ms |
| 运行状态 | 前后容器 ID 和启动时间一致，四个容器重启 0、OOM 0，健康检查全部 UP。满载测试后的 Registry 内存快照为 346.8 MiB / 768 MiB |

两阶段的延迟包含客户端、Docker 网络、Feign 和应用执行。50 步链耗时为单次观测，两次测量处于不同的 JVM 预热阶段。

- 并发调用与热操作同时进行时，稳定工作负载的 58,899 次请求均返回正确结果，探针卸载后也立即无法再通过 Flow 查到。这个结果验证了短时并发下的动态变更与后续查找行为。
- 满载时的 P95 为 22.19 ms，低于容量上限且同时进行热操作时的 P95 为 17.71 ms。两阶段的测量时长和背景操作不同，现有数据不足以估计注册量对延迟的独立影响。
- 100,000 条包含最初运行的 50 条和额外生成的 99,950 条轻量容量样本。HTTP 409 验证了配置上限的强制执行。内存数值为测试结束后的快照。

第一轮同样通过容量与稳定性断言。其 Windows 计时分辨率较粗，第二轮使用 Python `perf_counter` 复测，表格采用第二轮数据。

[原始指标](../results/spring-skill-lab.json) · [格式校验与容器状态摘要](../results/spring-skill-lab-environment.json)

## 结论范围

容量结论适用于当前配置和轻量技能定义。Registry 的技能目录是单实例内存状态，重启会清空。热加载和卸载通过 HTTP 提交，修改的是技能定义。已读取定义的在途执行可以完成，卸载后的新查找返回 404。原流程引擎的节点适配、持久化和跨副本一致性尚未集成。本轮短时压测覆盖并发调用和动态变更，长时稳定性、跨机部署和故障恢复仍待验证。
