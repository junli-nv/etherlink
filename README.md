# Etherlink

Linux 以太网口与 LLDP 拓扑工具，Python 3.9+ 标准库实现，无 pip 依赖。
控制端需要 OpenSSH；节点需要 Python 3.9+、已有 lldpd 服务和可访问的 lldpcli。
只读查询，不安装软件、不启动服务、不修改网络配置。

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
