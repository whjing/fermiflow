# 全能段谱拟合与 SED

流程为：选定空间模型 → 100 MeV–500 GeV 全能段谱型比较 → 逐能段拟合 → TS 筛选与重拟合。运行和统计解释的限制集中在[注意事项](notes.md)。

## 多源谱型组合测试（spectral-grid）

```bash
fermiflow init --mode spectral-grid --config ../configs/spectral_100MeV.yaml
```

编辑配置：

```yaml
base:
  input_model: ../products_1GeV/spatial_grid/srcT-P-srcP-P-srcE-G/srcT-P-srcP-P-srcE-G_reloc_minuit.xml
  project_config: proj_100MeV.yaml
  output_root: ../products_100MeV/spectral_grid
  # model_policy: model_policy_spectral.yaml
sources:
  - name: srcT
    models: [pl, lp]
  # - name: srcP
  #   models: [pl, lp]
slurm:
  working_dir: ../scripts
comparison:
  reference: srcT-PL
```

`sources` 每个源列出测试谱型，工具生成笛卡尔积：一个源两组、两个源四组、三个源八组；`models: [pl]` 表示该源只取一种谱型。支持 `pl/powerlaw` 和 `lp/logparabola`。

```bash
fermiflow spectral-grid --config ../configs/spectral_100MeV.yaml
bash ../products_100MeV/spectral_grid/sbatch/submit_like.sh
# 任务完成后
fermiflow spectral-grid --config ../configs/spectral_100MeV.yaml --compare-likelihood --reference srcT-PL
```

多源时 reference 使用完整 tag，例如 `srcT-PL-srcP-PL`。命令行 reference 优先于 YAML；未指定时选最小 AIC。

```text
spectral_grid/
├── spectral_grid_manifest.csv
├── spectral_comparison.csv       # 比较阶段生成
├── spectral_curvature.csv        # 有完成的PL/LP配对时生成
├── sbatch/submit_like.sh
├── logs/<tag>_like.log
└── <tag>/
    ├── <tag>_input.xml
    ├── <tag>_srcmaps.fits
    ├── <tag>_drmnfb.xml
    └── <tag>_minuit.xml
```

转换保持参考能量处的通量和局部斜率，LP的 beta 从0开始；Scale/Eb 和全部空间参数固定。未受检源沿用模板的谱参数和自由状态；`base.model_policy` 可统一调整自由参数。每个任务使用1 CPU、`fermi` 环境，提交间隔3秒。

PL 与 LP 的定义为：

$$
\frac{dN}{dE}=N_0(E/E_0)^{-\Gamma},
\qquad
\frac{dN}{dE}=N_0(E/E_b)^{-\alpha-\beta\ln(E/E_b)}.
$$

`spectral_comparison.csv` 包含 likelihood、k、ΔTS、Δk、ΔAIC、reference 和 notes。`--csv` 改变该表的输出路径。`spectral_curvature.csv` 在其他源谱型相同的条件下，逐源配对 PL 与 LP，输出 `ts_curve`、Δk和ΔAIC。

## 分能段 SED

将选定全能段谱拟合结果复制为 `shared/my_target_sed_input.xml`，在100MeV项目配置中设置：

```yaml
files:
  base_gti: "{products_dir}/{analysis_name}_gti.fits"
  sed_model: "{shared_dir}/my_target_sed_input.xml"
summary:
  sources: [srcT, srcP, srcE]
```

每个 bin 使用固定空间参数及全能段谱形，测量归一化。首次生成并拟合：

```bash
fermiflow run --config ../configs/proj_100MeV.yaml --mode bin --nbins 6 --ibin 1
```

`ibin` 从1到6分别执行，输出按能段放在 `products_100MeV/bin_*/`。源摘要由 `summary.sources` 控制，包含TS、photon flux、energy flux和谱参数。

## 按 TS 筛选并重跑

```bash
fermiflow init --mode sed-filter --config ../configs/sed_filter.yaml
```

在 `jobs` 中手动配对 `ibin`、原输入 XML 与该 bin 的 `*_minuit_results.dat`，设置 `ts_threshold`。`keep_normalization_sources` 指定保留归一化原有自由状态的源。

```bash
fermiflow sed-filter --config ../configs/sed_filter.yaml
fermiflow sed-submit --config ../configs/sed_filter.yaml
bash ../sbatch/sed_6bin_tslt2/submit_sed_filter.sh
```

筛选后生成 `*-tsltX_input.xml` 并打印自由参数修改前后数量。重拟合任务通过 `bin-fit` 使用新 XML，提交间隔3秒。单个 bin 也可直接运行：

```bash
fermiflow run --config ../configs/proj_100MeV.yaml --mode bin-fit --nbins 6 --ibin 4 --input-model ../products_100MeV/bin_04_.../my_target_sed_6bin04-tslt2_input.xml
```

## 绘图辅助脚本

- `scripts/plot_sed.py`：日志数据点、上限、全能段曲线和近似误差带。
- `scripts/filter_sed_from_logs.py`：读取日志筛选低TS源的分析辅助脚本。
- `scripts/compare_likelihood.py`：指定模型数值，计算相对likelihood差异。

辅助脚本的输入、源名与输出路径在脚本中填写。SED 纵轴通常为 \(E^2dN/dE\)，单位 \(\mathrm{erg\,cm^{-2}\,s^{-1}}\)。
