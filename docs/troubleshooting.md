# 检查与排错

- `fermiflow: command not found`：确认已激活安装所用的 Conda 环境，再检查 `python -m pip show fermiflow`。
- `Bundled template not found`：先确认当前已激活用于分析的 Conda 环境，再按[安装与更新](installation.md)重装。模板由仓库根目录的 `templates/` 提供。
- `bin-fit` 缺少 CCUBE 或曝光图：先对同一能段运行 `bin`，核对 `--nbins` 和 `--ibin`。
- likelihood 表缺少某些组合：查 `spatial_grid_manifest.csv`，确认空间拟合已完成，并检查对应的 `gtlike.log` 是否包含 MINUIT 完成标记。
- 重用 livetime cube 前，检查时间覆盖与事件筛选是否匹配。

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
fermitools_project.yaml
model_policy.yaml
myTarget_baseline_input.xml
spatial_grid.yaml
spatial_grid_manifest.csv
<tag>_spatial_final.xml
<tag>_reloc_input.xml
<tag>_reloc_minuit.xml
myTarget_bestspace_{pl,lp}_minuit.xml
myTarget_sed_input.xml
SED bin logs / results / plot
```

这样无论明天重新检查、换一个能段、增加一个邻源，还是让别人复现，你都可以从“共同初始模型 → 空间最优解 → 谱最优解 → SED”完整追溯每一步。
