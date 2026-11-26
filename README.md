# fermiflow

Fermi-LAT 分析工具：从数据下载、初始 gtlike 拟合、TS map、空间模型组合，到全能段谱型比较和分能段 SED。命令入口为 `fermiflow`，配置模板在 [`templates/`](templates/)，实现代码在 [`scripts/`](scripts/)。

## 安装与更新

在仓库目录中创建环境并安装：

```bash
mamba env create -f environment.yml
conda activate fermi
python -m pip install .
fermiflow --version
```

本地修改并 push 后，在超算的 `fermi` 环境更新安装：

```bash
python -m pip install --upgrade --force-reinstall --no-deps "git+https://github.com/whjing/fermiflow.git@main"
```

首次安装及环境说明见[安装与更新](docs/installation.md)。

## 项目目录

以下命令在分析项目的 `scripts/` 中运行：

```text
my_project/
├── configs/                 # 项目、参数策略和 grid YAML
├── rawdata/                 # Photon、Spacecraft 与下载链接
├── shared/                  # 本项目 ltcube、初始 XML 和目录 region
├── products_1GeV/           # 1–500 GeV 数据和空间分析
├── products_2GeV/           # 2–500 GeV 数据和空间分析
├── products_100MeV/         # 100 MeV–500 GeV 谱分析和 SED
├── figures/
├── logs/
└── scripts/                 # steps.sh、steps_spectral.sh 等项目脚本
```

公共源表和弥散背景放在 `archive_dir: ~/data/fermi`。`steps.sh` 按“初始拟合 → TS map → spatial → gtlike → 比较”分阶段组织；`steps_spectral.sh` 接着完成 100 MeV–500 GeV 谱分析。它们属于分析项目，仓库提供所调用的命令和模板。

## 1. 下载与 prepare

将数据下载页的 URL 或 wget 文本保存为 `urls.txt`，最后一个参数为并行下载进程数：

```bash
fermiflow download ../rawdata/urls.txt ../rawdata 6
fermiflow init --mode project --config ../configs/proj_1GeV.yaml
# 填写目标坐标、能段、原始数据及公共模型路径
fermiflow run --config ../configs/proj_1GeV.yaml --mode prepare
```

`prepare` 建立事件筛选、GTI、ltcube、CMAP、CCUBE、binned exposure，以及 `shared/<target>_model_16yr.xml` 和目录 region。2 GeV 与 100 MeV 分别使用各自项目配置和产品目录。[数据准备详情](docs/quickstart.md)

## 2. 参数策略与初始 gtlike

```bash
fermiflow init --mode model-policy --config ../configs/model_policy.yaml
# 在策略中设置 spectral / norm / fixed、径向分区与背景归一化
fermiflow model --input-model ../shared/my_target_model_16yr.xml --policy ../configs/model_policy.yaml --output-model ../products_1GeV/init_input.xml
fermiflow run --config ../configs/proj_1GeV.yaml --mode like --input-model ../products_1GeV/init_input.xml
```

`model` 打印修改前后自由参数总数；`like` 生成 source maps，依次运行 DRMNFB 与 MINUIT，输出 `init_minuit.xml` 和 `init_minuit_results.dat`。more/less 通过不同参数策略构建初始输入，复用对应能段的项目配置。[模型策略详情](docs/model-policy.md)

项目自己的源名整理、添加候选源等步骤放在这一阶段。空间 grid 的基础 XML 包含本次拟合涉及的全部候选源。

## 3. TS map

```bash
fermiflow init --mode tsmap-grid --config ../configs/tsmap_1GeV.yaml --target my_target --energy-label 1GeV
# 设置 project_config、tasks、size 和 binsz
fermiflow tsmap-grid --config ../configs/tsmap_1GeV.yaml --input-model ../products_1GeV/init_minuit.xml
bash ../products_1GeV/sbatch/submit_tsmap.sh
```

`tasks[].remove_sources` 选择从模型移除哪些源：空列表生成 `tsmap-res`，删源后生成 `tsmap-<源名>`。XML、FITS、sbatch 和 logs 默认放在输入 XML 所在目录及其子目录；FITS 在任务运行后产生。

**相同能段和数据设置下可共用一份 TS map YAML**，用 `--input-model` 选择不同组合。空间组合各有自己的目录，最终 TS map 因而随组合保存。提交脚本默认每次间隔 300 秒。[TS map 详情](docs/quickstart.md#批量-ts-map)

## 4. 空间模型组合

```bash
fermiflow init --mode spatial --config ../configs/spatial_fit.yaml --target my_target --energy-label 1GeV
fermiflow init --mode spatial-grid --config ../configs/grid_1GeV.yaml --target my_target --energy-label 1GeV
# 填写 base、sources、空间策略及任务输出位置
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml
bash ../products_1GeV/spatial_grid/sbatch/submit_spatial.sh
```

以上提交路径对应把 YAML 中 `slurm.sbatch_dir` 设为 `../products_1GeV/spatial_grid/sbatch` 的布局；将 `slurm.log_dir` 及 `gtlike.slurm` 两个目录也设到该 grid 的 `logs/`、`sbatch/`。

组合 tag 按 YAML 源顺序命名，例如 `srcT-P-srcP-N-srcE-G`；P/G/D/N 分别为 Point/Gaussian/Disk/缺失。`include: [true, false]` 配合三种形态生成 P/G/D/N。受检源全部为 N 的组合直接进入后续 gtlike。

空间任务完成后：

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --plot
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --prepare-gtlike
bash ../products_1GeV/spatial_grid/sbatch/submit_like.sh
```

文件衔接为：

```text
共同基础 XML
  → <tag>_spatial.xml + <tag>_spatial.yaml
  → <tag>/<tag>_spatial_final.xml + <tag>.reg
  → <tag>/<tag>_reloc_input.xml
  → <tag>/<tag>_reloc_minuit.xml
```

`_reloc_input.xml` 的谱参数和背景来自 `gtlike.template_model`（默认 `base.input_model`），受检源的位置、形态和尺度来自相应空间拟合结果。固定邻源只测试目标时，仅将目标列入 grid 的 `sources`，邻源保留在输入模板中。

`--plot` 输出 region 组合图以及各源 RA/Dec、延展半径比较图和 CSV。位置图默认显示绝对 RA/Dec，也可选择偏移模式。[空间分析详情](docs/spatial.md)

## 5. 比较空间模型与导出表格

gtlike 完成后：

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --compare-likelihood --reference my_target-P --csv ../products_1GeV/spatial_grid/results.csv
python -m scripts.csv_to_tex ../products_1GeV/spatial_grid/results.csv ../products_1GeV/spatial_grid/results.tex
```

`--reference` 填本轮 manifest 中的完整组合 tag。终端显示 likelihood、k、ΔTS、Δk 和 ΔAIC；CSV 还包含每个受检源的坐标、误差、r68、各阶段 TS 与备注。TeX 转换输出 AASTeX 表格数据行。

## 6. 100 MeV–500 GeV 谱型组合

准备该能段的数据产品后，采用选定空间模型的最终 `_reloc_minuit.xml`：

```bash
fermiflow init --mode spectral-grid --config ../configs/spectral_100MeV.yaml
# base.project_config 指向 proj_100MeV.yaml；input_model 指向选定空间结果
fermiflow spectral-grid --config ../configs/spectral_100MeV.yaml
bash ../products_100MeV/spectral_grid/sbatch/submit_like.sh
# 拟合完成后
fermiflow spectral-grid --config ../configs/spectral_100MeV.yaml --compare-likelihood --reference srcT-PL
```

一个源的 `[pl, lp]` 生成两组；两个源各测试两种谱型生成四组。全部空间参数固定，提交间隔为 3 秒。输出 `spectral_comparison.csv` 和逐源 PL/LP 对比的 `spectral_curvature.csv`。[谱型配置与输出](docs/sed.md)

## 7. 分能段 SED 与重拟合

将选定的全能段谱结果设为项目配置的 `files.sed_model`，并填写 `files.base_gti`：

```bash
fermiflow run --config ../configs/proj_100MeV.yaml --mode bin --nbins 6 --ibin 1
# 每个能段分别运行，ibin 从1开始
fermiflow init --mode sed-filter --config ../configs/sed_filter.yaml
# jobs 中逐项填写同一能段的 input_model、results_file 和 ibin
fermiflow sed-filter --config ../configs/sed_filter.yaml
fermiflow sed-submit --config ../configs/sed_filter.yaml
bash ../sbatch/sed_6bin_tslt2/submit_sed_filter.sh
```

直接重拟合单个能段可用 `run --mode bin-fit --input-model <修改后的_input.xml>`。`summary.sources` 控制拟合结束时打印的源列表。[SED 详情](docs/sed.md#分能段-sed)

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [安装与更新](docs/installation.md) | 创建环境、本地安装与 GitHub 更新 |
| [数据准备与 TS map](docs/quickstart.md) | 数据、prepare、初始模型及残差图 |
| [模型参数策略](docs/model-policy.md) | 半径分区、谱参数、TS 筛选 |
| [空间模型](docs/spatial.md) | spatial-grid、固定邻源、绘图、CSV |
| [谱与 SED](docs/sed.md) | spectral-grid、分能段与筛选重拟合 |
| [注意事项与限制](docs/notes.md) | 路径、覆盖、任务衔接、失败结果与统计解释 |
| [排错](docs/troubleshooting.md) | 错误定位和结果追溯 |
