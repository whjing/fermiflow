# Fermipy 空间分析

[README](../README.md) 给出完整运行顺序；[注意事项](notes.md) 集中说明失败结果、参数计数及输出覆盖。以下命令从项目 `scripts/` 运行。

## 单模型空间拟合

```bash
fermiflow init --mode spatial --config ../configs/spatial_fit.yaml --target my_target --energy-label 1GeV
fermiflow spatial --config ../configs/spatial_fit.yaml
```

空间 YAML 的 `fermipy.data` 设置 GTI、Spacecraft、ltcube；`fermipy.model.catalogs` 指向输入 XML，`fermipy.selection` 设置能段、中心及 MET 起止时间。

```yaml
sources:
  - name: srcT
    spatial_model: PointSource
    localization: {}
  - name: srcE
    spatial_model: RadialGaussian
    extension: {}
```

空字典继承 `fermipy.localize` 或 `fermipy.extension` 默认设置。`outputs.model_name` 设置最终模型名，`outputs.region_file` 设置region文件名；grid运行时由组合tag替换。

## 批量生成空间模型组合

```bash
fermiflow init --mode spatial-grid --config ../configs/grid_1GeV.yaml --target my_target --energy-label 1GeV
```

例如当前项目的4×2×2实验：

```yaml
base:
  input_model: ../products_1GeV/init_spatial.xml
  spatial_template: spatial_fit.yaml
  output_root: ../products_1GeV/spatial_grid
  model_policy: model_policy_spatial.yaml
sources:
  - name: srcT
    include: [true, false]
    models: [point, gaussian, disk]
    seed:
      r68: 0.4
  - name: srcP
    include: [true, false]
    models: [point]
  - name: srcE
    include: [true]
    models: [gaussian, disk]
slurm:
  working_dir: ../scripts
  sbatch_dir: ../products_1GeV/spatial_grid/sbatch
  log_dir: ../products_1GeV/spatial_grid/logs
gtlike:
  project_config: proj_1GeV.yaml
  template_model: ../products_1GeV/init_spatial.xml
  model_policy: model_policy_like.yaml
  slurm:
    sbatch_dir: ../products_1GeV/spatial_grid/sbatch
    log_dir: ../products_1GeV/spatial_grid/logs
comparison:
  reference: srcT-P-srcP-P-srcE-G
```

`include: [true]` 保留源，`[true, false]` 同时测试保留和缺失。tag按列表顺序组合完整源名与P/G/D/N代码，缺失源仍在tag中标为N。

省略seed时继承XML坐标和径向尺度；给出ra、dec只替换对应分量。`seed.r68` 单位度，转换为Gaussian的 \(\sigma=r_{68}/1.5096\) 或Disk的 \(R=r_{68}/\sqrt{0.68}\)。`base.model_policy` 在写入组合XML前应用。

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml
bash ../products_1GeV/spatial_grid/sbatch/submit_spatial.sh
```

输出：

```text
spatial_grid/
├── spatial_grid_manifest.csv
├── <tag>_spatial.xml
├── <tag>_spatial.yaml
├── sbatch/<tag>_spatial.sbatch
├── sbatch/submit_spatial.sh
├── logs/<tag>_spatial.log
└── <tag>/
    ├── <tag>_spatial_final.xml
    └── <tag>.reg
```

manifest记录各组合的模型、源形态、配置、输出和任务路径。提交脚本各任务间隔3秒。

## 以重新定位后的 XML 批量运行 gtlike

空间任务完成后：

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --prepare-gtlike
bash ../products_1GeV/spatial_grid/sbatch/submit_like.sh
```

`_reloc_input.xml` 从 `gtlike.template_model` 复制（默认 `base.input_model`），保留谱参数、背景和free状态，再插入对应 `_spatial_final.xml` 的受检源空间模型、坐标、尺度，并删除N源。`gtlike.model_policy` 覆盖自由参数策略，省略时继承base策略，显式null时保留模板原状态。

每组gtlike重建source maps并运行DRMNFB、MINUIT：

```text
<tag>/<tag>_reloc_input.xml
<tag>/<tag>_reloc_srcmaps.fits
<tag>/<tag>_reloc_drmnfb.xml
<tag>/<tag>_reloc_minuit.xml
logs/<tag>_like.log
sbatch/<tag>_like.sbatch
sbatch/submit_like.sh
```

Fermipy `_spatial_final_00.xml` 会规范化为 `_spatial_final.xml`；旧结果的prepare阶段也兼容编号后缀。

## 全部受检源缺失的对照组合

受检源全部为N时，manifest标记 `spatial_status=skipped_all_absent`。该组合生成删源XML，跳过空间YAML、任务和region；`--prepare-gtlike` 直接从共同模板删去受检源，生成背景对照的 `_reloc_input.xml` 和gtlike任务。固定邻源继续保留。一个受检源的P/G/D/N配置因此产生三个空间任务、四个gtlike任务。

## 固定邻源，只测试目标

从选定组合的 `_reloc_input.xml` 建立下一轮grid：仅将目标列入 `sources`，其他邻源沿用模板的空间信息。空间模板设置 `options.delete_low_ts_sources: false` 可保留完整背景源集合；默认true执行TS<1删源。

这对应项目steps中的fixPE、fixE_noP以及fromD实验：不同实验采用各自的基础XML与output_root，运行命令顺序相同。

## 比较 likelihood 和导出 CSV

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --compare-likelihood --reference srcT-P-srcP-P-srcE-G --csv ../products_1GeV/spatial_grid/results.csv
```

reference优先采用命令行，然后是 `comparison.reference`，未指定时选最小AIC。终端按likelihood排序，输出k、ΔTS、Δk、ΔAIC。`k` 从最终MINUIT XML的free=1计数。

$$
\Delta TS=2(N_{\rm ref}-N_{\rm model}),\qquad
\Delta AIC=2\Delta k-\Delta TS,\quad N=-\ln\mathcal L.
$$

默认 `likelihood_comparison.csv` 保存模型汇总；`--csv` 逐源输出tag、源名、形态、坐标/误差、r68/误差、模型统计量、reference与notes。模型统计量在该组合每个源行重复。浮点数保留两位小数，差值先用原始精度计算。

`ts_minuit`、`ts_summary`、`ts_drmnfb` 分别是各受检源在MINUIT源块、后续summary、DRMNFB源块的最后有效TS；缺失留空。定位/延展失败或越界写入notes，误差读取匹配的Fermipy LOC_DATA/EXT_DATA FITS。

```bash
python -m scripts.csv_to_tex ../products_1GeV/spatial_grid/results.csv ../products_1GeV/spatial_grid/results.tex
```

转换生成九列AASTeX数据行，放入 `\startdata`、`\enddata` 之间，加载multirow；notes保存为TeX注释。旧 `--latex` 接口仍可直接输出数据行。

## 用同一 TS map 检查所有空间结果

```yaml
plot:
  tsmap: ../products_1GeV/tsmap-srcT-srcP.fits
  radio_contours: ../regions/radio.ctr
  output: ../figures/spatial_grid.png
  center: {ra: 238.885, dec: -53.283}
  size: 2.0
  ncols: 4
  cmap: inferno
  power_gamma: 0.5
  vmin: -1.0
  vmax_percentile: 99.99
  position_coordinates: absolute
```

```bash
fermiflow spatial-grid --config ../configs/grid_1GeV.yaml --plot
```

组合图使用共同TS map、统一colorbar和各组region，可叠加射电 `.ctr`。center和size指定视野，两者省略或同时null显示TS map全图。`power_gamma=0.5` 是平方根颜色拉伸，1.0为线性。

region的名称只标在中心：点源用青色十字和黄色虚线定位圆；延展源用青色十字和实线r68圆；失败定位候选用橙色菱形和橙色虚线圆。延展半径读取extension返回的best-fit extension。

## 比较各组合的拟合位置与半径

`--plot` 默认额外生成 `spatial_positions.png` 与 `spatial_positions.csv`。每源一行两幅图：左侧比较坐标，右侧比较输入/最终r68；颜色和编号对应模型，圆/三角/方形对应Point/Gaussian/Disk，橙色叉号表示失败或越界，黑色加号表示输入中心。

默认 `plot.position_coordinates: absolute` 显示RA/Dec（度），RA向左增大；`offset` 显示局部天空偏移（角分），正ΔRA cosDec在左、正ΔDec在上。右侧灰色空心点为输入r68，彩色点为拟合r68，附可用误差棒。

`plot.position_comparison: false` 关闭位置图；`position_output`、`position_csv` 指定路径。未提供tsmap时仍可生成位置图。CSV同时保留绝对坐标和偏移，采用原始精度；位置图独立缩放。

## Grid 固定日志与覆盖

任务日志是 `<tag>_spatial.log`、`<tag>_like.log`，提交脚本分别为 `submit_spatial.sh`、`submit_like.sh`。覆盖和比较读取规则集中在[任务与输出](notes.md#任务与输出)。
