# 注意事项与限制

本文件集中保存主流程中的前置条件、覆盖行为、失败结果和统计解释。命令步骤见[README](../README.md)，错误排查见[排错文档](troubleshooting.md)。这些说明描述当前实现与分析条件，不增加审批步骤。

## 安装与版本

- 操作前激活安装fermiflow的环境。本地机器和超算各自拥有自己的环境。
- 普通安装不会跟随GitHub自动更新。版本号未变时使用 `--force-reinstall --no-deps` 重装；`--no-deps` 适用于运行依赖已经齐备的环境。
- `--no-build-isolation` 仅在希望使用当前环境构建工具时添加，当前环境需已有setuptools；一般安装可省略。
- `--version` 显示安装包版本和来源commit；本地未提交变更不由该commit完整描述。无来源信息时显示unknown。
- `download` 使用Bash的mapfile和GNU风格xargs；使用仓库环境中的Bash工具运行，系统旧版Bash可能不支持。

## 路径与输入

- README命令从分析项目的scripts目录运行。CLI相对路径和Fermitools项目YAML中的路径相对工作目录；spatial、spatial-grid、tsmap-grid、spectral-grid及sed-filter配置中的文件路径相对各自YAML。其中引用的项目YAML仍遵循自己的工作目录规则。
- `--input-model` 每次接收一个明确的XML文件。`srcT-*/*xml` 会展开成多个输入，也可能混入中间模型，不能作为批量输入。
- `model --input-model` 接收XML；参数策略文件为YAML。将空间配置YAML当成XML会触发解析错误。
- 源名使用XML中的准确名称。路径tag会清理不适合文件名的字符；原始源名仍保存在XML和manifest中。
- `init` 不覆盖已有配置；编辑现有文件或使用新文件名。
- 仓库通用模板不包含项目自己的源名整理/add_srcT等脚本；项目steps中的 `sr`、`download hpc` 也是用户环境命令，通用批处理用sbatch。

## 数据范围与共享文件

- 相同能段仅是共用项目/TS map配置的条件之一；时间、ROI、IRF、事件类型、像素和对应数据产品也需一致。配置选择CCUBE/曝光等数据，XML选择空间和谱模型，两者不能互相替代。
- 高能段空间XML可用于100MeV谱分析的固定空间模板，实际事件、CCUBE和曝光须按100MeV–500GeV重新准备。
- prepare按ltcube路径是否存在决定复用或生成，不自动证明其时间及GTI、筛选条件匹配。复用前核对这些条件。
- 下载圆、gtselect事件圆、CCUBE方图与源模型范围是不同设置。事件圆要覆盖方图四角，小角度近似为 `R_select ≥ L/√2`；模型区还需考虑低能PSF贡献。Fermipy和Fermitools各自的筛选半径以实际配置和日志为准，不能假定自动相同。
- 空间配置tmin/tmax需填写有效MET且tmin<tmax，匹配输入数据；scfile通配符需唯一匹配，否则填写明确文件名。
- XML中的SpatialMap模板路径须能在运行环境解析；目录坐标不一定写入SpatialMap节点。没有可用坐标的模板无法由该节点画中心，不能将其强行表示为径向圆。

## 任务与输出

- grid命令生成文件和任务脚本，实际拟合在手动执行submit脚本后运行。FITS等结果在任务完成后产生。
- `sbatch` 返回只表示成功提交，不表示完成。steps按阶段执行：空间任务完成后prepare-gtlike，gtlike完成后compare。提交间隔不保证实际调度的启动间隔。
- 空间/gtlike/spectral/SED提交间隔3秒，TS map默认300秒。TS map间隔由submit_delay_seconds配置。
- 重复生成覆盖同名模型和任务脚本；grid任务通过 `--open-mode=truncate` 覆盖固定Slurm日志。同一组合并发重复运行会竞争同名输出。
- Slurm stdout/stderr进入同一任务日志；Fermitools/Fermipy自身日志仍可能另外保存。比较器读取manifest中的日志路径，不依赖文件时间猜测。
- 多轮空间实验共用同一个output_root会覆盖spatial_grid_manifest.csv。新组合/旧结果不自动重命名；各轮使用明确的output_root，保留匹配的配置与manifest。
- TS map默认在输入XML同目录生成 `tsmap-res` 等名称。不同输入在不同组合目录时可共用YAML；同一目录内多个输入会产生同名输出，需分别设置output_dir。
- TS map删源列表中任一源缺失就跳过整项；不改为部分删源。本轮提交脚本仅含有效任务，但旧XML/FITS/sbatch不自动删除。全部跳过时生成空提交清单。
- source maps依赖源模型；空间形态或源清单改变后重新生成，like/bin-fit已负责执行此步。
- SED `bin` 允许复用已有输出目录并记录覆盖；它会重新复制原始bin输入。使用筛选后XML重跑时用 `bin-fit --input-model`，该模式直接使用传入文件。

## 空间拟合与失败标记

- 共同基础XML包含本次可能出现的源。点源转换Gaussian/Disk时需有seed.r68，或可从原径向模型继承尺度；普通SpatialMap没有可直接继承的圆对称半径。
- `fix_shape: true` 用于固定谱形；调试日志中Freeing/Fixing字样可能是内部临时切换，不单凭某一行判定最终free状态。
- 固定邻源实验需核对模板坐标、尺度和实际空间拟合源列表。`options.delete_low_ts_sources: false` 可关闭TS<1自动删源；默认仍开启。
- 定位失败/越界但返回有效候选坐标时，当前流程会把候选位置同步到region、最终XML及后续gtlike输入，并重新拟合。橙色菱形/虚线圆表示失败候选，不能当作可靠最佳位置或置信区间。无有效候选坐标时任务停止。
- 成功结果的误差来自匹配的LOC_DATA/EXT_DATA FITS。失败、缺失或中心不匹配时，不补造误差；CSV notes记录状态。固定位置没有误差不等于误差为零。
- 点源pos_r68是定位误差；延展r68是空间光子包含半径。Gaussian XML的Sigma、Disk XML的Radius与r68也不是同一数值。
- `--plot`/`--compare-likelihood` 读取结果，不重新定位或优化。修改输入坐标后需运行对应空间任务才能得到新拟合。

## likelihood、TS和AIC

- 直接比较使用相同数据、能段、IRF、背景源集合及明确的自由参数策略；跨能段的绝对likelihood不可用于模型优劣比较。
- 空间比较读取完成日志和可读最终MINUIT XML，缺失产物不能仅以results.dat存在认定完成。manifest中的路径和tag须与该轮实际产物匹配。
- 当前spatial-grid取其固定日志中最后记录的likelihood；spectral-grid取MINUIT完成标记之前的likelihood，以区分后续summary输出。源块ts_minuit、ts_summary、ts_drmnfb与模型之间delta_ts含义不同。
- 空间CSV每源一行，模型likelihood重复；汇总时按tag去重，不能把逐源行作为独立模型重复计数。
- `k` 只统计最终MINUIT XML的free=1参数，此前空间阶段拟合而后固定的坐标/尺度不计入。若解释整个空间模型选择的AIC，需统一考虑此前估计的参数；程序输出是按当前计数的比较。
- 令N=−lnL，ΔTS=2(N_ref−N_model)，ΔAIC=2Δk−ΔTS。ΔTS正值表示相对参考改善；ΔAIC越小越好。终端按likelihood排序，不是按AIC排序。更换reference改变零点，不改变相对差异。
- TS_source比较有源与无源；TS_ext比较同一背景下延展源与点源；TS_curve比较其他谱型相同条件下LP与PL。Gaussian与Disk的差值不是TS_ext。
- 背景固定位置或尺度不同的两轮可以比较整体描述，但跨轮差值不能直接当作只改变目标形态的延展TS。存在/不存在或延展检验需使用对应的受控配对。
- TS不自动等于sigma平方。参数边界、额外位置搜索、多次检验、非嵌套模型和拟合失败均影响显著性解释。
- 显示数值保留两位小数；程序用原始精度计算差值。由截图舍入值反算会有末位差别。

## 谱与 SED

- spectral-grid当前只转换PowerLaw/LogParabola，固定全部空间参数。多源比较的reference需是该轮完整组合tag。
- spectral-grid比较跳过缺失/未完成产物及带Traceback日志；收敛警告写入notes。出现return code、边界或异常beta误差时需核查，不能把输出文件存在等同于可信拟合。
- 相同背景自由度、事件范围和空间模板才构成可解释的PL/LP对照。低TS或空间混淆也可能造成表观谱曲率。
- SED中固定空间和全能段谱形、测量归一化。低TS背景筛选的XML/results/ibin须手动一一配对；keep_normalization_sources保留原归一化状态，不强制把原来fixed改成free。
- 积分photon flux/energy flux不能直接当作E²dN/dE单色点；用能段平均通量时标明定义。日志已计算上限的源可绘上限，未计算上限时不能伪造95%上限。
- butterfly的完整统计传播需要协方差或profile likelihood；仅用各XML参数独立误差得到的是近似误差带。
- 辅助绘图脚本含可编辑的源名和路径，使用前按项目填写。数据图、模型比较与物理关联是不同证据层次。
