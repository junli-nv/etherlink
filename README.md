# Etherlink

Linux 以太网口与 LLDP 拓扑工具，Python 3.9+ 标准库实现，无 pip 依赖。
控制端需要 OpenSSH；节点需要 Python 3.9+、已有 lldpd 服务和可访问的 lldpcli。
默认选择 Mellanox 网卡（PCI 0x15b3）。不安装软件、不改网卡或交换机配置；UP 物理口无 LLDP 时默认自动尝试一次服务恢复。

## 拓扑采集

```bash
cd /home/cmsupport/workspace/etherlink
./etherlink-cli local
./etherlink-cli 'node[001-016,021],gpu[01-04]'
./etherlink-cli 'rack[1-2]node[01-04]' --workers 8 --timeout 25
./etherlink-cli --nodes-file nodes.txt --json links.json --csv links.csv --svg topology.svg
./etherlink-cli --input links.json --svg topology.svg
./etherlink-cli --help
```

集合加引号。节点文件每行一个名字或集合，支持空行和 # 注释。
支持数字范围、枚举、多组括号和前导零；不支持嵌套、步长和完整 Slurm 语法。
默认最多展开 4096 个输入节点（--limit 可调），展开后去重，不依赖 Slurm。
SSH 复用 ~/.ssh/config，不交互询问密码、不关闭主机密钥校验。
local 表示本机；--sudo 仅对 lldpcli 使用 sudo -n。

## 独立名字工具

```bash
/home/cmsupport/workspace/etherlink/etherlink/hosts.py 'node[001-003,007]'
/home/cmsupport/workspace/etherlink/etherlink/hosts.py -c node001 node002 node003 node007
/home/cmsupport/workspace/etherlink/etherlink/hosts.py -c 'node[001-003]' node007
/home/cmsupport/workspace/etherlink/etherlink/hosts.py --separator ',' 'gpu[01-04]'
/home/cmsupport/workspace/etherlink/etherlink/hosts.py -c < names.txt
```

默认逐行展开；--expand/-e 展开，--compact/-c 合并为 node[001-003,007]。
无参数或参数为 - 时读取标准输入，空白分隔，不处理 # 注释。
合并最后一段数字，按前后缀及补零规则分组；结果排序去重，不补出不存在的节点。
不保证最短表达式。主工具无单独名字处理模式，仅自动展开输入集合。


## 输出和限制

SVG 是图片，可用浏览器打开，无 Graphviz/绘图库依赖；当前不直接输出 PNG。
JSON 保留错误及邻居详细字段；CSV 一行一个网口/邻居组合，无邻居时交换机字段为空。
--input 使用保存的 JSON 重绘，不联网。输出覆盖同名文件。
现场报告在 reports/，不要提交到公共仓库。

默认枚举 sysfs 中 type=1 且有 device 的网口，包含 bond 物理成员、RoCE；
排除虚拟网口和原生 InfiniBand。VF 用 is_vf 标记。
--include-virtual 包含虚拟以太网口，不猜测 bond 邻居属于哪个成员。
速率单位 Mb/s，无法读取为 null。

读取 lldpcli -f json show neighbors details，仅采纳 LLDP。多个邻居全部保留。
按 Chassis ID 分组，缺失时用系统名和管理地址；邻居不一定是交换机。
age 不代表最后收包时间。无 LLDP 不等于断线；权限不足、命令缺失、SSH 失败单独报告。
不自动抓包或尝试 lldptool。BMC 口只有 Linux 可见时才能发现。

退出码：0 成功（允许无邻居）；1 部分采集错误，仍导出结果；2 参数/文件/格式错误。

## 检查

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q etherlink
```

## 示例图

以下为模拟数据，不对应现场设备：

![拓扑示例](examples/demo.svg)

保存的数据样例见 examples/demo.json。

## 网卡厂商选择与可交互拓扑

```bash
./etherlink-cli 'node[001-016]' --html topology.html --svg overview.svg
./etherlink-cli 'node[001-016]' --vendor mellanox,intel
./etherlink-cli 'node[001-016]' --vendor mellanox --vendor broadcom
./etherlink-cli 'node[001-016]' --vendor all
./etherlink-cli 'node[001-016]' --vendor all --driver mlx5_core
./etherlink-cli --input links.json --vendor all --html topology.html
```

--vendor 支持逗号分隔和重复参数，也接受 PCI 厂商 ID，例如 15b3、0x8086。
预设名称：mellanox（nvidia 为同一以太网厂商 ID 的别名）、intel、broadcom、realtek、amazon。
all 取消厂商限制；默认仍排除虚拟设备，需要时另加 --include-virtual。
--driver 为可选驱动白名单，可重复。网卡型号从节点已有 pci.ids 读取，无该数据库时
仍保留 vendor_id、device_id 和驱动，不根据网口名字猜型号。

JSON/CSV/SVG/HTML 均使用筛选后的网口。没有匹配网卡的节点仍保留。
若以后需要切换厂商，请先用 --vendor all 保存完整 JSON；
筛选后的文件无法恢复被排除的网口。旧 JSON 无厂商元数据时，请重新采集，
或使用 --vendor all 绕过筛选，不把未知硬件当成 Mellanox。

多节点 SVG 是按相同邻居集合分组的总览，连线表示聚合连接数，不推断交换机互联。
单节点 SVG 按本地网口自然顺序显示精确接线，不按交换机归属重新排列网口。--html 输出无需服务器和外部资源的单文件报告：
总览中的节点可点击，明细可展开查看端口接线图和硬件字段，搜索支持节点、网口、交换机和型号。
UP 只表示本地链路状态；彩色连线按邻居区分，不代表 LLDP 一定可用；邻居为空仍保留，UP 但无邻居的节点以黄色强调。
PNG 预览可用已有 ImageMagick 将 SVG 转换，核心工具无需安装它。

## LLDP 一次性自动恢复与链路状态

实时采集时，只对所选物理网口中 operstate=up、carrier=1 且无 LLDP 的节点，
自动执行一次 systemctl --no-ask-password restart lldpd.service。
同一节点多个口缺少邻居，也只重启一次；统一等待 5 秒后只复查一次。
仍为空就保留空字段并标注告警，不继续重启或轮询。

DOWN 网口无邻居为正常情况，不触发恢复，不标为 LLDP 异常。
虚拟网口、VF 不触发物理口恢复。重启失败、复查失败分别记录；
JSON 的 lldp_recovery 保存操作结果和恢复前后的缺失网口。
非 root 的服务恢复使用 sudo -n，不交互询问密码；--sudo 仍控制 lldpcli 查询权限。

普通实时采集默认启用上述行为，无需额外参数。
需要纯只读采集时可用 --no-restart-lldp；--input 离线重绘始终不连接节点或重启服务。
该规则不把物理口 UP 当成 LLDP 一定可达的保证；BF3/DPU 等环境恢复后仍缺失时保留待核实，
不自动修改 DPU 模式、转发规则、交换机配置或重置网卡。

单节点图逐口显示 UP/DOWN 和速率；DOWN 以灰色标注，LLDP 空值注明正常。
UP 但无邻居以黄色提示。本地网口按自然顺序固定排列，例如 eth1、eth2、eth10；
没有邻居的网口也保留原位置，右侧连线跟随该位置，总览的分组方式不变。
