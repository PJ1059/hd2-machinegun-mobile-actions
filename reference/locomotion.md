# 离线预览的直行、冲刺与站姿来源

依据：本机原版 avatar `4d1c334d294dfa97` 的 `state_machine`，归档 `18235e0c9ec0e636`；解析对照本地 Filediver `stingray/state_machine/state_machine.go` 的 `ParseBlendFunction`、`ParsePostfix`、`ToDriver` 和 Blender importer 的 Time state 分支。只研究当前预览必要的 layer 0 状态 59、75、78、86、93，未修改游戏或模型。

## 最终选择

|用途|状态/索引（从零计数）|动画资源|采样方式|
|---|---|---|---|
|持续直线冲刺|layer 0 state 78，clip 0|`0f93b8bf901345ea`|原速，周期 **0.5 秒**，冻结 `StingrayEntityRoot.position` 后循环|
|直线行走|layer 0 state 86，clip 1|`ce5ed97dc3c5e599`|原速，周期 1.0 秒，原地预览冻结根位移|
|稳定站立下半身|layer 0 state 93，clip 4|`b726036661e01b81`|固定采样末帧 **1.983333349 秒**，不循环|

## 为什么 state 75 不适合作持续冲刺

state 75 为 `Blend`，`Loop=false`。共有 6 个自定义函数：第一个为播放速度 `1`，随后 5 个为相应 clip 的权重，均受 `move_angle`（变量索引 30，默认值 0）控制。

|clip index|资源|三角权重的最低点/峰值/最高点|
|---|---|---|
|0|`49e0e478d2727bcb`|-250 / -180 / -90|
|1|`07ee199d8651ad10`|-180 / -90 / 0|
|2|`280f6a48a012814a`|-90 / 0 / 90|
|3|`cff461ec14ed8436`|0 / 90 / 180|
|4|`76b75f2675df64c8`|90 / 180 / 250|

`move_angle=0` 确实应选 clip 2，权重为 `[0,0,1,0,0]`。但它是直线**起步**，不是持续循环：时长 0.666666687 秒，首末 boss 转角差 39.227685°、右大腿 44.869901°，不可直接首尾续接。

决定性状态机证据：state 75 的 `EmitEndEvent=879a950f`，同状态内该事件转向 **state 78**（blend 0.2 秒，link type 2）。state 78 的 `Loop=true`，它才是起步后的持续冲刺状态。

## 持续冲刺 state 78 的选择

state 78 含 9 clips、首个播放速度函数 `1`。其直线/平地中央分支使用变量 `move_speed`（索引 42）与尚未解析名称的变量 `85e2c29a`（索引 28，默认 0）。不要给未知变量擅自命名。

clip 0 权重：

```text
match_range2d(move_speed, 4.5, 6.5, 50,
              variable_28, -30, 0, 30)
```

这是两个三角权重的乘积；设 `move_speed=6.5`、`variable_28=0`，得到 clip 0 权重 1，其余 8 clips 权重均为 0。末尾另有 `terrain` 函数（索引 49，默认 0），其引擎具体作用本轮未解释，不当作第十个 clip。

原生 clip `0f93b8bf901345ea` 的首末检查通过：boss、hips、左右大腿/膝/脚/脚掌的局部旋转差均为 **0°**，局部位置差均为 **0 米**；去除共同根位移后，其全局关节点位置差也为 0。唯一持续位移在 `StingrayEntityRoot`：0.5 秒前进 3.19437415 米。原地预览固定该根位置即可保留真正的连续冲刺步态，无需加速行走或构造半步续接。

## 行走与站立

state 86 的 clip 0 峰值方向是 -45°，不适合当作直行。clip 1 对应：

```text
match_range2d(move_angle, -45, 0, 45, move_speed, 0, 2, 100)
```

`move_angle=0`、`move_speed=2` 时 6 个 clip 权重为 `[0,1,0,0,0,0]`。该状态 `Loop=true`。

state 93 的 clip 4 在 `move_angle=0` 时权重 1；其他 clips 为 0。它是方向相关的停步动作，`Loop=false`。首末腿部姿态确实不同；最后 0.25 秒中 boss、hips、双腿、双膝、双脚的旋转变化均为 0°，末帧适合固定作站立下半身底姿。右脚掌末段仅约 0.075°变化，固定末帧后也不会漂移。

原先使用的 state 59 `759c08277f1296d0` 是 `Time` 状态，时间变量为 `aim_horizontal`（索引 35，默认 **0.5**）。Filediver 的 importer 把此变量限制在 0..1 并作为归一化 `eval_time`，所以固定 t=0 是水平瞄准参数端点，并非中性站姿；该 clip 时长 1 秒，中性默认值对应 0.5 秒。当前采用 state 93 末帧即可避免这个问题。

## 重复核实

在本机开发工作区根目录（本项目的上一级）运行：

```powershell
python mg43-mobile-reload/tools/inspect_locomotion.py
python mg43-mobile-reload/tools/inspect_locomotion.py --seams
```

首条读取本机原版状态机，打印函数、变量、所选权重与起步到持续冲刺的连接，并用断言核对前进方向；第二条从原始动画读取关节点变换并比较端点。工具只读，不生成或覆盖模型/UI。
