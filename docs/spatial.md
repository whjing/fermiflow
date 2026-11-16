# Fermipy 空间分析
## 生成空间模型模板

```bash
fermiflow init --mode spatial --config ../configs/spatial_fit.yaml --target my_target --energy-label 1GeV
```
将 `fermipy.data.evfile` 指向 `prepare` 生成的 GTI，将 `fermipy.data.ltcube` 指向已有 livetime cube，并核对 `fermipy.model.catalogs` 和 `sources` 的源名。


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
运行
```bash
fermiflow spatial --config ../configs/spatial_fit.yaml
```

该流程写出最终 ROI XML 与 CARTA-compatible region。由 `prepare` 自动生成的 catalogue region 也会直接从输出 XML 读取空间模型：点源画中心十字，`RadialGaussian` 与 `RadialDisk` 画中心十字和换算后的 \(r_{68}\) 圆。银河/各向同性背景及没有圆对称参数的空间模板不会被伪装成圆形 region。正式报告 `TS_ext` 时，点源与延展模型应各自独立定位并重新优化背景，不能把点源中心固定到延展模型中心后直接作显著性结论。

### 批量生成空间模型组合

当需要系统比较多个源的 Point/Gaussian/Disk 模板，以及可选邻近点源是否存在时，使用独立的空间组合配置。先生成模板：

```bash
fermiflow init --mode spatial-grid --config ../configs/spatial_grid.yaml --target my_target --energy-label 1GeV
```

这个 YAML 与单个 `spatial_*.yaml` 分工不同：它不直接运行 Fermipy，而是从一个含全部候选源的基础 XML，生成每个空间假设独立的 XML、单模型空间 YAML、`.sbatch` 文件和 manifest。典型配置如下：

```yaml
base:
  input_model: ../shared/my_target_model_16yr.xml
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
  radio_contours: ../shared/regions/my_target-radio.ctr
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


比较模型时保留相同的数据选择与背景策略。`--compare-likelihood` 给出拟合差值，显著性解读还取决于模型是否嵌套以及检验的自由度。
