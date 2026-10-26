# fermiflow

用于 Fermi-LAT binned-likelihood 与 Fermipy 空间拟合的轻量工作流。仓库提供不绑定具体天体的 YAML 模板；每个项目都从模板生成自己的配置文件，避免覆盖已有结果。

## 目录结构

```text
fermiflow/
├── fermiflow.py                  # 安装后提供 fermiflow 命令
├── pyproject.toml
├── README.md
└── scripts/
    ├── run_fermitools.py          # Fermitools 主流程
    ├── fermi_target.py           # Fermitools 各个处理步骤
    ├── run_spatial.py            # Fermipy 定位与延展拟合
    ├── spatial_grid.py           # 批量空间假设、Slurm 脚本与可选图像检查
    ├── utils.py                  # 日志与路径公共函数
    ├── model_editor.py           # 独立 XML 参数自由度策略工具
    ├── download.sh               # URL 列表的并行 wget 下载
    ├── fix-sedbin.py             # 依照 TS 固定 SED bin 的低显著性背景源
    ├── plot_sed.py               # 绘制 SED、PL/LogParabola 与近似误差带
    ├── compute_likelihood.py     # 计算手动输入模型之间的 ΔTS
    └── templates/                # init 命令复制的通用 YAML 模板
        ├── project.yaml
        ├── model_policy.yaml
        ├── spatial.yaml
        └── spatial_grid.yaml
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
python -m pip install --upgrade --no-deps --no-build-isolation "git+https://github.com/whjing/fermiflow.git@main"
```

pip 只会临时获取 GitHub 源码并安装到当前 `fermi` 环境；它不会在你的 home 目录保留项目 checkout。

```bash
fermiflow --help
fermiflow path
```

## 为新目标创建配置

```bash
fermiflow init ../configs/project.yaml
```

此命令会从安装包内的 `scripts/templates/project.yaml` 复制一份不会覆盖已有文件的通用配置。默认约定是在项目的 `scripts/` 目录运行所有命令，因此项目级路径会使用 `../data`、`../rawdata`、`../products_*` 与 `../logs`。编辑其中标注 `CHANGE ME` 的 `target`、`ra`、`dec`、能量范围、数据路径和产品目录。

同样可生成独立的模型策略、空间拟合和空间组合模板：

```bash
fermiflow init-model-policy ../configs/model_policy.yaml
fermiflow init-spatial ../configs/spatial.yaml --target my_target --energy-label 1GeV
fermiflow init-spatial-grid ../configs/spatial_grid.yaml --target my_target --energy-label 1GeV
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
  project_data_dir: ../data
  rawdata_dir: ../rawdata
  products_dir: ../products_{energy_label}
  log_dir: ../logs
```

相对路径相对于运行命令时的当前目录。本文后续命令都假定当前目录是 `<project>/scripts/`。

对于首次 SED 分能段拟合，`files:` 还必须设置：

```yaml
  ltcube: "{project_data_dir}/{target}_ltcube.fits"
  base_gti: "{products_dir}/{analysis_name}_gti.fits"
  sed_model: "{project_data_dir}/models/my_target_sed_input.xml"
```

推荐的项目目录是：

```text
my_project/
├── configs/                  # 此项目的 YAML
├── data/
│   ├── my_target_ltcube.fits # 可跨本项目复用的 livetime cube
│   ├── models/               # 固定输入 XML、空间模板
│   └── regions/              # DS9 region 文件
├── rawdata/                  # 下载的 photon / spacecraft FITS
├── products_100MeV/          # 可再生的 Fermitools 产物
├── logs/
└── scripts/                   # 在此目录运行 fermiflow 命令
```

全局目录 `~/data/fermi/` 只放可跨项目共享的文件，例如 `gll_psc_16yr_v38.xml`、`gll_iem_v07.fits`、`iso_P8R3_SOURCE_V3_v1.txt` 和其他公共空间模板。`data/` 则保存只对当前项目有意义、但不想反复生成的输入。配置 `ltcube: "{project_data_dir}/{target}_ltcube.fits"` 后，`prepare` 会直接在 `data/` 下创建或复用该文件。

## Fermitools 主流程

通过已安装命令运行：

```bash
fermiflow run --config ../configs/project.yaml --mode MODE
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
fermiflow run --config ../configs/project.yaml --mode prepare
```

`prepare` 仅建立事件、曝光和目录模型产品；它不替代正式的似然拟合。

### 使用指定模型拟合全能段

```bash
fermiflow run --config ../configs/project.yaml --mode like --input-model ../products_100MeV/model_input.xml
```

会依次执行 `gtsrcmaps`、`gtlike (DRMNFB)`、`gtlike (MINUIT)`，并生成 `*_srcmaps.fits`、`*_drmnfb.xml`、`*_minuit.xml` 与结果文件。

### 生成 TS map

```bash
fermiflow run --config ../configs/project.yaml --mode tsmap --input-model ../products_100MeV/model_minuit.xml --size 5 --binsz 0.05
```

`size` 为图的边长（deg），`binsz` 为像素尺寸（deg）。一般使用收敛后的 `*_minuit.xml`。

### 首次分能段 SED 拟合

```bash
fermiflow run --config ../configs/project.yaml --mode bin --nbins 6 --ibin 1
```

`--ibin` 从 1 开始。首次 `bin` 要求 `ltcube`、`base_gti`、`sed_model` 均存在；分 bin 边界由 `emin`、`emax` 和 `nbins` 自动以对数间隔计算。

### 用改过的模型重跑已有 SED bin

```bash
fermiflow run --config ../configs/project.yaml --mode bin-fit --nbins 6 --ibin 6 --input-model /absolute/path/my_target_sed_6bin06-mod_input.xml
```

`bin-fit` 不会重复事件筛选、CCUBE 和曝光图计算，但会重新生成 source maps 和两次 gtlike。它会覆盖该 bin 目录中同名拟合产物；比较不同模型前应复制 XML 或保存结果目录。

## 独立修改模型的自由参数

`scripts/model_editor.py` 不依赖 Fermitools 或 Fermipy；它只读取一个 XML、按策略写出一个新的 XML。原输入模型保持不变。它支持三种策略：

- `spectral`：放开归一化和谱形参数，如 `Prefactor`/`norm`、`Index`、`alpha`、`beta`；`Eb`、`Scale` 和全部空间参数固定；
- `norm`：只放开谱归一化参数，其余谱参数与空间参数固定；
- `fixed`：该源所有参数固定。

例如，把下面内容单独保存为 `../configs/model_policy.yaml`。它不属于项目总 YAML。该例会将目标中心 3° 以内的源全部放开，3°--5° 的源只放开归一化，5° 外固定，同时使 Galactic 与 isotropic 背景只放开归一化：

```yaml
radial:
  # Uses each source's ROI_Center_Distance attribute (deg).
  # Add center: {ra: ..., dec: ...} only for a different center.
  zones:
    - {max_radius: 3.0, policy: spectral}
    - {max_radius: 5.0, policy: norm}
  outside_policy: fixed
background_norms: [gll_iem_v07, iso_P8R3_SOURCE_V3_v1]
sources:
  my_target: spectral
```

指定源的 `sources:` 规则优先级最高，因而可用于强制放开目标源或指定邻源；例如 `nearby_source: norm`。没有位置的背景源不会套用半径分区，只会由 `background_norms` 或 `sources` 控制。

如果只想放开目标源的所有参数，以及银河/各向同性背景的归一化，而固定其它全部源，则用更短的版本：

```yaml
default_policy: fixed
sources:
  my_target: spectral
background_norms: [gll_iem_v07, iso_P8R3_SOURCE_V3_v1]
```

如果已有一次 gtlike 输出的 `*_results.dat` 文件，可直接让低 TS 源优先固定。例如：

```yaml
ts_filter:
  results_file: ../products_1GeV/target_minuit_results.dat
  threshold: 1.0
  policy: fixed
```

`results_file` 相对本策略 YAML 文件解析。显式的 `sources:` 和 `background_norms:` 优先级高于 TS 筛选；其余 `TS < 1` 的源固定，剩余源再执行半径分区。

单独生成模型时，把上面的内容保存为 `model_policy.yaml`，运行：

```bash
fermiflow model --input-model ../data/models/target_input.xml --policy ../configs/model_policy.yaml --output-model ../data/models/target_freeing_input.xml
```

若不写 `--output-model`，会自动创建同目录的 `target_input_edited.xml`。也可以完全不另建 YAML，直接在终端设定同一规则：

```bash
fermiflow model --input-model ../data/models/target_input.xml --free-spectral-within 3 --free-norm-until 5 --ts-results ../products_1GeV/target_minuit_results.dat --ts-threshold 1 --background-norm gll_iem_v07 --background-norm iso_P8R3_SOURCE_V3_v1 --source-policy my_target=spectral
```

如希望在拟合前临时调用同一个工具，而不改项目配置，则额外传入独立策略文件：

```bash
fermiflow run --config ../configs/project.yaml --mode like --input-model ../data/models/target_input.xml --model-policy ../configs/model_policy.yaml

fermiflow spatial --config ../configs/spatial.yaml --model-policy ../configs/model_policy.yaml
```

`fermiflow run` 会在原 XML 旁生成 `*_edited.xml`；`fermiflow spatial` 会把副本写入空间拟合输出目录的 `model_inputs/`，然后再开始分析。两者都不修改总 YAML 或原 XML。

## Fermipy 空间分析

```bash
fermiflow spatial --config ../configs/spatial.yaml
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

### 批量生成空间模型组合

当需要系统比较多个源的 Point/Gaussian/Disk 模板，以及可选邻近点源是否存在时，使用独立的空间组合配置。先生成模板：

```bash
fermiflow init-spatial-grid ../configs/spatial_grid.yaml --target my_target --energy-label 1GeV
```

这个 YAML 与单个 `spatial_*.yaml` 分工不同：它不直接运行 Fermipy，而是从一个含全部候选源的基础 XML，生成每个空间假设独立的 XML、单模型空间 YAML、`.sbatch` 文件和 manifest。典型配置如下：

```yaml
base:
  input_model: ../products_1GeV/my_target_1GeV_input.xml
  spatial_template: ../configs/spatial_my_target_1GeV.yaml
  output_root: ../products_1GeV/spatial_grid
  # model_policy: ../configs/modify-model.yaml

sources:
  - name: my_target
    include: [true]
    models: [point, gaussian, disk]
    seed:
      ra: 237.124685
      dec: -53.921295
      r68: 0.33

  - name: extend
    include: [true]
    models: [gaussian, disk]
    seed: from_input_model

  - name: pt
    include: [true, false]
    models: [point]
```

`name` 必须严格对应基础 XML 内的源名。`include: [true]` 表示该源始终保留；`include: [true, false]` 会生成“保留”和“完全移除”两类 XML。被移除的源不会出现在文件名中。

生成器使用完整源名，并以 `point`、`gaussian`、`disk` 表示空间模型。例如：

```text
my_target-gaussian-extend-disk-pt-point
my_target-gaussian-extend-disk
```

第二个组合没有 `pt`，因此不会出现 `pt-absent` 之类的占位名称。包含空格的正式源名在 XML 和 manifest 中保持不变；只在文件路径中把空格替换为连字符。

对任意源，省略 `seed:` 时会沿用基础 XML 的 RA/DEC；指定 `seed.ra` 或 `seed.dec` 时只替换给出的坐标分量。对延展模型，`seed.r68` 是 68% 包含半径（deg）：工具会自动写入 Gaussian 的 \(\sigma=r_{68}/1.5096\) 或 Disk 的 \(R=r_{68}/\sqrt{0.68}\)。若基础 XML 是点源、而该组合要求 Gaussian/Disk，则必须提供 `seed.r68`，因为点源本身没有可继承的延展尺度。

生成组合、模型和任务脚本：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml
```

该命令**不会提交任务**。它会写出：

```text
products_1GeV/spatial_grid/
├── models/<tag>_spatial.xml
├── configs/spatial_<tag>.yaml
├── <tag>/                         # 每个组合的 Fermipy 输出目录
└── spatial_grid_manifest.csv

sbatch/spatial_grid/
├── <tag>.sbatch
└── submit_spatial_grid.sh
```

检查生成的 XML 和 `.sbatch` 后，再手动提交：

```bash
bash ../sbatch/spatial_grid/submit_spatial_grid.sh
```

`spatial_grid_manifest.csv` 保留 tag、每个源实际使用的模型、XML、单模型 YAML、输出目录、region 文件和 sbatch 文件路径。后续比较 likelihood、TS、定位结果和延展半径时，应从该表读取组合信息，而不是依赖文件名猜测模型。

每个自动生成的单组合 YAML 都会将 `sources:` 写成该组合实际需要拟合的源。例如：

```yaml
sources:
  - name: my_target
    spatial_model: PointSource
    localization: {}
  - name: extend
    spatial_model: RadialGaussian
    extension: {}
```

这表示对 `my_target` 执行点源定位（`localize`），对 `extend` 执行 Gaussian 延展拟合（`extension`）；空字典表示继承空间模板 YAML 顶层 `localize:`、`extension:` 中的默认设置。组合生成器会以完整 tag 命名最终 XML 与 DS9 region，例如 `my_target-point-extend-gaussian_spatial_final.xml` 和 `my_target-point-extend-gaussian.reg`，便于将文件移出原目录后仍能辨认其模型组合。

### 以重新定位后的 XML 批量运行 gtlike

空间组合的 raw likelihood 不应直接来自初始坐标的 XML。推荐顺序是：先完成全部 Fermipy spatial 任务，检查定位和延展结果，再将每个组合的 `<tag>_spatial_final.xml` 用作该组合的 gtlike 输入。

在 `spatial_grid.yaml` 中增加：

```yaml
gtlike:
  project_config: ../configs/my_target_1GeV.yaml
  # Optional; defaults to base.input_model.
  template_model: ../products_1GeV/my_target_1GeV_model.xml
  # model_policy: ../configs/modify-model.yaml
  slurm:
    sbatch_dir: ../sbatch/gtlike_grid
    log_dir: ../logs/gtlike_grid

comparison:
  output: ../products_1GeV/spatial_grid/likelihood_comparison.csv
```

`project_config` 是标准 Fermitools 项目 YAML；每个组合必须使用同一份事件筛选、CCUBE、曝光图、livetime cube、IRF 和能段设置。空间任务结束并确认 region 合理后，生成 gtlike 输入和任务：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --prepare-gtlike
```

每个已经存在 `<tag>_spatial_final.xml` 的组合将产生：

```text
<tag>/
├── <tag>_spatial_final.xml
├── <tag>_reloc_input.xml
├── <tag>_reloc_srcmaps.fits       # gtlike 运行后生成
├── <tag>_reloc_drmnfb.xml         # gtlike 运行后生成
├── <tag>_reloc_minuit.xml         # gtlike 运行后生成
└── gtlike.log                     # 每个组合稳定、可复查的日志
```

Fermipy 本身常把 `write_roi()` 的 XML 临时写为 `<tag>_spatial_final_00.xml`；流水线会在空间拟合成功后自动规范化为 `<tag>_spatial_final.xml`。对于已在旧版本流水线完成的任务，`--prepare-gtlike` 也会自动识别最新的 `_00.xml` 文件并记录其实际路径。

`_reloc_input.xml` 始终从 `gtlike.template_model`（未设置时为 `base.input_model`）复制：它保留模板内所有谱参数、背景源、其它邻源及其 `free` 状态。脚本只从对应的 `<tag>_spatial_final.xml` 读取候选源的最佳空间模型、RA、DEC 与延展尺度，并按组合删除缺失源。若设置 `gtlike.model_policy`，会在此基础上额外统一修改自由参数策略；若要让其它内容严格保持模板一致，请不要设置该项。

该步骤只为已完成的 spatial 结果写入 gtlike `.sbatch`，不会自动提交：

```bash
bash ../sbatch/gtlike_grid/submit_gtlike_grid.sh
```

每个任务会针对自己的 `_reloc_input.xml` 重新生成 source maps，再依次运行 DRMNFB 和 MINUIT；不同空间模板之间不能复用同一个 `srcmaps.fits`。

全部或部分 gtlike 任务完成后，运行：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --compare-likelihood
```

比较器只读取 manifest 中记录的 `<tag>/gtlike.log`，并且只纳入包含 `[DONE] gtlike (MINUIT) finished` 的任务。它输出按 \(-\log L\) 排序的表、相对最佳模型的

\[
\Delta TS=2\left[(-\log L)_i-(-\log L)_{\rm best}\right],
\]

并在固定其它所有源假设的前提下，列出每个源切换 Point/Gaussian/Disk 或“存在/不存在”时的比较。对于可选源，存在与缺失的一对模型会给出：

\[
TS_{\rm source}=2\left[(-\log L)_{\rm absent}-(-\log L)_{\rm present}\right].
\]

注意：这一步并不重新定位。若需要比较每种模型的最佳位置，必须重新运行对应的 Fermipy spatial 任务，而不是只修改 gtlike 输入 XML 的坐标。

### 可选：用同一 TS map 检查所有空间结果

空间组合 YAML 可选加入绘图块；不写该块或不设置 `tsmap` 不影响 XML/YAML/sbatch 的正常生成。

```yaml
plot:
  tsmap: ../products_1GeV/my_target_1GeV_tsmap.fits
  radio_contours: ../data/regions/my_target-radio.ctr
  output: ../figures/my_target_spatial_grid.png
  ncols: 4
  cmap: inferno
  power_gamma: 0.5
  vmin: -1.0
  vmax_percentile: 99.99
```

所有子图共用同一色标范围，并在右侧绘制一个统一的 colorbar（默认标为 `TS`）。`power_gamma: 0.5` 是平方根显示拉伸，用于增强较低 TS 结构；如需线性颜色映射，设为 `1.0`。

所有空间任务完成后运行：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --plot
```

绘图器从 manifest 查找已存在的最终 `.reg` 文件，以同一张 TS map 画成子图；可选叠加 `.ctr` 射电等高线。最终 region 图中，延展源的实线圆半径直接取自 `gta.extension()` 的 best-fit extension（即日志的 `Best-fit extension`）；点源的虚线圆是定位误差 `pos_r68`，两者不可作相同的物理解释。

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
bash download.sh ../urls.txt ../rawdata 6
```

这里的 `6` 是同时运行的 wget 数。脚本使用 `wget --continue`，中断后用同一命令可继续下载未完成文件。

## 辅助脚本

- `scripts/fix-sedbin.py`：从 SED 日志读取 TS，固定低显著性背景源并生成 `-mod_input.xml`。
- `scripts/plot_sed.py`：读取 SED 日志和全能段 XML，绘制 (E^2dN/dE)、上限及近似谱误差带。
- `scripts/compute_likelihood.py`：修改文件顶部的 `models` 字典后，计算相对模型的 (2\Delta\log\mathcal{L})。

这三项是可编辑的分析辅助脚本；用于新目标前，请先修改脚本顶部的目标名、输入 XML、日志和输出路径，避免写入其它项目的产品目录。

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
