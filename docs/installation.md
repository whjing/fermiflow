# 安装与更新

先安装 [Miniforge](https://github.com/conda-forge/miniforge)，然后在 fermiflow 仓库根目录运行以下命令。

## 首次安装

```bash
mamba env create -f environment.yml
conda activate fermi
python -m pip install .
python -c "import pyLikelihood; from fermipy.gtanalysis import GTAnalysis; from LATSourceModel import SourceList"
fermiflow --help
```

`mamba` 根据 [environment.yml](../environment.yml) 创建环境并安装 Fermitools。pip 根据 [pyproject.toml](../pyproject.toml) 准备临时构建环境，然后将 fermiflow 和 Python 依赖（包括 Fermipy 和 LATSourceModel）安装到当前环境。

如果已有名为 `fermi` 的环境，可用 `mamba env update -n fermi -f environment.yml` 补齐 Conda 包，然后从 `conda activate fermi` 继续。

## 超算安装与更新

已有环境时可直接使用 GitHub 地址；新环境可以先在超算上用一份 `environment.yml` 创建。安装需要能访问 GitHub 和 Python 包索引。

```bash
conda activate fermi
python -m pip install --upgrade "git+https://github.com/whjing/fermiflow.git@main"
```

首次安装由 pip 补齐 Python 依赖。如果已经安装过所需依赖，而且只想重装包版本号未变的 fermiflow，使用：

```bash
python -m pip install --upgrade --force-reinstall --no-deps \
  "git+https://github.com/whjing/fermiflow.git@main"
```

如果 pip 无法获取临时环境的构建依赖，而当前 `fermi` 环境已装有 `setuptools`，可以给安装命令加上 `--no-build-isolation`，直接用当前环境构建。

## 本地开发

```bash
git status
git add .
git commit -m "Describe the change"
git push origin main
```

随后在超算重新执行上面的 `pip install --upgrade` 命令。普通 pip 安装不会自动跟随 GitHub 改动；每次需要新版本时重新安装一次即可。安装完成后直接运行 `fermiflow --help` 或具体分析命令。

- 提交内容：代码、YAML、少量 XML 模板、region 和 Slurm 脚本。

- 忽略：原始事件文件、FITS 产品、source maps、批量日志、`rawdata/`、`products*/`、`logs/`、`sbatch/`。这些已经由 `.gitignore` 排除。

## 查看已安装的版本

运行 `fermiflow --version` 查看包版本和 Git commit。发布新版本时，在 `pyproject.toml` 的 `[project]` 中更新 `version`。从 Git 仓库安装时，commit 对应安装所用的 Git 提交。本地构建时，commit 对应当时的 HEAD，构建中包含的未提交改动无法通过 commit 识别。缺少 Git 来源信息的安装会显示 `git: unknown`。
