# fermiflow

用于 Fermi-LAT binned-likelihood 与 Fermipy 空间拟合的轻量工作流。仓库以 Kes 27 的分析参数为示例，但日常使用时应为每个目标单独生成 YAML 配置，避免覆盖已有结果。

## 目录结构

```text
fermiflow/
├── fermiflow.py                  # 安装后提供 fermiflow 命令
├── pyproject.toml
├── README.md
├── examples/
│   └── kes27_100MeV.yaml         # 当前 Kes 27 配置示例
└── scripts/
    ├── run_kes27.py              # Fermitools 主流程
    ├── fermi_target.py           # Fermitools 各个处理步骤
    ├── run_spatial.py            # Fermipy 定位与延展拟合
    ├── utils.py                  # 日志与路径公共函数
    ├── download.sh               # URL 列表的并行 wget 下载
    ├── fix-sedbin.py             # 依照 TS 固定 SED bin 的低显著性背景源
    ├── plot_sed.py               # 绘制 SED、PL/LogParabola 与近似误差带
    └── compute_likelihood.py     # 计算手动输入模型之间的 ΔTS
```

没有 `src/` 或额外 Python 包层级。所有实际分析代码都在 `scripts/`；根目录只保留安装入口、说明和打包配置。

`gtlike.par`、`gtsrcmaps.par` 是运行时生成的参数记录，不是项目配置，已不纳入仓库。每个项目只需维护自己的 YAML 文件。

## 本地开发与超算安装

你只在本地仓库中修改、测试、提交和 push 代码；超算只安装 GitHub 已发布的版本。Fermitools、Fermipy、NumPy、PyYAML、regions、matplotlib 等科学依赖应预先在目标 Conda 环境中安装。

本地开发时，如需在本机运行命令：

```bash
conda activate fermi
cd /path/to/fermiflow
python -m pip install . --no-deps --no-build-isolation
```

超算无需 clone 仓库，直接安装：

```bash
conda activate fermi
python -m pip install --upgrade --no-deps --no-build-isolation \
  "git+https://github.com/whjing/fermiflow.git@main"
```

pip 只会临时获取 GitHub 源码并安装到当前 `fermi` 环境；它不会在你的 home 目录保留项目 checkout。

```bash
fermiflow --help
fermiflow path
```

## 为新目标创建配置

```bash
fermiflow init ../configs/g328_4_100MeV.yaml
```

此命令会生成一份不会覆盖已有文件的样本配置。编辑其中的 `target`、`ra`、`dec`、能量范围、数据路径和产品目录。现有 Kes 27 参数可参照：

```text
examples/kes27_100MeV.yaml
```

最重要的设置为：

```yaml
analysis:
  target: my_target
  ra: 0.0
  dec: 0.0
  roi_radius: 15.0
  emin: 100.0
  emax: 500000.0
  mapsize_deg: 10.0
  binsz: 0.1

paths:
  common_data_dir: ~/data/fermi
  project_data_dir: ./data
  rawdata_dir: ./rawdata
  products_dir: ./products_{energy_label}
  log_dir: ./logs
```

相对路径相对于运行命令时的当前目录。因此建议在分析项目目录中运行命令，配置内使用稳定的相对路径或绝对路径。

对于首次 SED 分能段拟合，`files:` 还必须设置：

```yaml
  ltcube: "{project_data_dir}/ltcube/my_target_ltcube.fits"
  base_gti: "{products_dir}/{analysis_name}_gti.fits"
  sed_model: "{project_data_dir}/models/my_target_sed_input.xml"
```

推荐的项目目录是：

```text
my_project/
├── configs/                  # 此项目的 YAML
├── data/
│   ├── ltcube/               # 可跨本项目复用的 livetime cube
│   ├── models/               # 固定输入 XML、空间模板
│   └── regions/              # DS9 region 文件
├── rawdata/                  # 下载的 photon / spacecraft FITS
├── products_100MeV/          # 可再生的 Fermitools 产物
└── logs/
```

全局目录 `~/data/fermi/` 只放可跨项目共享的文件，例如 `gll_psc_16yr_v38.xml`、`gll_iem_v07.fits`、`iso_P8R3_SOURCE_V3_v1.txt` 和其他公共空间模板。`data/` 则保存只对当前项目有意义、但不想反复生成的输入；其中 `data/ltcube/` 是 ltcube 的推荐位置。

## Fermitools 主流程

通过已安装命令运行：

```bash
fermiflow run -- --config configs/g328_4_100MeV.yaml --mode MODE
```

或直接运行：

```bash
python scripts/run_kes27.py --config configs/g328_4_100MeV.yaml --mode MODE
```

| 模式 | 功能 | `--input-model` |
| --- | --- | --- |
| `prepare` | 从原始 LAT 文件生成 filtered events、GTI、CMAP、CCUBE、曝光图和目录 XML | 不需要 |
| `like` | 复用全能段 CCUBE/曝光图，对指定 XML 重建 source maps 并进行 DRMNFB + MINUIT | 必须 |
| `tsmap` | 复用全能段产品与指定 XML，生成 TS map | 必须 |
| `bin` | 首次构造一个对数 SED 能段并拟合 | 不需要 |
| `bin-fit` | 复用已有 bin 的 CCUBE/曝光图，只替换 XML 重新拟合 | 必须 |

### 建立全能段数据产品

```bash
fermiflow run -- \
  --config configs/g328_4_100MeV.yaml \
  --mode prepare
```

`prepare` 仅建立事件、曝光和目录模型产品；它不替代正式的似然拟合。

### 使用指定模型拟合全能段

```bash
fermiflow run -- \
  --config configs/g328_4_100MeV.yaml \
  --mode like \
  --input-model ../products_100MeV/model_input.xml
```

会依次执行 `gtsrcmaps`、`gtlike (DRMNFB)`、`gtlike (MINUIT)`，并生成 `*_srcmaps.fits`、`*_drmnfb.xml`、`*_minuit.xml` 与结果文件。

### 生成 TS map

```bash
fermiflow run -- \
  --config configs/g328_4_100MeV.yaml \
  --mode tsmap \
  --input-model ../products_100MeV/model_minuit.xml \
  --size 5 \
  --binsz 0.05
```

`size` 为图的边长（deg），`binsz` 为像素尺寸（deg）。一般使用收敛后的 `*_minuit.xml`。

### 首次分能段 SED 拟合

```bash
fermiflow run -- \
  --config configs/g328_4_100MeV.yaml \
  --mode bin \
  --nbins 6 \
  --ibin 1
```

`--ibin` 从 1 开始。首次 `bin` 要求 `ltcube`、`base_gti`、`sed_model` 均存在；分 bin 边界由 `emin`、`emax` 和 `nbins` 自动以对数间隔计算。

### 用改过的模型重跑已有 SED bin

```bash
fermiflow run -- \
  --config configs/g328_4_100MeV.yaml \
  --mode bin-fit \
  --nbins 6 \
  --ibin 6 \
  --input-model /absolute/path/my_target_sed_6bin06-mod_input.xml
```

`bin-fit` 不会重复事件筛选、CCUBE 和曝光图计算，但会重新生成 source maps 和两次 gtlike。它会覆盖该 bin 目录中同名拟合产物；比较不同模型前应复制 XML 或保存结果目录。

## Fermipy 空间分析

```bash
fermiflow spatial -- --config configs/spatial_g328_4.yaml
```

空间配置独立于 Fermitools 配置，使用 Fermipy 的 `fermipy:` 块以及顶层 `output:`、`outputs:` 和 `sources:`。例如：

```yaml
sources:
  - name: target
    spatial_model: RadialGaussian
    extension:
      width_min: 0.05
      width_max: 1.0
      width_nstep: 25
      fit_position: true

  - name: nearby_point_source
    spatial_model: PointSource
    localization:
      dtheta_max: 1.0
      nstep: 20
```

该流程写出最终 ROI XML 与 DS9 region。正式报告 `TS_ext` 时，点源与延展模型应各自独立定位并重新优化背景，不能把点源中心固定到延展模型中心后直接作显著性结论。

## 用链接文本多核下载 Fermi 数据

将 Fermi 下载页面给出的普通链接保存为 `urls.txt`。文件既可以是每行一个 URL，也可以直接粘贴一大段普通 `wget ... URL` 文本；脚本会自动抽取全部 HTTP(S) 链接：

```text
https://.../PH00.fits
https://.../PH01.fits
https://.../SC00.fits
```

然后设置下载目录和并行任务数：

```bash
fermiflow download urls.txt rawdata 6
```

等价于：

```bash
bash scripts/download.sh urls.txt rawdata 6
```

这里的 `6` 是同时运行的 wget 数。脚本使用 `wget --continue`，中断后用同一命令可继续下载未完成文件。

## Kes 27 辅助脚本

- `scripts/fix-sedbin.py`：从 SED 日志读取 TS，固定低显著性背景源并生成 `-mod_input.xml`。
- `scripts/plot_sed.py`：读取 SED 日志和全能段 XML，绘制 (E^2dN/dE)、上限及近似谱误差带。
- `scripts/compute_likelihood.py`：修改文件顶部的 `models` 字典后，计算相对模型的 (2\Delta\log\mathcal{L})。

这三项仍记录当前 Kes 27 的具体文件名和路径。用于新目标时，请复制一份并明确更改输入文件；不要直接让新项目写入 Kes 27 的产品目录。

## 本地编辑与超算使用

GitHub 是唯一代码源：

```text
本地编辑 → commit → push → 超算从 GitHub 普通安装/升级 → 提交任务
```

本地每次修改后：

```bash
git status
git add .
git commit -m "Describe the change"
git push origin main
```

随后在超算重新执行上面的 `pip install --upgrade` 命令。普通 pip 安装不会自动跟随 GitHub 改动；每次需要新版本时重新安装一次即可。安装完成后直接运行 `fermiflow --help` 或具体分析命令。

提交到 Git：代码、YAML、少量 XML 模板、region 和 Slurm 脚本。

不要提交：原始事件文件、FITS 产品、source maps、批量日志、`rawdata/`、`products*/`、`logs/`、`sbatch/`。这些已经由 `.gitignore` 排除。
