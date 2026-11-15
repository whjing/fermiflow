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
fermiflow init --mode model-policy --config ../configs/model_policy.yaml
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
- 银河系弥散辐射模型 [`gll_iem_v07.fits`](https://fermi.gsfc.nasa.gov/ssc/data/analysis/software/aux/4fgl/gll_iem_v07.fits)
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
├── myTarget_1GeV_model_16yr.xml
└── ROI_myTarget_1GeV_model_16yr_carta.reg
```

初始 XML 是**目录模型**，不是最终科学模型。它包含 catalogue 源和 diffuse backgrounds。

### 目录 region 文件

生成 XML 时，流水线会额外写出一个 CARTA 可直接读入的 `.reg` 文件。它从 XML 的 `spatialModel` 读取信息：

- `SkyDirFunction` 点源：中心十字；
- `RadialGaussian`：中心十字与 $r_{68}=1.5096\sigma$ 圆；
- `RadialDisk`：中心十字与 $r_{68}=\sqrt{0.68}R$ 圆；
- Galactic/isotropic diffuse 与 `SpatialMap` 等没有圆对称尺度的源：跳过，不强行画成圆。

可用改 region 文件检查 catalogue 初始模型。

---

## 4. 基准全能段似然拟合与残差检查

按[模型参数策略](model-policy.md)建立 baseline XML，再用它 进行一次全能段拟合：

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode like \
  --input-model ../shared/models/myTarget_baseline_input.xml
```

每次 `like` 都重新生成与该 XML 对应的 source maps，然后运行 DRMNFB 与 MINUIT。常见产品为：

```text
myTarget_baseline_srcmaps.fits
myTarget_baseline_drmnfb.xml
myTarget_baseline_minuit.xml
myTarget_baseline_minuit_results.dat
```

使用下例的 `*_minuit.xml` 生成 TS map，检查是否有未建模残差或候选邻源：

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode tsmap \
  --input-model ../shared/models/myTarget_baseline_minuit.xml \
  --size 5 --binsz 0.05
```

若 TS map 显示稳定的新残差，应先把该候选源加入共同的模型模板，再开始空间模型之间的正式比较。不要让不同候选空间组合使用不同的背景源清单。

---


## 用链接文本多核下载 Fermi 数据

将 Fermi 下载页面给出的普通链接保存为 `urls.txt`。文件既可以是每行一个 URL，也可以直接粘贴一大段普通 `wget ... URL` 文本；脚本会自动抽取全部 HTTP(S) 链接：

```text
https://.../PH00.fits
https://.../PH01.fits
https://.../SC00.fits
```

然后设置下载目录和并行任务数：

```bash
fermiflow download ../urls.txt ../rawdata 6
```

等价于：

```bash
bash /path/to/fermiflow/scripts/download.sh ../urls.txt ../rawdata 6
```

这里的 `6` 是同时运行的 wget 数。脚本使用 `wget --continue`，中断后用同一命令可继续下载未完成文件。


下一步可做[空间拟合](spatial.md)或[谱与 SED 分析](sed.md)。
