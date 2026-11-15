# 全能段谱拟合与 SED

## 确定空间模型后，进行全能段谱型比较

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
fermiflow run --config ../configs/fermitools_project.yaml --mode like \
  --input-model ../shared/models/myTarget_bestspace_pl_input.xml

fermiflow run --config ../configs/fermitools_project.yaml --mode like \
  --input-model ../shared/models/myTarget_bestspace_lp_input.xml
```

若 LP 比 PL 多一个自由参数，可报告：

$$
TS_{\rm curve}=2\left[(-\log L)_{\rm PL}-(-\log L)_{\rm LP}\right].
$$

但低显著性源、背景残差和不稳定高能 bin 都可能制造表观曲率，因此还必须检查下一步的 SED；不能只凭一个全能段 $TS_{\rm curve}$ 下物理解读。

---

## SED：固定空间，逐能段测量归一化

### 选择正确的 SED 输入模板

SED 的起点应是上文的**最佳全能段谱拟合结果**，通常是：

```text
myTarget_bestspace_pl_minuit.xml
```

或在谱曲率显著时使用 LP 结果。把它复制到项目 `data/models/`，例如：

```text
shared/models/myTarget_sed_input.xml
```

并在 `fermitools_project.yaml` 中设置：

```yaml
files:
  base_gti: "{products_dir}/{analysis_name}_gti.fits"
  sed_model: "{shared_dir}/models/myTarget_sed_input.xml"
```

### 每个 SED bin 应固定与放开的参数

SED 点的目的不是在窄能段重新测量完整谱形或空间形状，而是在固定模板下测量强度。因此每个能段中应遵守：

| 参数类别 | 建议 |
| --- | --- |
| 目标源 RA/DEC、Gaussian $\sigma$ 或 Disk $R$ | 固定为[空间拟合](spatial.md)的最佳空间值 |
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
fermiflow run --config ../configs/fermitools_project.yaml --mode bin --nbins 6 --ibin 1
```

其它 bin 改变 `--ibin` 即可。建议先以 5--6 个 bin 开始；如果多数 bin 拟合失败或 TS 很低，优先减少 bin 数而不是强行解释噪声点。

若先前一个 bin 中低 TS 源过多，可用该 bin 的结果固定背景源，随后只重跑该 bin：

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode bin-fit \
  --nbins 6 --ibin 4 \
  --input-model /absolute/path/myTarget_sed_bin04-mod_input.xml
```

`bin-fit` 会复用已经生成的 bin CCUBE/曝光图，但重新生成 source maps 并完成两次 gtlike；修改空间模板、源清单或任意 XML 后不能复用旧 source maps。

### 绘制与解释 SED

SED 的纵轴通常是：

$$
E^2\frac{dN}{dE}
\quad [\mathrm{erg\ cm^{-2}\ s^{-1}}],
$$

其中微分光子通量（differential photon flux）为 $dN/dE$，单位通常为 $\mathrm{ph\ cm^{-2}\ s^{-1}\ MeV^{-1}}$。全能段积分 photon flux 与 energy flux 不能直接当作一个 SED 点。

当某 bin 的 TS 低（常用阈值是 4 或 5）、通量非正或通量误差大于通量时，可按分析规则报告实际算出的 95% 上限。缺少正式上限时应标记或跳过该点。SED 应同时叠加上文的 PL/LP 全能段曲线；若要画 butterfly，必须使用拟合协方差矩阵或 profile likelihood，而不是只独立传播单个参数误差。

---


## 按 TS 筛选并重跑

先完成每个 bin 的第一轮拟合，获得对应的 `*_minuit_results.dat`。随后创建配置：

```bash
fermiflow init --mode sed-filter --config ../configs/sed_filter.yaml
```

在 `jobs:` 中**手动**写入每一组 `ibin`、`input_model` 和 `results_file`。同一项中的 XML 与 results 文件必须来自同一个能段；工具不会自动扫描或猜测配对关系。运行：

```bash
fermiflow sed-filter --config ../configs/sed_filter.yaml
```

它会对 TS 小于 `ts_threshold` 的源固定参数，生成 `*-tsltX_input.xml`。指定在 `keep_normalization_sources` 中的源即使 TS 较低，也只固定谱形和空间参数，保留其归一化参数原有的 free/fixed 状态。每个新 XML 都会打印修改前后的自由参数总数。

确认新 XML 后，使用同一份 YAML 生成每个 `bin-fit` 的 `.sbatch` 文件与总提交脚本：

```bash
fermiflow sed-submit --config ../configs/sed_filter.yaml
```

`sed-submit` 只生成脚本，不会自动提交任务。检查后运行：

```bash
bash ../sbatch/sed_6bin_tslt2/submit_sed_filter.sh
```

该脚本在每两个 Slurm 任务之间固定等待 3 秒；这是内置行为，无需也不能通过 YAML 设置。

## 辅助脚本

- `scripts/filter_sed_from_logs.py`：从 SED 日志读取 TS，固定低显著性背景源并生成 `-mod_input.xml`。
- `scripts/plot_sed.py`：读取 SED 日志和全能段 XML，绘制 (E^2dN/dE)、上限及近似谱误差带。
- `scripts/compare_likelihood.py`：修改文件顶部的 `models` 字典后，计算相对模型的 (2\Delta\log\mathcal{L})。

这三项是可编辑的分析辅助脚本；用于新目标前，请先修改脚本顶部的目标名、输入 XML、日志和输出路径，避免写入其它项目的产品目录。
