# M-1000 移动射击：最小改动核实

当前结论：独立开关只需把 M-1000 自有 `WeaponDataComponentData` 记录内 **+387 的一个字节从 1 改为 0**。Filediver 将此字段命名为 `FirePreventsMovement`，现有 HD2Runtime 将它公开为 `weapon.stationary_while_firing`。无需修改 MG-43 换弹字段、射速、伤害、旋转预热、弹药或新动画。

## 精确目标

|项目|值|
|---|---|
|武器|M-1000 Maxigun|
|实体资源 ID|`43a58cb89cfa197c`|
|组件|`WeaponDataComponentData`，component index **236**|
|组件框架偏移|**26151656**（解码后的 entities 文件内）|
|组件索引容量 / 记录数|730 / 366|
|索引行 / 记录索引|**116 / 348**|
|记录区相对偏移 / 记录步长|11680 / 1232|
|记录绝对参考偏移|26592100|
|目标字节记录内偏移|**387**，`u8`|
|目标字节绝对参考偏移|26592487|
|原值 → 目标值|**1 → 0**|
|所有者|该记录只有 `43a58cb89cfa197c` 一个所有者|

上述偏移属于参考定义文件/运行时定义区域，**不能当作进程绝对地址或磁盘加密文件偏移直接写入**。独立开关应沿用已有组件定位、所有权核对、原值检查及恢复流程。对完整 1232 字节记录做内存内模拟后，差异列表严格为 `[387]`。

重新读取本机 Filediver 解码引用数据，366 个 WeaponData 记录中只有 record 348 的该字节为 1。引用 entities SHA-256：`21377252B81FDBC670EBA1E59A8AB64B170323DF208F175E708992E4C1FB515E`；引用 typelib 也与 active build 一致。安装中的 EXE 与 game.dll 指纹均与当前 `F5FEE03DCFDB` / Steam build `25480438` 配置相符。

## 为什么不会沿用全身架枪滑步

保留的 WeaponData 事件是：

|记录内偏移|原值|事件|
|---|---|---|
|388|`45fa1230`|`brace`|
|392|`a1b0847a`|`brace_exit`|
|928|`70636b55`|`fire_minigun`|

本地已有原生 consumer 研究说明：+387 置 1 时，射击路径发送 +388 的 `brace`、准备 +392 的 `brace_exit`，并设置持枪者 action bit 55；清零后不走该静止射击分支。+928 的逐发 `fire_minigun` 是独立路径，应保留。

本轮直接读取本机原版 avatar 状态机并核实：

- `brace` 进入 layer 1 的 state 8 / 46，`brace_exit` 进入 state 9 / 47；这些有动画的状态使用 **mask 16**，boss、hips、双大腿、双膝、双脚的权重全为 **1**，会覆盖下半身。另有空状态目标 33 / 36。
- `fire_minigun` 进入 **layer 12，state 19**（`Weapon_Add/fire_minigun`），动画 `b814069f343bc0b9`，为 additive 动画，使用 **mask 60**。
- mask 60 的 boss、hips、双大腿、双膝、双脚权重全为 **0**；spine1 为 0.8，spine2/chest 为 1。原本的射击反馈已经只影响上半身，因此本轮没有证据要求新增移动射击动画或改腿部 mask。

这与 MG-43 解除换弹限制仍播放跪姿的情形不同：这里同一个标志还控制进入全身 `brace` 的射击分支，最小改动会同时避开它。是否在所有操作顺序和联机状态下都能获得预期表现，仍需一次游戏内验证。

## 不需要修改 Ability 或预热

该实体 `AbilityComponentData` record 942 的四个 spawn pair 均为 `(job=12, ability=0)`，不是一个可供本需求简单切换的架设/射击能力开关。已定位的限制直接属于 WeaponData。`WeaponWindUpComponentData` record 8 的预热/停转均为 0.5 秒，本轮保持不变；`WeaponReloadComponentData` 和背包供弹也保持不变。

## 已验证与限制

已验证：本机版本指纹、引用定义 checksum、字段类型和原值、唯一所有者、唯一置 1 记录、一个字节差异、当前 avatar 的 brace 与逐发射击 mask。

继承的静态研究：`runtime-interface-lab/HD2Runtime/scripts/research_weapon_movement.py` 的原生代码 consumer 证据（`+0x183` 判断和 `bts rax,0x37`）及 `docs/weapon-movement.md`。原研究依赖的已解包 `.hd2snap` 在当前机器该路径下不存在，因此本轮没有重新执行其 game.dll consumer 扫描；不能把它表述为本轮新完成的反汇编验证。

未验证：实际移动速度、疾跑/飞扑可用性、旋转预热时切换开关、已经进入 brace 后立即关闭限制的过渡、联机同步。独立开关优先在松开扳机后应用；动作中切换是否能立即退出既有姿态应实测后再承诺。现有 SDK 对该字段仍标记 `liveTested=false`，本轮也未部署或运行游戏。

## 重复检查

在本机开发工作区根目录（本项目的上一级）运行：

```powershell
python mg43-mobile-reload/tools/inspect_m1000.py
```

输出包括准确目标、当前原值、所属记录、事件与 mask。加 `--profile` 可额外输出完整原始记录供已有构建器核对。工具只读，不改游戏、附加组件或模型。
