# 0.2.0 初始化失败与 0.2.1 修复

2026-10-18 用户实测：两插件已由 Bingus Shared Loader 加载，MG43MobileReload.log / M1000MobileFire.log 均报 `expected exactly one current entity allocation`，发生在目标字段写入前。本轮直接读取原日志并核对 Arsenal 当前 default：原 MOD 已启用部署、两个选项均开启。没有重新启动或访问游戏进程。

## 确认的定位器缺陷

旧代码要求 `VirtualQuery.RegionSize == 46616576` 且区域基址等于 allocation 基址，但 VirtualQuery 返回的是具有相同状态/保护的连续区域，不保证等于整个分配区。数据未就绪时只扫描一次；任何查询异常也会提前结束扫描，统一转成候选数量断言。旧日志没有实际候选数、表头数、扫描终止地址，无法据此确定用户那次运行的具体分支。

当前文件头、参考文件尺寸、游戏版本指纹及 Bingus 的真实 FFI 查询接口已核对；没有把“文件头错误”或“FFI 参数不能传数字”的猜测当成结论。

## 修复范围

- 用 GetSystemInfo 的应用地址上限完成扫描，查询错误单独报告地址和原因。
- 在 allocation 起点核对表头；按各区域逐段验证引用数据覆盖范围、所属 allocation 和保护，再核对组件框架、唯一所有者、记录及目标字节外的原值。
- 完整有效的候选必须唯一；表头相同但目标记录不符的副本不再妨碍真实目标。多个完整候选仍拒绝写入。
- 数据表尚未出现时等待一秒后重新扫描，最多五次。每轮记录 regions / headers / candidates；其他明确校验失败不以无限重试掩盖。

动画、状态机、两个原生选项名称、GUID、目标字段及一字节写入/还原逻辑保持原范围。

## 验证

在项目目录可运行：

```powershell
python tools/verify_locator.py --expect-broken
python tools/verify_locator.py
python tools/verify_locator_windows.py
```

第一条使用 build/history 中冻结的 0.2.0 模板，证明旧错误可重复。第二条执行两插件各七种场景：分段分配、较大分配、延迟表、查询错误、始终无表、两个完整表和表头相似的无效副本。预期成功场景均完成目标写入及还原；拒绝场景没有写入，错误可区分。

第三条在加载原游戏 lua51.dll 的独立测试 VM 中，创建并释放自有 VirtualAlloc 分配区；只替换游戏版本检查，其余使用真实 Win32 查询、读取、保护修改、写入和还原。两插件分别在完整和分段保护下均通过，共四项，不附加或写入游戏。

原各十项记录/原值/一字节写入/保护恢复检查、五项真实 Bingus core 共存检查，以及 Arsenal 原始选项逻辑和最终 ZIP 资源检查继续通过。证据保存在 build/locator-before-fix.json、locator-verification.json、locator-windows-verification.json 及 release-verification.json；修复 ZIP 内也包含验证结果。

## 尚未确认

0.2.1 没有导入管理器、部署或进入游戏。不能宣称实际游戏内已恢复。下一次启动应先检查两日志是否出现 `v0.2.1 scans=... candidates=1`，随后分别出现 `ReloadAllowMove=1` 和 `stationary_while_firing=0`。这只证明初始化与字段写入；动作、实际移动速度和中断表现仍以游戏观察为准。
