# fermiflow

## 待办

- Fermipy 的 gtselect 也用 15°，可以显式设 fermipy.selection.radius: 15.0，目前本地安装的 Fermipy 会自动取方图半对角线 + 0.5°，默认约 7.57°。 需要确定是否需要修改

- 确定一下
用于 Fermi-LAT binned likelihood、Fermipy 空间拟合与分能段 SED 的命令行工作流。辅助脚本在 `scripts/`，项目 YAML 模板在 [`templates/`](templates/)。
- run_gtbin_cmap设置为边长为直径的外切圆
- run_gtbin_ccube 设置为边长为1.41*R的内切圆。

## 安装

安装 Miniforge 后，在本仓库根目录运行：

```bash
mamba env create -f environment.yml
conda activate fermi
python -m pip install .
fermiflow --help
```

`environment.yml` 安装 Fermitools，随后 pip 安装 fermiflow、Fermipy 与其余 Python 依赖。已有 `fermi` 环境或想在超算直接从 GitHub 安装，可参照[安装与更新](docs/installation.md)。

## 第一次运行

在分析项目的 `scripts/` 目录运行以下命令。生成配置后，填写目标坐标、能段和输入路径，再执行 `prepare`。

```bash
fermiflow init --mode project --config ../configs/fermitools_project.yaml
# 编辑 ../configs/fermitools_project.yaml，并准备 photon、spacecraft 和背景文件
fermiflow run --config ../configs/fermitools_project.yaml --mode prepare
```

`fermiflow init --help` 列出所有模板。用 `--mode` 选择模板，用 `--config` 指定输出路径。省略 `--config` 时，模板以默认文件名写入当前目录。

## Grid 对照模型

`spatial-grid` 支持受检源全部为 `N` 的背景对照组合：跳过空间拟合，直接通过 `--prepare-gtlike` 生成 gtlike 输入和任务，完成后一起比较 likelihood/AIC。仅删除 YAML 列出的受检源，保留其他背景源。参见[全 N 对照模型](docs/spatial.md#全部受检源缺失的对照组合)。

## Wiki

| 页面 | 内容 |
| --- | --- |
| [安装与更新](docs/installation.md) | 本地安装、超算更新、开发流程 |
| [快速开始](docs/quickstart.md) | 项目布局、数据下载、基准拟合、TS map 与 tsmap-grid 批量任务 |
| [模型参数策略](docs/model-policy.md) | XML 参数自由度、邻源半径和 TS 筛选 |
| [空间模型](docs/spatial.md) | 点源定位、Gaussian / Disk、Slurm 和 likelihood 比较 |
| [谱与 SED](docs/sed.md) | 全能段 PL / LP、分能段拟合、TS 筛选和绘图 |
| [检查与排错](docs/troubleshooting.md) | 常见问题与结果追溯 |
