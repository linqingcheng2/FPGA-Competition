# FPGA参赛作品

500 MSPS 数字基带测量仪，基于 Digilent Zybo Z7-20（Zynq-7020）。

## 下载工程

[下载 FPGA参赛作品.zip](./FPGA参赛作品.zip?raw=true)

压缩包包含 RTL 源码、Python 上位机、Vivado 工程、IP 配置、约束、测试数据、预编译 bit/ltx 和开发板资料。

## 使用 Vivado 打开

完整解压后，使用 Vivado 2025.2（安装 Zynq-7000 器件支持）打开：

```text
FPGA500MSPS_GitHub/vivado/parallel.xpr
```

首次使用 IP 时需生成 Output Products。详细安装、上位机启动、构建和仿真步骤见压缩包内 README.md。

## 验证说明

分发文件摘要和工程引用已检查；本打包版本尚未实际使用 Vivado 2025.2 打开、重新综合布线或完成新一轮实板验证。包内历史验证报告的适用范围见 VALIDATION.md。

500 MSPS 指 FPGA 内部数字处理速率，不代表 USB/JTAG 持续传输速率。
