# 上游与数据来源

- [research](https://github.com/LDlornd/research/tree/6c6131b10b4ec4e108dbaf0e4e53b96f199c0608) 提供调度与 harness 接口；本仓库提供实验扩展和兼容补丁。
- [agent-session-analyzer](https://github.com/LDlornd/agent-session-analyzer/tree/502da5b899667bd525241b4e3d0878f9e83540e8) 提供记录器。
- [SkillRet 数据](https://huggingface.co/datasets/ThakiCloud/SKILLRET/tree/6583d7d2ed07644d0fb8938ed8178f3a7dc42a12) 用于 BM25 检索，论文见 [arXiv](https://arxiv.org/abs/2605.05726)。
- [OfficeQA 数据](https://huggingface.co/datasets/databricks/officeqa/tree/763a8366abf2a3605c381d53586d844dc60fa756) 与 [评分器](https://github.com/databricks/officeqa/blob/7b9a3c154ef9fb40215bb67934afc43e6799de16/reward.py) 来自 Databricks。数据需按上游访问条件获取。
- [SkillOpt](https://github.com/microsoft/SkillOpt/tree/22c1ed85d20bf09476373c4a1b10965284873e3d/ckpt/officeqa) 是 Microsoft 的公开技能研究项目。本实验复用其已发布 Checkpoint，没有训练技能；使用的文件哈希和样本划分见 [source.json](../skillopt/source.json)。
- [rsi-flow-spring-boot](https://github.com/ymxiong/rsi-flow-spring-boot/tree/11b418d3068343d0430e46a58650f97d189159d5) 提供 Spring 项目结构和 Feign 服务发现参考。本仓库的 [skill-lab](../skill-lab/) 是可独立构建的实验模块。模块使用同版本 SkillRet 测试库中的 [text-cleanup](https://github.com/majiayu000/claude-skill-registry/tree/main/skills/data/text-cleanup) 样本，UID 和原文 SHA-256 见 [实验结果](../results/spring-skill-lab.json)。

发布前由项目所有者确认扩展源码、上游补丁和自身贡献的公开许可。原始数据与 trace 按各自来源规定保管。
