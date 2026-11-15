# 独立修改模型的自由参数

`scripts/edit_model.py` 不依赖 Fermitools 或 Fermipy；它只读取一个 XML、按策略写出一个新的 XML。原输入模型保持不变。它支持三种策略：

- `spectral`：放开归一化和谱形参数，如 `Prefactor`/`norm`、`Index`、`alpha`、`beta`；`Eb`、`Scale` 和全部空间参数固定；
- `norm`：只放开谱归一化参数，其余谱参数与空间参数固定；
- `fixed`：该源所有参数固定。

例如，把下面内容单独保存为 `../configs/model_policy.yaml`。它不属于项目总 YAML。该例会将目标中心 3° 以内的源放开谱归一化和谱形，3°--5° 的源只放开归一化，5° 外固定，同时使 Galactic 与 isotropic 背景只放开归一化：

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

如果只想放开目标源的谱归一化与谱形参数，以及银河/各向同性背景的归一化，而固定其它全部源，则用更短的版本：

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
fermiflow model --input-model ../shared/models/target_input.xml --policy ../configs/model_policy.yaml --output-model ../shared/models/target_freeing_input.xml
```

若不写 `--output-model`，会自动创建同目录的 `target_input_edited.xml`。也可以完全不另建 YAML，直接在终端设定同一规则：

```bash
fermiflow model --input-model ../shared/models/target_input.xml --free-spectral-within 3 --free-norm-until 5 --ts-results ../products_1GeV/target_minuit_results.dat --ts-threshold 1 --background-norm gll_iem_v07 --background-norm iso_P8R3_SOURCE_V3_v1 --source-policy my_target=spectral
```

如希望在拟合前临时调用同一个工具，而不改项目配置，则额外传入独立策略文件：

```bash
fermiflow run --config ../configs/fermitools_project.yaml --mode like --input-model ../shared/models/target_input.xml --model-policy ../configs/model_policy.yaml

fermiflow spatial --config ../configs/spatial_fit.yaml --model-policy ../configs/model_policy.yaml
```

`fermiflow run` 会在原 XML 旁生成 `*_edited.xml`；`fermiflow spatial` 会把副本写入空间拟合输出目录的 `model_inputs/`，然后再开始分析。两者都不修改总 YAML 或原 XML。
