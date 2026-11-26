# 数据准备与 TS map

主流程见 [README](../README.md)，路径规则及运行限制集中在[注意事项](notes.md)。下列命令在项目 `scripts/` 执行。

## 下载和配置

从 [FSSC LAT 数据查询](https://fermi.gsfc.nasa.gov/cgi-bin/ssc/LAT/LATDataQuery.cgi) 获取 Photon、Spacecraft 链接，保存为 `../rawdata/urls.txt`：

```bash
fermiflow download ../rawdata/urls.txt ../rawdata 6
fermiflow init --mode project --config ../configs/proj_1GeV.yaml
```

配置目标名、RA/Dec、能段、ROI、像素和目录。公共文件位于 `archive_dir`，常用下载入口：

- [FL16Y XML](https://fermi.gsfc.nasa.gov/ssc/data/access/lat/fl16y/gll_psc_v38.xml)
- [4FGL-DR4 XML](https://fermi.gsfc.nasa.gov/ssc/data/access/lat/14yr_catalog/gll_psc_v32.xml)
- [Galactic diffuse FITS](https://fermi.gsfc.nasa.gov/ssc/data/analysis/software/aux/4fgl/gll_iem_v07.fits)
- [P8R3 SOURCE 各向同性谱](https://fermi.gsfc.nasa.gov/ssc/data/analysis/software/aux/iso_P8R3_SOURCE_V3_v1.txt)

在 `files` 中填写实际下载文件名。

## prepare

```bash
fermiflow run --config ../configs/proj_1GeV.yaml --mode prepare
```

`products_1GeV/` 保存 `<analysis_name>_filtered.fits`、`_gti.fits`、`_cmap.fits`、`_ccube.fits` 和 `_bexpmap.fits`；`shared/` 保存 `<target>_model_16yr.xml` 和 `ROI_<target>_model_16yr_carta.reg`。`files.ltcube` 指定活时立方体路径，已有文件时复用，否则生成。

目录 region：点源用中心十字；径向延展源用中心十字与换算后的 r68 圆；有目录坐标的 SpatialMap 用中心菱形和源名。

## 修改模型文件

```bash
fermiflow init --mode model-policy --config ../configs/model_policy.yaml
fermiflow model --input-model ../shared/my_target_model_16yr.xml --policy ../configs/model_policy.yaml --output-model ../products_1GeV/init_input.xml
```

策略采用 `spectral`、`norm`、`fixed`，详见[模型参数策略](model-policy.md)。

## 初始 gtlike

```bash
fermiflow run --config ../configs/proj_1GeV.yaml --mode like --input-model ../products_1GeV/init_input.xml
```

输出 `init_srcmaps.fits`、`init_drmnfb.xml`、`init_minuit.xml`、`init_minuit_results.dat`。项目源名整理及候选源添加可使用项目自己的脚本完成，再将共同模型用于[空间组合分析](spatial.md)。

## 单张残差 TS map

```bash
fermiflow model --default-policy fixed --input-model ../products_1GeV/init_minuit.xml --output-model ../products_1GeV/init_tsmap-res.xml
fermiflow run --config ../configs/proj_1GeV.yaml --mode tsmap --input-model ../products_1GeV/init_tsmap-res.xml --size 3 --binsz 0.05
```

## 批量 TS map

```bash
fermiflow init --mode tsmap-grid --config ../configs/tsmap_1GeV.yaml --target my_target --energy-label 1GeV
fermiflow tsmap-grid --config ../configs/tsmap_1GeV.yaml --input-model ../products_1GeV/init_minuit.xml
bash ../products_1GeV/sbatch/submit_tsmap.sh
```

配置示例：

```yaml
project_config: proj_1GeV.yaml
slurm:
  working_dir: ../scripts
submit_delay_seconds: 300
defaults:
  size: 3.0
  binsz: 0.05
tasks:
  - remove_sources: []
  - remove_sources: [srcT]
  - remove_sources: [srcP]
  - remove_sources: [srcE]
```

生成器固定全部模型参数，按每项删除完整源节点。任务输出为 `tsmap-res` 或 `tsmap-<源名>`；联合删源用连字符连接。`defaults.size/binsz` 可在各项覆盖。输入 XML 所在目录默认接收 XML/FITS，`sbatch/` 接收任务与 `submit_tsmap.sh`，`logs/` 接收任务日志；`output_dir` 可指定另一个输出位置。每个任务使用1 CPU和 `fermi` 环境。

同一能段的不同空间组合可共用这份 YAML：

```bash
fermiflow tsmap-grid --config ../configs/tsmap_1GeV.yaml --input-model ../products_1GeV/spatial_grid/srcT-P-srcP-N-srcE-G/srcT-P-srcP-N-srcE-G_reloc_minuit.xml
fermiflow tsmap-grid --config ../configs/tsmap_1GeV.yaml --input-model ../products_1GeV/spatial_grid/srcT-D-srcP-N-srcE-G/srcT-D-srcP-N-srcE-G_reloc_minuit.xml
```

任务生成、覆盖和缺失源的处理见[任务与输出](notes.md#任务与输出)。
