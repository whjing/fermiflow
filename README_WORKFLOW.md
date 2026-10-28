# Fermi-LAT 分析流程手册

这是一份按实际分析顺序组织的工作手册，适合从一个新目标开始完成 Fermi-LAT 的空间分析、全能段谱拟合和 SED。它是对 [README.md](README.md) 命令参考的补充，**不会替代或覆盖原 README**。

本文中的命令假设当前目录是项目的 `scripts/`：

```text
my_project/
├── configs/                 # 项目 YAML 与自由参数策略
├── data/                    # 可复用的本项目 livetime cube、XML、region 等
├── rawdata/                 # Photon 与 spacecraft FITS
├── products_1GeV/           # 由 Fermitools/Fermipy 生成的产品
├── logs/
└── scripts/                 # 在这里运行 fermiflow
```

所有距离以角度（deg）表示；能量以 MeV 表示，除非另有说明。

---

## 0. 开始前：建立配置与确定分析问题

先建立项目配置。模板不会覆盖已有文件：

```bash
fermiflow init ../configs/project.yaml
fermiflow init-model-policy ../configs/model_policy.yaml
fermiflow init-spatial ../configs/spatial.yaml --target my_target --energy-label 1GeV
fermiflow init-spatial-grid ../configs/spatial_grid.yaml --target my_target --energy-label 1GeV
```

首先编辑 `project.yaml` 中的：

- `analysis.target`：简短项目名；
- `analysis.ra`、`analysis.dec`：ROI 中心；
- `analysis.emin`、`analysis.emax`：主分析能段；
- `analysis.roi_radius`、`mapsize_deg`、`binsz`；
- `paths`：共享背景文件与项目数据目录；
- `files.ltcube`：建议保留 `{project_data_dir}/{target}_ltcube.fits`，可在同一项目复用。

在开始处理前，明确三件事：研究能段、ROI 中心、以及你希望比较的空间假设（目标是点源、Gaussian、Disk；是否包含邻近候选源）。空间模型、谱型与背景自由度必须在同一轮比较中保持可追溯。

---

## 1. 下载 LAT 数据和公共模型

在 FSSC Data Portal 根据 ROI 中心、时间范围、能段和下载半径取得 Photon 与 Spacecraft 文件链接。下载半径通常要覆盖事件筛选半径并留出 PSF 余量；不要只按可见射电壳的大小下载。

将下载页提供的 URL（或整段 `wget ... URL` 文本）保存为 `../rawdata/urls.txt`，然后并行下载：

```bash
fermiflow download ../rawdata/urls.txt ../rawdata 6
```

确认 `rawdata/` 至少包含一个或多个 `*_PH*.fits` 和一个 `*_SC*.fits`。同时在 `~/data/fermi/`（或 `project.yaml` 的 `common_data_dir`）准备：

- 4FGL/FL16Y catalogue XML；
- Galactic diffuse model，例如 `gll_iem_v07.fits`；
- isotropic diffuse spectrum，例如 `iso_P8R3_SOURCE_V3_v1.txt`。

这些公共背景文件可跨项目共享；项目特有的 livetime cube、模型 XML 和 region 文件应放在 `data/`。

---

## 2. 建立全能段数据产品和目录初始模型

运行一次 `prepare`：

```bash
fermiflow run --config ../configs/project.yaml --mode prepare
```

它依次建立事件筛选、GTI、livetime cube（若配置文件没有提供已有文件）、CMAP、CCUBE、binned exposure map 和 catalogue 初始 XML。典型输出为：

```text
products_1GeV/
├── my_target_1GeV_filtered.fits
├── my_target_1GeV_gti.fits
├── my_target_1GeV_cmap.fits
├── my_target_1GeV_ccube.fits
├── my_target_1GeV_bexpmap.fits
└── my_target_1GeV_input.xml

data/
└── my_target_ltcube.fits
```

初始 XML 是**目录模型**，不是最终科学模型。它包含 catalogue 源和 diffuse backgrounds，适合作为空间组合的共同起点。

### 目录 region 文件

生成 XML 时，流水线会额外写出一个 CARTA 可直接读入的 `.reg` 文件。它从 XML 的 `spatialModel` 读取信息：

- `SkyDirFunction` 点源：中心十字；
- `RadialGaussian`：中心十字与 $r_{68}=1.5096\sigma$ 圆；
- `RadialDisk`：中心十字与 $r_{68}=\sqrt{0.68}R$ 圆；
- Galactic/isotropic diffuse 与 `SpatialMap` 等没有圆对称尺度的源：跳过，不强行画成圆。

这份 region 适合检查 catalogue 初始模型，不能替代后续重新定位得到的空间结果。

---

## 3. 在正式拟合前设定“谁可以变化”

不要直接修改唯一的 catalogue XML。用 `fermiflow model` 复制并写出一个具有明确自由度策略的新 XML：

```bash
fermiflow model \
  --input-model ../products_1GeV/my_target_1GeV_input.xml \
  --policy ../configs/model_policy.yaml \
  --output-model ../data/models/my_target_baseline_input.xml
```

`model_policy.yaml` 的三个无歧义策略为：

| 策略 | 允许变化的参数 | 保持固定的参数 |
| --- | --- | --- |
| `spectral` | 谱归一化与拟合谱形，例如 `Prefactor/norm`、`Index/alpha/beta` | `Scale`、`Eb`、RA/DEC、空间半径 |
| `norm` | 仅谱归一化 | 谱形、参考能量、全部空间参数 |
| `fixed` | 无 | 所有参数 |

通常的基准策略是：

```yaml
radial:
  zones:
    - {max_radius: 3.0, policy: spectral}
    - {max_radius: 5.0, policy: norm}
  outside_policy: fixed
background_norms: [gll_iem_v07, iso_P8R3_SOURCE_V3_v1]
sources:
  my_target: spectral
```

含义是：目标源和近处显著邻源可重拟合谱；较远源只改变归一化；更远源固定；银河与各向同性背景只改变归一化。这样既保留足够的背景弹性，也避免大量低显著性源造成不稳定拟合。

如果已有一次 `gtlike` 的 `*_results.dat`，可加入 `ts_filter`，按低 TS 源的专用半径策略减少自由度。例如，下面规则只对 \(TS<25\) 的源生效：中心 5° 内只放开归一化，5° 外固定；高 TS 源仍使用上面的主 `radial` 分区。

```yaml
ts_filter:
  results_file: ../products_1GeV/my_target_baseline_minuit_results.dat
  threshold: 25.0
  radial:
    zones:
      - {max_radius: 5.0, policy: norm}
    outside_policy: fixed
  policy: fixed
```

若主 `radial` 已定义 `center`，`ts_filter.radial` 自动继承该中心；也可在其内部单独指定 `center`。目标源和两个 diffuse backgrounds 应通过 `sources:` 与 `background_norms:` 显式保护，避免低 TS 筛选将其固定。

---

## 4. 基准全能段似然拟合与残差检查

用上一步的 baseline XML 进行一次全能段拟合：

```bash
fermiflow run --config ../configs/project.yaml --mode like \
  --input-model ../data/models/my_target_baseline_input.xml
```

每次 `like` 都重新生成与该 XML 对应的 source maps，然后运行 DRMNFB 与 MINUIT。常见产品为：

```text
my_target_baseline_srcmaps.fits
my_target_baseline_drmnfb.xml
my_target_baseline_minuit.xml
my_target_baseline_minuit_results.dat
```

用收敛后的 `*_minuit.xml`，复制一份_tsmap.xml,固定全部参数 生成 TS map，检查是否有未建模残差或候选邻源：

```bash
fermiflow run --config ../configs/project.yaml --mode tsmap \
  --input-model ../data/models/my_target_baseline_minuit.xml \
  --size 5 --binsz 0.05
```

若 TS map 显示稳定的新残差，应先把该候选源加入共同的模型模板，再开始空间模型之间的正式比较。不要让不同候选空间组合使用不同的背景源清单。

---

## 5. 空间模板：先 Fermipy，后 gtlike

空间结论应该遵循：**每种空间假设独立定位/延展拟合 → 将最佳空间参数交给 gtlike → 比较同一数据下的 likelihood**。只把一个点源挪到 Gaussian 中心，而不重新拟合点源位置，不能作为点源与延展源的公平比较。

### 5.1 单一空间假设的快速测试

编辑 `spatial.yaml`：

- `fermipy.data.evfile` 指向步骤 2 的 `*_gti.fits`；
- `fermipy.data.ltcube` 指向项目 `data/` 中的 livetime cube；
- `fermipy.model.catalogs` 指向准备做空间拟合的 XML；
- `sources:` 中的源名必须与 XML 完全一致；
- 点源用 `PointSource + localization`；延展源用 `RadialGaussian` 或 `RadialDisk + extension`。

运行：

```bash
fermiflow spatial --config ../configs/spatial.yaml \
  --model-policy ../configs/model_policy.yaml
```

在 `extension` 与 `localize` 设置中，通常应让 `fix_shape: true`。这表示空间扫描过程中保持**被测源的谱形参数**（Index、alpha、beta 等）固定，避免空间尺度与谱形在同一次扫描中相互吸收；其归一化仍可由 Fermipy 的拟合流程重新优化。其它源可否变化，由输入 XML 的 `free` 状态和 `model_policy` 共同决定。

### 5.2 系统比较多个空间组合

当目标和邻近候选源都可能改变空间模型时，优先使用 spatial grid。以同一份“包含所有候选源”的 XML 为基础：

```yaml
base:
  input_model: ../data/models/my_target_baseline_input.xml
  spatial_template: ../configs/spatial.yaml
  output_root: ../products_1GeV/spatial_grid

sources:
  - name: my_target
    include: [true]
    models: [point, gaussian, disk]
    seed:
      r68: 0.3
  - name: nearby_candidate
    include: [true, false]
    models: [point]
```

执行：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml
bash ../sbatch/spatial_grid/submit_spatial_grid.sh
```

这里生成的 `<tag>_spatial.xml` 是每个组合的 **Fermipy 输入模型**。它只负责指定该组合使用 Point/Gaussian/Disk、可选源是否存在、以及可选的 seed 坐标/尺度；还不是最佳空间结果。

每个 Fermipy 作业完成后，关键产物是：

```text
products_1GeV/spatial_grid/<tag>/
├── <tag>_spatial_final.xml    # 已定位/延展拟合的结果
└── <tag>.reg                  # 供 CARTA/DS9 检查的结果 region
```

对于该结果 region：延展源圆是 extension 拟合得到的 best-fit extension；点源虚线圆是定位不确定度 `pos_r68`。二者含义不同，不应直接把它们的半径比较为“谁更大”。

---
绘制
```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --plot
```

## 6. 将重新定位结果转入 gtlike，并比较空间模型

先目视检查步骤 5 输出的 region 和拟合是否合理，再生成 gtlike 作业：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --prepare-gtlike
bash ../sbatch/gtlike_ grid/submit_gtlike_grid.sh
```

这里最关键的模板传递规则是：

| 文件 | 来自哪里 | 用途 |
| --- | --- | --- |
| `<tag>_spatial.xml` | spatial grid 由共同 base XML 生成 | Fermipy 的某个空间假设输入 |
| `<tag>_spatial_final.xml` | Fermipy `localize/extension` 输出 | 提供最佳 RA、DEC、空间模型和尺度 |
| `gtlike.template_model` | 共同的 baseline XML；未设置时为 `base.input_model` | 保留所有谱参数、背景源、其它邻源和其 `free` 状态 |
| `<tag>_reloc_input.xml` | 流水线由 template model 复制，并插入空间结果 | 每个组合的 gtlike 输入 |
| `<tag>_reloc_minuit.xml` | gtlike 最终输出 | 空间比较后该组合的全能段拟合模型 |

因此，不要直接把 `<tag>_spatial_final.xml` 当作 gtlike 的模板。正确做法是让它只提供**空间参数**，而让 `template_model` 统一提供谱和背景自由度。这样所有组合在相同背景和自由参数约定下比较。

若要把模型自由度进一步统一，可在 `spatial_grid.yaml` 的 `gtlike.model_policy` 指向一个专用策略。注意：这会再次改变 `<tag>_reloc_input.xml` 的 `free` 状态；用于空间模型间 comparison 时，所有 tag 必须使用同一策略。

汇总已完成结果：

```bash
fermiflow spatial-grid --config ../configs/spatial_grid.yaml --compare-likelihood
```

比较量为：

$$
\Delta TS_i = 2\left[(-\log L)_i - (-\log L)_{\rm best}\right].
$$

数值越小的 $-\log L$ 对应越好的拟合。对于“有/无某个可选源”的一对嵌套模型：

$$
TS_{\rm source}=2\left[(-\log L)_{\rm absent}-(-\log L)_{\rm present}\right].
$$

只有在模型严格嵌套、其它设置一致且没有参数压在边界时，才适合把该 TS 直接按常见显著性近似解释。Gaussian 与 Disk 等非嵌套模板更适合作 likelihood/AIC 等模型选择比较，而不是简单当作一个自由度的 TS。

---

## 7. 确定空间模型后，进行全能段谱型比较

选定最佳、或物理上需要保留的空间描述后，以它对应的 `<tag>_reloc_minuit.xml` 为起点分别建立 PowerLaw 和 LogParabola 模型。两次谱型拟合必须：

1. 使用同一个最佳空间模型、RA/DEC 和延展尺度；
2. 使用同一事件、能段、IRF、CCUBE、曝光图和背景源；
3. 允许目标源的谱参数拟合；
4. 对相同邻源使用相同的自由参数策略。

谱型定义为：

$$
\frac{dN}{dE}=N_0\left(\frac{E}{E_0}\right)^{-\Gamma}
\qquad \text{(PowerLaw)},
$$

$$
\frac{dN}{dE}=N_0\left(\frac{E}{E_b}\right)^{-\left[\alpha+\beta\log(E/E_b)\right]}
\qquad \text{(LogParabola)}.
$$

先复制全能段最佳空间模型，分别把目标源写成 PL 与 LP；不要在两个谱型文件中改变空间参数或其它源的清单。然后各自运行：

```bash
fermiflow run --config ../configs/project.yaml --mode like \
  --input-model ../data/models/my_target_bestspace_pl_input.xml

fermiflow run --config ../configs/project.yaml --mode like \
  --input-model ../data/models/my_target_bestspace_lp_input.xml
```

若 LP 比 PL 多一个自由参数，可报告：

$$
TS_{\rm curve}=2\left[(-\log L)_{\rm PL}-(-\log L)_{\rm LP}\right].
$$

但低显著性源、背景残差和不稳定高能 bin 都可能制造表观曲率，因此还必须检查下一步的 SED；不能只凭一个全能段 $TS_{\rm curve}$ 下物理解读。

---

## 8. SED：固定空间，逐能段测量归一化

### 8.1 选择正确的 SED 输入模板

SED 的起点应是步骤 7 的**最佳全能段谱拟合结果**，通常是：

```text
my_target_bestspace_pl_minuit.xml
```

或在谱曲率显著时使用 LP 结果。把它复制到项目 `data/models/`，例如：

```text
data/models/my_target_sed_input.xml
```

并在 `project.yaml` 中设置：

```yaml
files:
  base_gti: "{products_dir}/{analysis_name}_gti.fits"
  sed_model: "{project_data_dir}/models/my_target_sed_input.xml"
```

### 8.2 每个 SED bin 应固定与放开的参数

SED 点的目的不是在窄能段重新测量完整谱形或空间形状，而是在固定模板下测量强度。因此每个能段中应遵守：

| 参数类别 | 建议 |
| --- | --- |
| 目标源 RA/DEC、Gaussian $\sigma$ 或 Disk $R$ | 固定为步骤 5/6 的最佳空间值 |
| 目标源 Index、alpha、beta、Scale、Eb | 固定为全能段最佳谱的值 |
| 目标源归一化 | 放开 |
| 邻源空间参数 | 固定 |
| 邻源谱形 | 固定 |
| 近处且在该 bin 有贡献的邻源归一化 | 可放开，但所有 bin 用同一套规则 |
| Galactic / isotropic 归一化 | 常见做法是放开；所有 bin 保持一致 |
| 低 TS 背景源 | 初次结果后可固定，并重新运行该 bin |

换言之，SED 最理想的自由参数数量很少：目标源归一化、两个 diffuse normalizations，以及少量非常近/非常亮邻源的归一化。不要在每个 bin 再放开 `Index` 或 `alpha/beta`，否则得到的点不再是对同一个全能段谱模型的独立检验。

首次生成第 $i$ 个对数等宽 bin：

```bash
fermiflow run --config ../configs/project.yaml --mode bin --nbins 6 --ibin 1
```

其它 bin 改变 `--ibin` 即可。建议先以 5--6 个 bin 开始；如果多数 bin 拟合失败或 TS 很低，优先减少 bin 数而不是强行解释噪声点。

若先前一个 bin 中低 TS 源过多，可用该 bin 的结果固定背景源，随后只重跑该 bin：

```bash
fermiflow run --config ../configs/project.yaml --mode bin-fit \
  --nbins 6 --ibin 4 \
  --input-model /absolute/path/my_target_sed_bin04-mod_input.xml
```

`bin-fit` 会复用已经生成的 bin CCUBE/曝光图，但重新生成 source maps 并完成两次 gtlike；修改空间模板、源清单或任意 XML 后不能复用旧 source maps。

### 8.3 绘制与解释 SED

SED 的纵轴通常是：

$$
E^2\frac{dN}{dE}
\quad [\mathrm{erg\ cm^{-2}\ s^{-1}}],
$$

其中微分光子通量（differential photon flux）为 $dN/dE$，单位通常为 $\mathrm{ph\ cm^{-2}\ s^{-1}\ MeV^{-1}}$。全能段积分 photon flux 与 energy flux 不能直接当作一个 SED 点。

当某 bin 的 TS 低（常用阈值是 4 或 5）、通量非正或通量误差大于通量时，应报告 95% 上限，而不是对称误差条。SED 应同时叠加步骤 7 的 PL/LP 全能段曲线；若要画 butterfly，必须使用拟合协方差矩阵或 profile likelihood，而不是只独立传播单个参数误差。

---

## 9. 每次结果检查清单

在写结论前逐项检查：

1. 所有比较是否使用同一事件范围、IRF、能段与背景源清单？
2. 每个空间组合是否独立运行了 `localize` 或 `extension`？
3. 比较 gtlike likelihood 的输入是否是相应的 `<tag>_reloc_input.xml`？
4. 目标与候选源的空间参数是否在 SED 中固定为最终值？
5. PL 与 LP 是否仅改变了目标源谱型，而没有悄悄改变背景自由度？
6. 低 TS SED 点是否显示为上限？
7. 任何关于“延展”“曲率”“强子/轻子”的说法，是否经过空间稳定性、SED 和多波段形态的一致性检查？

---

## 10. 最小可复现文件链

建议为每一次正式分析保留下面这条链，而不要只保留最终图：

```text
project.yaml
model_policy.yaml
my_target_baseline_input.xml
spatial_grid.yaml
spatial_grid_manifest.csv
<tag>_spatial_final.xml
<tag>_reloc_input.xml
<tag>_reloc_minuit.xml
my_target_bestspace_{pl,lp}_minuit.xml
my_target_sed_input.xml
SED bin logs / results / plot
```

这样无论明天重新检查、换一个能段、增加一个邻源，还是让别人复现，你都可以从“共同初始模型 → 空间最优解 → 谱最优解 → SED”完整追溯每一步。
