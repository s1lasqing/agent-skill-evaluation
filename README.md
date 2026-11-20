# Agent Skill Evaluation · SkillRet / OfficeQA / Spring Skill Lab

这个项目记录三组技能实验。SkillRet 基于 [research](https://github.com/LDlornd/research) 评估技能检索，OfficeQA 比较两个 harness 及固定技能对作答的影响，Spring Skill Lab 验证技能注册容量、Feign 串联和动态加载卸载。仓库包含基线代码、运行配置、复跑入口和结果分析。

## 实验结果

### SkillRet · 技能检索

固定 5 条查询从 6,006 个候选技能中检索。BM25 使用技能名称、描述和正文，返回前 20 个结果。dsh 与 OpenHands 分别组织复跑，两份逐题指标一致；检索和评分由同一个非 LLM 执行器完成。

| 样本数 | NDCG@10 | Recall@10 | MAP@10 | Precision@10 | Completeness@10 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 0.4165 | 0.3667 | 0.3667 | 0.0600 | 0.2000 |

这些结果验证了检索流程可以复现。样本为固定小清单，不能用于估计全量表现。当前版本未接入技能表示对照和拒绝调用评测。[逐题数据](results/skillret.json)

### OfficeQA Pro · 两种 harness 与固定技能对照

在同一批三题和 697 份 Treasury Bulletin TXT 语料上运行，使用 DeepSeek Flash、Docker Linux、终端与只读文件工具。每题智能体预算 300 秒，Databricks 官方评分器的数值容差为 0。超时题无分数；答对率和评分覆盖率的分母均为计划题数。

| 300 秒主对照 | UID0001 | UID0003 | UID0004 | 答对率 | 评分覆盖率 | 超时 |
| --- | --- | --- | --- | ---: | ---: | ---: |
| dsh 无技能基线 | 超时 | 1 | 超时 | 1/3 | 1/3 | 2/3 |
| OpenHands 无技能基线 | 超时 | 1 | 超时 | 1/3 | 1/3 | 2/3 |
| dsh + Microsoft SkillOpt | 0 | 1 | 超时 | 1/3 | 2/3 | 1/3 |

加入 SkillOpt 后，**少了一道超时题，答对数仍是 1/3**。新增提交的 UID0001 得分为 0。UID0003 前后均答对，工具调用从 13 次增至 30 次。UID0004 前后均超时，调用从 37 次增至 56 次。三题的单次结果适合发现问题，不能据此判断技能对整体正确率的影响。

本项目扩展了 OfficeQA 的任务加载、容器隔离、官方评分与结果落盘，并增加了 SkillOpt 对照入口。入口校验公开技能文件的 SHA-256，逐题附加固定版本的技能正文，同时核对基线配置和任务清单。OfficeQA 原有无网容器只暴露只读语料与每题工作区，答案由宿主评分器持有。此条件测量「提供技能」的效果。UID0001 属于 SkillOpt 的验证集，另外两题属于其公开测试集。[技能版本与划分](skillopt/source.json)

补充记录独立于主对照。600 秒诊断中，dsh 两题均超时，OpenHands 一题得 1、一题得 0。OpenHands 的 300 秒 v2 重跑为两题答对、一题超时；v3 的末题仍标记为运行中，属于未完整收尾的批次。[所有记录及耗时](results/officeqa.json)

### Spring Skill Lab · 注册、串联与动态加载

在 Docker 中运行 Eureka、Registry、Worker 和 Flow。Flow 通过 Feign 按服务名查找技能定义和调用执行服务。初始流程包含 1 个从 SkillRet 适配的 `text-cleanup` 和 49 个合成技能，50 步顺序执行的完整输出已校验。

| 指标 | 第二轮实测 |
| --- | --- |
| 注册容量 | 达到配置上限 100,000 条，额外注册返回 HTTP 409 |
| 动态加载与卸载 | 60 轮通过，卸载后 60 次新调用均返回预期的 HTTP 404 |
| 并发与稳定性 | 8 路并发运行 60.01 秒，58,899 次两技能调用成功，意外错误 0，P95 17.71 ms |
| 满载执行 | 50 步调用链通过，另有 1,000 次两技能调用全部通过，P95 22.19 ms |

容量数据适用于本机 Docker 上的单实例内存注册中心和轻量定义。实验模块独立运行，原 RSI 流程引擎的节点适配和长期稳定性仍待验证。[基线代码与复跑](skill-lab/) · [结果分析报告](docs/spring-skill-lab-report.md) · [原始指标](results/spring-skill-lab.json)

## 文件结构

| 路径 | 用途 |
| --- | --- |
| [overlay/datasets](overlay/datasets) · [overlay/environment](overlay/environment) | 数据包转换、任务与评分适配、OfficeQA Docker 环境 |
| [overlay/config](overlay/config) | 按数据集、环境、执行器和评分拆分 TOML |
| [patches](patches) | 支持无凭据 BM25 执行器的最小上游补丁和锁文件 |
| [scripts](scripts) | 安装覆盖文件、下载数据及技能、复跑 SkillOpt 对照 |
| [skill-lab](skill-lab) | Spring/Eureka/Feign 基线源码、Docker Compose 和压测脚本 |
| [results](results) | 检索和问答逐题结果、Spring 注册容量与稳定性指标 |
| [docs/reproduce.md](docs/reproduce.md) | SkillRet、OfficeQA 和 Spring 实验复现入口 |

OfficeQA 数据、答案和完整 trace 保存在实验机器。公开结果仅含题号、状态与指标。评分器从 Databricks 上游获取；SkillOpt 文本通过固定提交下载。模型服务地址按本地授权配置。[数据来源和版本](docs/sources.md)
