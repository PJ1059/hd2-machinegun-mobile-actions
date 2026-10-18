# HD2 Arsenal 原生独立选项核实

核实时间：2026-10-18。只读检查，没有导入、启用、部署或改写 Arsenal 配置。

## 结论

使用两个顶层 `Options` 即可：MG-43 与 M-1000 各自为独立复选框，能够单独或同时启用。顶层不是互斥单选；`SubOptions` 才在同一个父选项内显示为单选按钮。本机 Arsenal 为 **0.36.2**，`setAllOptionsActive=true`，导入时两个顶层选项默认都会启用；MOD 总开关因 `setModsActive=false` 默认关闭。Manifest 没有可用的逐项 `Default`、`Required` 或 `Group` 字段。

推荐包布局：

```text
manifest.json
MG43/
  18235e0c9ec0e636.patch_0[.stream/.gpu_resources]
  9ba626afa44a3aa3.patch_0[.stream/.gpu_resources]
M1000/
  9ba626afa44a3aa3.patch_1[.stream/.gpu_resources]
```

```json
{
  "Version": 1,
  "Guid": "使用本 MOD 的稳定 UUID",
  "Name": "MG-43 移动换弹与 M-1000 移动射击",
  "Description": "两项功能可在 Arsenal 选项中独立选择。",
  "Options": [
    { "Name": "MG-43 移动换弹", "Description": "启用 MG-43 移动换弹。", "Include": ["MG43"] },
    { "Name": "M-1000 移动射击", "Description": "启用 M-1000 移动射击。", "Include": ["M1000"] }
  ]
}
```

根目录不要放 `.patch_` 文件。若两项都不选，部署器会回退扫描包根目录；仅保留 manifest 的根目录不会部署任何补丁。`Include` 是包根目录下的文件夹路径，不是补丁文件名；选中多个目录时依次扫描，不递归扫描目录里的子目录。

## 实际源码证据

证据来自本地安装包已提取的 `backups/arsenal-app-inspection/obfuscated_src/`。源文件为单行混淆代码；使用现有只读解码脚本 `backups/arsenal-app-inspection/inspect-api.cjs` 替换纯字符串解码调用，以下片段保留实际执行逻辑。

1. `renderer/eventHandlers/modsTable.js`：选项弹窗实际生成 `<input type="checkbox" class="option-checkbox">`；子选项生成 `<input type="radio" name="subopt-${父选项下标}" class="suboption-checkbox">`。确认按钮遍历每个 `.option-row`，将全部已勾选下标加入 `enabledOptions`，没有顶层互斥逻辑。

2. `main/modsHandler.js` 的 `extractFromManifest`：

   ```js
   // 每个顶层选项，只读取 Name / Description / Include / Image / SubOptions。
   enabled: readData("setAllOptionsActive") ? true : optionIndex === 0
   // 每个子选项：
   enabled: readData("setAllOptionsActive") ? subIndex === 0 : optionIndex === 0 && subIndex === 0
   ```

   `renderer/menus/dev/manifest.js` 的 `generateManifest`、`cleanManifest` 与 `validateManifest` 也只支持上述字段。未读取 `Default` / `Required` / `Group`；给这些字段赋值不会控制导入行为。字段 `Description` 可为空字符串，但不能缺省为 null；有子选项时允许父 `Include` 为空。

3. `main/modules/modDeployer.js` 的 `getValidFolders`：

   ```js
   for (const option of mod.options) {
     if (!option.enabled) continue;
     folders.push(...option.include || []);
     for (const sub of option.suboptions || [])
       if (sub.enabled) folders.push(...sub.include || []);
   }
   ```

   `processModFiles` 对每个 `path.join(packageRoot, include)` 调用 `readdir`，筛选文件名包含 `.patch_` 的条目。多个 Include 是组合关系；不依据其他选项或归档名排他。

4. 同文件 `groupFilesByPatch` 用 `/^(.+?)\.patch_(\d+)(.*)$/` 按源归档及源补丁号把三件套分组。`findAvailablePatchNumber(existing, baseName)` 从 0 起寻找未占用的目标补丁号；`processModFiles` 对每组重新编号，保留扩展名，每写一个文件就更新 `existing`。因此 MG43 中的 boot `.patch_0` 与 M1000 中的 boot `.patch_1` 会分别取得不冲突的新号码；源补丁号不要求与部署后号码相同。

## 选择的持久化格式及原生 API

`main/preload.js` 暴露原生 `window.electronAPI`，`selectModOptions(index, payload)` 对应 IPC `select-mod-options`。`main/ipcHandlers.js` 的处理器接收：

```js
{ enabledOptions: [0, 1], enabledSubOptions: {} }
```

下标是当前配置文件里 `modsList` 的 MOD 下标，`enabledOptions` 则是该 MOD 顶层选项下标；不要把 UUID 直接当下标。处理器持久化到所选 profile 的该 MOD：

```json
{
  "optionsConfig": [
    { "name": "MG-43 移动换弹", "enabled": true },
    { "name": "M-1000 移动射击", "enabled": false }
  ]
}
```

`mergeOptionsWithConfig` 按 `name` 匹配配置，故更新版本时应保留选项名称。处理器在选项有变化且 MOD 已启用或部署时标记 `changed=true`，需要重新部署才改变游戏文件。

相关 API：`addModsFromRenderer([zipPath], profile)` 导入；`getModsLibrary()` 读取库；`readVar('modsList')` 读取所选 profile；`toggleModStatus(index, bool)` / `toggleModStatusBatch([{index,status}])` 控制 MOD 总开关；`selectModOptions(index, payload)` 控制独立选项；`deploy()` 部署。现有 `arsenal-api.mjs` 是连接本机调试端口 9357 的 CDP 辅助脚本，执行给定 renderer 表达式，**不是官方 CLI**；本轮未调用它或执行这些修改 API。未发现独立稳定命令行导入/部署接口。

## 离线验证

从项目目录运行：

```powershell
node reference/test-arsenal-options.cjs
```

测试直接载入上述原始混淆源码，在 VM 中执行原生导入和部署选项逻辑，文件系统操作全部以仅记录调用的桩函数代替，没有真实复制或写入。验证两个独立选项的全部四种组合、导入默认值、按名称合并配置、Include 目录选择、同归档不同源补丁号的重新编号、三件套完整性，以及两项关闭时根目录不含补丁而不复制文件。输出包含实际源码 SHA-256，以固定证据版本。

版本证据：`backups/arsenal-app-inspection/package.json` 的 `version` 与本机 `AppData/Local/hd2arsenal/hd2a_data.json` 的 `appVersion` 都为 `0.36.2`。本轮仅定向读取版本、当前 profile 与两项默认开关，不读取账号凭据。
