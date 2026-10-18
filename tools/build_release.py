"""Build the two independently selectable Arsenal features; never installs them."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'runtime-interface-lab/HD2Runtime/scripts'))
from hd2_archive import ARCHIVE_NAME, make_resource_archive, read_archive, resource_hash

AVATAR_STEM = '18235e0c9ec0e636.patch_0'
SUFFIXES = ('', '.gpu_resources', '.stream')
VERSION = '0.2.1'


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def load_archive(folder, stem=ARCHIVE_NAME):
    return read_archive((folder / stem).read_bytes(), (folder / (stem + '.gpu_resources')).read_bytes())


def add_archive(files, folder, stem, resources):
    main, gpu = make_resource_archive(resources)
    if read_archive(main, gpu) != resources:
        raise ValueError('Native archive readback differs: ' + folder)
    for suffix, body in (('', main), ('.gpu_resources', gpu), ('.stream', b'')):
        files[f'{folder}/{stem}{suffix}'] = body


def validate_selection(files, manifest, selected):
    includes = [directory for index in selected for directory in manifest['Options'][index]['Include']]
    paths = sorted(name for name in files if any(name.startswith(directory + '/') for directory in includes)
                   and '.patch_' in name)
    names = [Path(name).name for name in paths]
    if len(names) != len(set(names)):
        raise ValueError('Selected options have colliding native filenames')
    resources = {}
    for path in paths:
        if path.endswith(('.gpu_resources', '.stream')):
            continue
        for suffix in SUFFIXES:
            if path + suffix not in paths:
                raise ValueError('Incomplete native archive triad')
        archive = read_archive(files[path], files[path + '.gpu_resources'])
        shared = resources.keys() & archive.keys()
        if shared:
            raise ValueError('Selected options overwrite the same native resources: ' + repr(shared))
        resources.update(archive)
    lua_type = resource_hash('lua')
    for index, path in ((0, 'mods/hd2_local/mg43_mobile_reload'), (1, 'mods/hd2_local/m1000_mobile_fire')):
        if ((lua_type, resource_hash(path)) in resources) != (index in selected):
            raise ValueError('Feature checkbox does not independently select its addon: ' + path)
    avatar_key = (resource_hash('state_machine'), int('4d1c334d294dfa97', 16))
    if (avatar_key in resources) != (0 in selected):
        raise ValueError('MG43 checkbox does not independently select its state machine')
    if 0 in selected:
        package_key = (resource_hash('package'), int('18235e0c9ec0e636', 16))
        package = resources[package_key][0]
        count, = struct.unpack_from('<I', package, 8)
        if len(package) != 16 + count * 16:
            raise ValueError('Invalid native package dependency list')
        items = set(struct.iter_unpack('<QQ', package[16:]))
        for name in ('4cb7b7c50f25ddc0', '7d8cc9583080a3a4'):
            key = (resource_hash('animation'), int(name, 16))
            if key not in resources or key not in items:
                raise ValueError('MG43 private animation is not declared and packed')
    return {'selectedOptions': selected, 'archiveTriads': len(paths) // 3,
            'nativeResources': len(resources), 'addons': len([t for t, _ in resources if t == lua_type]),
            'filenamesDistinct': True, 'typedResourcesDistinct': True}


def main():
    visual = ROOT / 'dist/mg43-mobile-reload-visual-prototype'
    mg43 = ROOT / 'dist/mg43-mobile-reload-movement-prototype'
    m1000 = ROOT / 'dist/m1000-mobile-fire'
    asset_report = json.loads((visual / 'manifest.json').read_text('utf-8'))
    mg43_report = json.loads((mg43 / 'build-report.json').read_text('utf-8'))
    m1000_report = json.loads((m1000 / 'build-report.json').read_text('utf-8'))
    files = {}
    for suffix in SUFFIXES:
        files['MG43/' + AVATAR_STEM + suffix] = (visual / (AVATAR_STEM + suffix)).read_bytes()
    mg43_boot = load_archive(mg43 / 'Addon')
    dependencies = load_archive(visual)
    if mg43_boot.keys() & dependencies.keys():
        raise ValueError('MG43 addon overlaps its native package dependency resource')
    mg43_boot.update(dependencies)
    add_archive(files, 'MG43', ARCHIVE_NAME, mg43_boot)
    # Both features belong to the boot archive. Give the optional patch a distinct
    # filename so selection cannot overwrite it before Arsenal assigns load order.
    m1000_stem = ARCHIVE_NAME.rsplit('.patch_', 1)[0] + '.patch_1'
    add_archive(files, 'M1000', m1000_stem, load_archive(m1000 / 'Addon'))
    manifest = {'Version': 1, 'Guid': '328ebc8a-691a-4a45-8129-c190a7a7c1ed',
        'Name': '机枪移动动作 v' + VERSION,
        'Description': 'MG-43 自然移动换弹，以及可单独开关的 M-1000 移动射击。需要 Bingus Shared Loader API 1。切换选项后部署并重启游戏。',
        'Options': [
            {'Name': 'MG-43：自然移动换弹', 'Description': '启用直立换弹动作，并允许移动换弹。支持普通和快速换弹，保留原版趴姿换弹。', 'Include': ['MG43']},
            {'Name': 'M-1000：允许移动射击', 'Description': '解除 M-1000 射击时强制站定的限制。可单独启用。', 'Include': ['M1000']}]}
    matrix = [validate_selection(files, manifest, options) for options in ([], [0], [1], [0, 1])]
    report = {'version': VERSION, 'status': 'offline-validated-not-game-tested',
        'assetValidation': asset_report, 'mg43RuntimeValidation': mg43_report,
        'm1000RuntimeValidation': m1000_report, 'selectionMatrix': matrix,
        'arsenalManifest': {'options': 'two independent top-level checkboxes',
            'defaults': 'controlled by Arsenal setAllOptionsActive; no invented Default field'},
        'dependency': {'name': 'Bingus Shared Loader', 'api': 1, 'bundled': False},
        'deployed': False, 'arsenalImportTested': False, 'liveGameTested': False}
    for key, filename in (('locatorRegressionValidation', 'locator-verification.json'),
                          ('windowsLocatorValidation', 'locator-windows-verification.json')):
        evidence = json.loads((ROOT / 'build' / filename).read_text('utf-8'))
        if not evidence['passed'] or evidence['gameProcessAccess']:
            raise ValueError('Locator regression evidence failed: ' + filename)
        report[key] = evidence
    files['manifest.json'] = json_bytes(manifest)
    (ROOT / 'build/arsenal-manifest.json').write_bytes(files['manifest.json'])
    native_options = subprocess.run(['node', str(ROOT / 'reference/test-arsenal-options.cjs'),
        str(ROOT.parent / 'backups/arsenal-app-inspection/obfuscated_src'),
        str(ROOT / 'build/arsenal-manifest.json')], cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    options_evidence = json.loads(native_options.stdout)
    if not options_evidence['passed'] or options_evidence['actualWrites'] != 0:
        raise ValueError('Actual Arsenal option/deployer logic validation failed')
    report['arsenalManifestValidation'] = options_evidence
    (ROOT / 'build/arsenal-options-verification.json').write_bytes(json_bytes(options_evidence))
    files['validation-report.json'] = json_bytes(report)
    files['README.txt'] = (
        '机枪移动动作 v0.2.1\n\n'
        '在 HD2Arsenal 中导入本 ZIP，进入模组选项后可独立勾选：\n'
        '  MG-43：自然移动换弹\n'
        '  M-1000：允许移动射击\n'
        '选择需要的功能，部署后重启游戏。全部取消时，本包不加载任何补丁。\n'
        '新导入选项的初始勾选由 Arsenal 的全局设置决定。\n\n'
        '依赖：Bingus Shared Loader（API 1）；不需要另装 HD2Runtime。\n'
        '当前匹配 Steam build 25480438。运行插件核对游戏指纹后定位数据；不匹配时不写入。\n'
        '0.2.1 修复：按完整分配区和目标组件核实数据，不再要求单个内存区域恰好等于文件大小；启动尚未就绪时最多扫描五次；查询错误、候选数和拒绝原因分别写日志。\n'
        'MG-43：普通/快速直立动作与移动换弹；保持原版换弹时长、事件、弹药规则及趴姿动画。\n'
        'M-1000：仅将射击强制站定字段从 1 改为 0；不改射速、伤害、起转时间或射击事件。\n\n'
        '已验证：原生动画独立解码、资源归档读回、MG-43 新动画依赖、Lua 编译、合成内存写入与还原、四组选项资源选择。\n'
        '未验证：Arsenal 实际导入、游戏引擎加载、持续冲刺、M-1000 实际移动速度和联机表现。\n'
        '本构建脚本没有导入管理器、写入游戏或启动游戏。\n').encode('utf-8')
    output = ROOT / f'dist/Machinegun-Mobile-Actions-v{VERSION}.zip'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as package:
        for name, body in sorted(files.items()):
            package.writestr(name, body)
    with zipfile.ZipFile(output) as package:
        if package.testzip() is not None or set(package.namelist()) != set(files):
            raise ValueError('Final ZIP integrity check failed')
        for name, body in files.items():
            if package.read(name) != body:
                raise ValueError('Final ZIP differs from validated source: ' + name)
    summary = {'output': str(output), 'bytes': output.stat().st_size,
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'selectionMatrix': matrix, 'deployed': False, 'liveGameTested': False}
    (ROOT / 'build/release-verification.json').write_bytes(json_bytes(summary))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
