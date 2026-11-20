# 快速开始

这是一份按实际分析顺序组织的工作手册，适合从一个新目标开始完成 Fermi-LAT 的空间分析、全能段谱拟合和 SED。

本文中的命令假设当前目录是项目的 `scripts/`：

```text
my_project/
├── configs/                 # 项目 YAML 与自由参数策略
├── shared/                    # 可复用的本项目 livetime cube、XML、region 等
├── rawdata/                 # Photon 与 spacecraft FITS
├── products_1GeV/           # 由 Fermitools/Fermipy 生成的产品
├── logs/
└── scripts/                 # 在这里运行 fermiflow
```

角尺度默认用度，能量默认用 MeV。命令行传入的相对路径以当前工作目录为基准。`fermitools_project.yaml` 中的项目路径也以当前工作目录为基准，`spatial_fit.yaml`、`spatial_grid.yaml` 和 `sed_filter.yaml` 中的配置路径则以各自 YAML 文件所在目录为基准。

---

## 0. 开始前：建立配置与确定分析问题

先建立项目配置。模板不会覆盖已有文件：

```bash
fermiflow init --mode project --config ../configs/fermitools_project.yaml
```

首先编辑 `fermitools_project.yaml` 中的：

- `analysis.target`：简短项目名；
- `analysis.ra`、`analysis.dec`：ROI 中心；
- `analysis.emin`、`analysis.emax`：主分析能段；
- `analysis.roi_radius`、`mapsize_deg`、`binsz`；
- `paths`：共享背景文件与项目数据目录；
- `files.ltcube`：建议保留 `{shared_dir}/{target}_ltcube.fits`，可在同一项目复用。

在开始处理前，明确三件事：研究能段、ROI 中心、以及你希望比较的空间假设（目标是点源、Gaussian、Disk；是否包含邻近候选源）。空间模型、谱型与背景自由度必须在同一轮比较中保持可追溯。

---


## 1. 下载 LAT 数据和公共模型


在 [FSSC LAT Data Server](https://fermi.gsfc.nasa.gov/cgi-bin/ssc/LAT/LATDataQuery.cgi) 根据 ROI 中心、时间范围、能段和下载半径取得 Photon 与 Spacecraft 文件链接。下载半径通常要覆盖事件筛选半径并留出 PSF 余量（通常选15deg）。

将下载页提供的 URL（或整段 `wget ... URL` 文本）保存为 `../rawdata/urls.txt`，然后并行下载：

```bash
fermiflow download ../rawdata/urls.txt ../rawdata 6
```

确认 `rawdata/` 至少包含一个或多个 `*_PH*.fits` 和一个 `*_SC*.fits`。同时在 `~/data/fermi/`（或 `fermitools_project.yaml` 的 `archive_dir`）准备：

- Fermi-LAT 源表：
  - [FL16Y 16 年源表 `gll_psc_v38.xml`](https://fermi.gsfc.nasa.gov/ssc/data/access/lat/fl16y/gll_psc_v38.xml)
  - [4FGL-DR4 14 年源表 `gll_psc_v32.xml`](https://fermi.gsfc.nasa.gov/ssc/data/access/lat/14yr_catalog/gll_psc_v32.xml)
- the current Galactic diffuse emission model [`gll_iem_v07.fits`](https://fermi.gsfc.nasa.gov/ssc/data/analysis/software/aux/4fgl/gll_iem_v07.fits)
- 各向同性弥散谱（`P8R3_SOURCE_V3`，FRONT + BACK）[`iso_P8R3_SOURCE_V3_v1.txt`](https://fermi.gsfc.nasa.gov/ssc/data/analysis/software/aux/iso_P8R3_SOURCE_V3_v1.txt)

这些公共背景文件可跨项目共享；项目特有的 livetime cube、模型 XML 和 region 文件应放在 `data/`。

---

## 2. 建立全能段数据产品和目录初始模型

运行一次 `prepare`：

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode prepare
```

它依次建立事件筛选、GTI、livetime cube（若配置文件没有提供已有文件）、CMAP、CCUBE、binned exposure map 和 catalogue 初始 XML。典型输出为：

```text
products_1GeV/
├── myTarget_1GeV_filtered.fits
├── myTarget_1GeV_gti.fits
├── myTarget_1GeV_cmap.fits
├── myTarget_1GeV_ccube.fits
└── myTarget_1GeV_bexpmap.fits

shared/
├── myTarget_ltcube.fits
├── myTarget_model_16yr.xml
└── ROI_myTarget_model_16yr_carta.reg
```

初始 XML 是**目录模型**，不是最终科学模型。它包含 catalogue 源和 diffuse backgrounds。

### 目录 region 文件

生成 XML 时，流水线会额外写出一个 CARTA 可直接读入的 `.reg` 文件。它结合 XML 的 `spatialModel` 和源表坐标绘制标记：

- `SkyDirFunction` 点源：中心十字；
- `RadialGaussian`：中心十字与 $r_{68}$ 圆；
- `RadialDisk`：中心十字与 $r_{68}=$ 圆；
- `SpatialMap`：有坐标时在源中心画菱形并标注源名。
- 无坐标的 `SpatialMap` 与 Galactic/isotropic diffuse：跳过。
---

## 修改模型文件


```bash
fermiflow init --mode model-policy --config ../configs/model_policy.yaml
```

编辑 `model_policy.yaml`，按需设置邻源的半径分区、弥散背景的归一化和指定源的自由参数。然后把上一节 `prepare` 生成的初始 XML 作为输入，写出下一节基准拟合使用的模型。

```bash
fermiflow model --input-model ../shared/myTarget_model_16yr.xml --policy ../configs/model_policy.yaml --output-model ../products_1GeV/myTarget_1GeV_model_init-1_input.xml
```

命令会报告修改前后的自由参数总数。策略字段见[模型参数策略](model-policy.md)。

## 4. 基准全能段似然拟合
进行gtlike拟合，注意或需要反复迭代，到quality =3. 

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode like --input-model ../shared/models/myTarget__model_init-1_input.xml
```

每次 `like` 都重新生成与该 XML 对应的 source maps，然后运行 DRMNFB 与 MINUIT。常见产品为：

```text
myTarget_model_init-1_srcmaps.fits
myTarget_model_init-1_drmnfb.xml
myTarget_model_init-1_minuit.xml
myTarget_model_init-1_minuit_results.dat
```

## 残差检查

从分析项目的 `scripts/` 目录运行。先用 `fermiflow model` 将基准拟合的 `*_minuit.xml` 另存为 `*_xxx-tsmap.xml`，并将所有源的谱参数和空间参数设为 `free="0"`。参数数值沿用 MINUIT 拟合结果，原始拟合 XML 保留。

```bash
fermiflow model --default-policy fixed \
  --input-model ../shared/models/myTarget_baseline_minuit.xml \
  --output-model ../shared/models/myTarget_baseline_xxx-tsmap.xm;
```

确认命令显示输出模型的自由参数数为 `0`。然后用这份固定后的 XML 生成 TS map，检查是否有未建模的残差或候选邻源。

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode tsmap --input-model ../shared/models/myTarget_baseline_minuit_fixed.xml --size 5 --binsz 0.05
```

若 TS map 显示稳定的新残差，应先把该候选源加入共同的模型模板，再开始空间模型之间的正式比较。不要让不同候选空间组合使用不同的背景源清单。
---
## Nest step

[spatial analysis](spatial.md)

---
## Reference and Guide
- [binned_likelihood_tutorial](https://github.com/fermi-lat/AnalysisThreads/blob/master/SourceAnalysis/1.BinnedLikelihood/binned_likelihood_tutorial.ipynb)
## 批量生成 TS map 任务

```bash
fermiflow init --mode tsmap-grid --config ../configs/tsmap_grid.yaml --target my_target --energy-label 1GeV
# 编辑 project_config 和 tasks 中要删除的准确源名。
fermiflow tsmap-grid --config ../configs/tsmap_grid.yaml --input-model ../products_1GeV/my_target_minuit.xml
bash ../products_1GeV/sbatch/submit_tsmap.sh
```

生成器固定模板中全部参数，再按 `tasks[].remove_sources` 删除完整源节点；原模板不改动。不删除源时输出 `tsmap-res.xml/.fits`，删除源时按 YAML 顺序输出 `tsmap-src1-src2.xml/.fits`。XML 和 FITS 默认写到命令行 `--input-model` 所在目录，每个任务一个 `.sbatch`，统一提交脚本默认在该目录的 `sbatch/submit_tsmap.sh`，Slurm 日志默认在该目录的 `logs/`。可省略 `output_dir`、`slurm.sbatch_dir`、`slurm.log_dir`。如显式设置这些字段，则仍按 YAML 指定路径输出；未设置的 sbatch/log 目录派生自实际输出目录。生成过程不执行或提交任务，也不预先生成 FITS。重复生成会覆盖同名 XML 和任务脚本，运行时 TS map 也会覆盖同名 FITS，保留不同轮次请使用不同目录。

每个任务固定为 1 CPU、激活 `fermi`，不执行 `punlearn`；如批处理找不到 conda，设置 `slurm.conda_sh`。任务日志在 `slurm.log_dir`，流水线自身日志仍按项目 YAML 配置输出。默认任务工作目录为 YAML 所在目录的同级 `scripts/`，也可设置 `slurm.working_dir`。YAML 路径相对于 YAML，命令行输入 XML 路径相对于执行目录。

`defaults.size`（方图边长，度）和 `defaults.binsz`（像素大小，度）可由每个任务覆盖。`submit_delay_seconds` 默认 300，提交脚本在两次 `sbatch` 之间等待 5 分钟，不保证实际调度开始时间间隔。不同源名转换为安全文件名后若重名，则停止生成并提示。若某个任务要求删除的源不在输入 XML 中，则打印缺失源名并跳过整个任务，其他任务继续生成。联合删源中只要有一个源缺失也跳过整项，不悄悄改成部分删源。提交脚本只包含本次有效任务；旧的同名 XML/sbatch/FITS 不自动删除，但不会加入本次提交清单。全部任务被跳过时生成不含 sbatch 命令的提交脚本，不提交任何任务。

多个空间组合各自的 `_reloc_minuit.xml` 在不同目录时，同一份 TS-map YAML 可重复使用，自动在各输入目录生成任务，不相互覆盖。如果不同输入 XML 位于同一目录（例如初始 more/less 模型），同级的 tsmap-res 等名称仍会相同，应分别显式设置独立 output_dir。输入 XML 本身不会被改写。
