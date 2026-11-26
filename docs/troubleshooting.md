# 检查与排错

- `fermiflow: command not found`：确认已激活安装所用的 Conda 环境，再检查 `python -m pip show fermiflow`。
- `Bundled template not found`：先确认当前已激活用于分析的 Conda 环境，再按[安装与更新](installation.md)重装。模板由仓库根目录的 `templates/` 提供。
- `bin-fit` 缺少 CCUBE 或曝光图：先对同一能段运行 `bin`，核对 `--nbins` 和 `--ibin`。
- likelihood 表缺少某些组合：查 `spatial_grid_manifest.csv`，确认空间拟合已完成，并检查manifest 指向的 `<tag>_like.log` 是否包含 MINUIT 完成标记。

运行条件、覆盖行为和科学解释集中在[注意事项与限制](notes.md)。

## 最小可复现文件链

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
