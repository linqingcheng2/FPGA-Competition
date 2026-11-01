# 500 MSPS 数字基带测量仪

基于 Digilent Zybo Z7-20 的数字 I/Q 信号测量系统，支持幅度、帧长、频点和带宽测量，包含 FPGA 工程、Python 上位机及烧录文件。

## 硬件平台

- 开发板：Digilent Zybo Z7-20
- 芯片：Zynq-7020
- Vivado 器件型号：xc7z020clg400-1
- 工作时钟：125 MHz
- 数据通路：四路并行，每拍处理四对 12 位 I/Q 数据
- FPGA 内部数字处理速率：500 MSPS
- FFT 点数：8192、16384
- 数据传输：USB/JTAG

## 工程目录

```text
outputs/parallel_baseband/competition_project_route_opt/
  rtl/          RTL 源码及存储器初始化数据
  ip_seed/      FFT IP 配置
  scripts/      工程构建、仿真及调试脚本
  tb/           仿真测试文件
  vectors/      I/Q 测试数据
  host/         数据采集和信号分析程序
  results/      bit、ltx、时序报告及验证记录
deliverables/ui_professional/   上位机程序
board/                         开发板型号及实物照片
vivado/parallel.xpr            Vivado 工程文件
vivado/parallel.srcs/          配套 IP 配置文件
tools/project.py               工程管理入口
start_ui.cmd                   上位机启动脚本
requirements.txt               Python 依赖
```

## 开发环境

- Windows 10/11
- Vivado 2025.2，安装 Zynq-7000 器件支持
- Python 3.12 及以上版本，包含 Tkinter
- NumPy、SciPy

## 上位机运行

将工程解压到本地目录，在工程根目录打开 PowerShell，安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

双击 `start_ui.cmd` 启动上位机。在诊断页设置本机 `vivado.bat` 路径，连接 Zybo Z7-20。点击连接后加载配套固件，随后可设置测试信号或导入 I/Q 数据进行采集。

也可通过命令启动：

```powershell
$env:VIVADO_PATH = 'D:/Xilinx/Vivado/2025.2/bin/vivado.bat'
.\.venv\Scripts\python.exe -X utf8 -B tools/project.py ui --vivado $env:VIVADO_PATH
```

## 固件加载

在 Vivado Hardware Manager 中连接开发板，选择 Program Device，设置以下文件：

- 比特流：`outputs/parallel_baseband/competition_project_route_opt/results/competition.bit`
- 调试探针：`outputs/parallel_baseband/competition_project_route_opt/results/competition.ltx`

## 工程构建

解压完整工程后，使用 Vivado 2025.2 打开 `vivado/parallel.xpr`，即可查看源码、IP 和约束。首次使用 IP 时，在 Vivado 中生成对应的 Output Products。

也可在工程根目录执行以下命令，另建一份工程：

```powershell
$env:VIVADO_PATH = 'D:/Xilinx/Vivado/2025.2/bin/vivado.bat'
.\.venv\Scripts\python.exe -X utf8 -B tools/project.py create --vivado $env:VIVADO_PATH
```

生成的工程文件位于 `work/rebuild/work/route_opt_build/parallel.xpr`，可使用 Vivado 打开。

执行综合、布局布线和比特流生成：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tools/project.py build --vivado $env:VIVADO_PATH
```

构建结果位于 `work/rebuild/outputs/parallel_baseband/competition_project_route_opt/results/`。

## 仿真

创建工程后，执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tools/project.py simulate --vivado $env:VIVADO_PATH
```

默认运行 `tb_pipeline4.v`，使用 8192 点单频测试数据，仿真 4 帧。输出位于 `work/rebuild/work/route_opt_verified_sim/`。

## 文件校验

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tools/project.py check
```

该命令核对源码、固件和配套文件的 SHA-256。验证记录见 `VALIDATION.md`。
