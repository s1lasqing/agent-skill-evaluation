# 复现步骤

以下命令从同一父目录中的仓库运行，假设本项目目录名为 agent-skill-evaluation。准备 Git、Python 3.12、uv，以及在运行 OfficeQA 时可访问的 Docker Desktop Linux 引擎。

~~~powershell
git clone https://github.com/LDlornd/research.git
git -C research checkout 6c6131b10b4ec4e108dbaf0e4e53b96f199c0608
git clone https://github.com/LDlornd/agent-session-analyzer.git
git -C agent-session-analyzer checkout 502da5b899667bd525241b4e3d0878f9e83540e8
git clone https://github.com/databricks/officeqa.git
git -C officeqa checkout 7b9a3c154ef9fb40215bb67934afc43e6799de16
python .\agent-skill-evaluation\scripts\apply_overlay.py .\research
Set-Location .\research
uv sync --python 3.12 --locked --extra skillret
~~~

从这一步起保持当前目录为 research。

## SkillRet

下载器默认固定原实验的数据版本。用 --plan 核对 5 条查询，移除 --plan 即执行。这个步骤适用 Windows 或 WSL 上已安装依赖的 Python 环境，不需要模型凭据。

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m datasets.skillret --output data/skillret
.\.venv\Scripts\python.exe -X utf8 -m evaluation --dataset config/datasets/skillret-week1.toml --environment config/environments/skillret.toml --agent config/agents/skillret-bm25.toml --evaluation config/evaluation/skillret-week1.toml --name skillret-reproduce --plan
~~~

## OfficeQA

先在 Hugging Face 获得 databricks/officeqa 的访问权限并完成本机认证。下载脚本需要 huggingface_hub，可通过单独的 uv 环境提供。配置模型时，在两份 OfficeQA agent TOML 中替换 example.invalid/v1，保留两边实际使用的模型一致。API key 和费用归属填写在 research 自己的 .env 中，参见 .env.example。模型网关应支持相应的模型协议；复现记录应注明与原实验的服务差异。

~~~powershell
uv run --no-project --with huggingface_hub hf auth login --no-add-to-git-credential
uv run --no-project --with huggingface_hub python ..\agent-skill-evaluation\scripts\download_officeqa.py
.\.venv\Scripts\python.exe -X utf8 -m datasets.officeqa --raw data/officeqa-raw --output data/officeqa
pnpm --dir .\config\dsh\profiles\sdk-minimal install --no-frozen-lockfile
docker version
~~~

保留独立实验名。加 --plan 无模型预览；加 --task UID0001 可另做单题检查，但单题检查应使用不同实验名。

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m evaluation --dataset config/datasets/officeqa-pro.toml --environment config/environments/officeqa.toml --agent config/agents/dsh-officeqa.toml --evaluation config/evaluation/officeqa-pro.toml --name officeqa-pro-dsh-pilot
.\.venv\Scripts\python.exe -X utf8 -m evaluation --dataset config/datasets/officeqa-pro.toml --environment config/environments/officeqa.toml --agent config/agents/openhands-officeqa.toml --evaluation config/evaluation/officeqa-pro.toml --name officeqa-pro-openhands-pilot
~~~

dsh 基线跑完并保存 manifest 后，再运行固定技能对照。下面的入口读取新跑出的本地 dsh 基线并核对清单；公开结果 JSON 不是运行输入。

~~~powershell
.\.venv\Scripts\python.exe -X utf8 ..\agent-skill-evaluation\scripts\download_skillopt.py
.\.venv\Scripts\python.exe -X utf8 ..\agent-skill-evaluation\scripts\run_skillopt.py --plan
.\.venv\Scripts\python.exe -X utf8 ..\agent-skill-evaluation\scripts\run_skillopt.py
~~~

用 trial 的 result.json、原始 trace 和实验 summary.json 检查结果。OfficeQA 的 null 表示未评分，0 表示已评分但答错。600 秒配置用于补充诊断，单列结果。
