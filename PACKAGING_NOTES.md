# GitHub 版本整理说明

此版本补齐 host、上位机及匹配的调试探针。RTL、存储器初始化文件、FFT XCI、引脚时序约束、预编译 bit/ltx 与归档工程逐字节一致。

脚本中的 Codex Python 路径改为 BASEBAND_PYTHON；组件仿真工具改为 VIVADO_PATH；界面仅保留 500 MSPS。项目和工作目录以仓库位置解析。归档 JSON/报告中的原电脑路径与主机名已去除，数值和原通过标记未改。

results 下的仿真及验收 JSON 属于历史记录，不表示本次重新运行。firmware_manifest 的 hashes 是本 GitHub 版本的文件完整性清单，补包及路径适配已改变部分软件摘要；硬件身份单独由根目录 release_identity.json 约束。不得把重新计算的软件摘要当作新增板测证明。

重新构建在 work/rebuild 中进行，不覆盖随包的 bit/ltx 或历史记录。新构建需要重新检查时序、仿真并上板验收，不能自动继承原板测结论。
