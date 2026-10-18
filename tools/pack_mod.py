"""Package edited native animations into an offline HD2 patch; never installs.

Input manifest: {"resources": [{"name": "16hex", "type": "animation",
"file": "path/relative/to/manifest.animation"}]}. --mobile-mask redirects only
MG43 standing reload states 600/601 to private animation IDs and upper-body
mask 40. The original animation resources remain available to prone states.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

from game_resources import AVATAR, AVATAR_ARCHIVE, GameResources, hash64
from native_animation import decode

ROOT = Path(__file__).resolve().parents[1]
HEADER = struct.Struct('<III20sQQ24s')
TYPE = struct.Struct('<IIQIIII')
ENTRY = struct.Struct('<7Q6I')
RELOADS = {600: 0xF9761FD85530AE0F, 601: 0xB72125AC2AA44568}
PRIVATE_NAMES = {600: 'content/mods/mg43_mobile_reload/normal',
                 601: 'content/mods/mg43_mobile_reload/fast'}
BOOT_ARCHIVE = '9ba626afa44a3aa3'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(value, alignment=16):
    return (value + alignment - 1) // alignment * alignment


def patch_mobile_state_machine(source: bytes, replacements: dict[int, int]):
    """Change exactly mask+one animation reference in MG43 standing states."""
    data = bytearray(source)
    groups_at, = struct.unpack_from('<I', data, 8)
    group_count, = struct.unpack_from('<I', data, groups_at)
    if group_count <= 10:
        raise ValueError('Avatar has no expected layer 10')
    group_relative, = struct.unpack_from('<I', data, groups_at + 4 + 10 * 4)
    group = groups_at + group_relative
    count, = struct.unpack_from('<I', data, group + 8)
    if count <= 751:
        raise ValueError('Unexpected avatar state count')
    changes = []
    touched = set()
    for state_index, old_animation in RELOADS.items():
        relative, = struct.unpack_from('<I', data, group + 12 + state_index * 4)
        state = group + relative
        anim_count, anim_offset = struct.unpack_from('<II', data, state + 12)
        old_mask, = struct.unpack_from('<i', data, state + 108)
        animations = struct.unpack_from(f'<{anim_count}Q', data, state + anim_offset)
        if old_mask != -1 or animations != (old_animation,):
            raise ValueError(f'State {state_index} differs from pinned MG43 standing state')
        new_animation = replacements[state_index]
        struct.pack_into('<i', data, state + 108, 40)
        struct.pack_into('<Q', data, state + anim_offset, new_animation)
        touched.update(range(state + 108, state + 112))
        touched.update(range(state + anim_offset, state + anim_offset + 8))
        changes.append({'layer': 10, 'state': state_index, 'offset': state,
                        'maskBefore': old_mask, 'maskAfter': 40,
                        'animationBefore': f'{old_animation:016x}',
                        'animationAfter': f'{new_animation:016x}'})
    changed = [i for i, (a, b) in enumerate(zip(source, data)) if a != b]
    if not set(changed) <= touched or len(source) != len(data):
        raise ValueError('State-machine modification exceeded the two requested fields')
    return bytes(data), {'changes': changes, 'changedByteCount': len(changed),
                         'sourceSha256': sha(source), 'resultSha256': sha(data),
                         'proneStateRecords': 'unchanged', 'otherStateRecords': 'unchanged'}


def patch_global_package(source: bytes, animations):
    """Keep the game's global-resources package and declare the two new clips."""
    if len(source) < 16:
        raise ValueError('Truncated global resource package')
    count, = struct.unpack_from('<I', source, 8)
    if len(source) != 16 + count * 16:
        raise ValueError('Unexpected package extent or trailing data')
    original = list(struct.iter_unpack('<QQ', source[16:]))
    if original != sorted(original) or len(set(original)) != len(original):
        raise ValueError('Expected sorted unique original package items')
    animation_type = hash64('animation')
    required_originals = {(animation_type, value) for value in RELOADS.values()}
    required_originals.add((hash64('state_machine'), AVATAR))
    if not required_originals <= set(original):
        raise ValueError('This package does not own the expected avatar reload resources')
    additions = [(animation_type, name) for name in animations]
    if len(additions) != 2 or len(set(additions)) != 2 or set(additions) & set(original):
        raise ValueError('Expected exactly two genuinely new animation dependencies')
    items = sorted(original + additions)
    header = bytearray(source[:16])
    struct.pack_into('<I', header, 8, len(items))
    result = bytes(header) + b''.join(struct.pack('<QQ', kind, name) for kind, name in items)
    restored = [item for item in items if item not in additions]
    if restored != original or result[:8] != source[:8] or result[12:16] != source[12:16]:
        raise ValueError('Package edit changed original dependencies or unknown header fields')
    return result, {'resource': AVATAR_ARCHIVE, 'path': 'packages/content/global_resources',
        'type': 'package', 'sourceArchive': BOOT_ARCHIVE, 'sourceItems': count, 'resultItems': len(items),
        'originalItemsPreserved': len(restored), 'addedItems': [
            {'type': 'animation', 'name': f'{name:016x}'} for _, name in additions],
        'sourceSha256': sha(source), 'resultSha256': sha(result),
        'sourceBytes': len(source), 'resultBytes': len(result)}


def build_patch(resources):
    """Build standard main-only Stingray archive from (name, kind, bytes)."""
    resources = sorted(resources, key=lambda item: (hash64(item[1]), item[0]))
    if not resources:
        raise ValueError('No resources supplied')
    if len({(n, k) for n, k, _ in resources}) != len(resources):
        raise ValueError('Duplicate resource IDs')
    types = sorted({kind for _, kind, _ in resources}, key=hash64)
    type_records = b''.join(TYPE.pack(0, 0, hash64(kind),
        sum(1 for _, k, _ in resources if k == kind), 0, 16, 64) for kind in types)
    cursor = align(HEADER.size + len(type_records) + len(resources) * ENTRY.size, 256)
    records, payload = [], bytearray()
    payload_start = cursor
    main_buffer = 0
    for index, (name, kind, raw) in enumerate(resources):
        cursor = align(cursor)
        payload.extend(b'\0' * (cursor - payload_start - len(payload)))
        # Native animations and state machines have no stream or GPU payload.
        records.append(ENTRY.pack(name, hash64(kind), cursor, 0, 0, main_buffer, 0,
                                  len(raw), 0, 0, 16, 64, index))
        payload.extend(raw)
        cursor += len(raw)
        main_buffer += align(len(raw), 256)
    main_size = align(cursor)
    header = HEADER.pack(0xF0000011, len(types), len(resources), b'', main_buffer, 0, b'')
    table = header + type_records + b''.join(records)
    return {'': table.ljust(payload_start, b'\0') + bytes(payload) + b'\0' * (main_size - cursor),
            '.stream': b'', '.gpu_resources': b''}


def verify_patch(main, expected):
    magic, type_count, count, *_ = HEADER.unpack_from(main)
    if magic != 0xF0000011 or count != len(expected):
        raise ValueError('Archive count/header validation failed')
    readback = {}
    base = HEADER.size + type_count * TYPE.size
    for at in range(base, base + count * ENTRY.size, ENTRY.size):
        entry = ENTRY.unpack_from(main, at)
        name, kind, offset = entry[:3]
        size = entry[7]
        if offset % entry[10] or entry[8] or entry[9] or offset + size > len(main):
            raise ValueError('Archive resource range/alignment validation failed')
        readback[name, kind] = main[offset:offset + size]
    for name, kind, raw in expected:
        if readback.get((name, hash64(kind))) != raw:
            raise ValueError(f'Archive round-trip failed for {name:016x}.{kind}')
        if kind == 'animation':
            decode(raw)
    return True


def verify_with_sdk(raw):
    """Independent HD2SDK reader, loading only its codec classes (no Blender)."""
    sdk = ROOT / 'vendor/hd2sdk'
    scope = {'ceil': math.ceil, 'sqrt': math.sqrt, 'floor': math.floor,
             'isnan': math.isnan, 'PrettyPrint': lambda *_: None}
    memory_source = (sdk / 'utils/memoryStream.py').read_text('utf-8')
    exec(compile(memory_source, 'hd2sdk/utils/memoryStream.py', 'exec'), scope)
    tree = ast.parse((sdk / 'stingray/animation.py').read_text('utf-8'))
    classes = ast.Module(body=[node for node in tree.body if isinstance(node, ast.ClassDef)], type_ignores=[])
    exec(compile(classes, 'hd2sdk/stingray/animation.py', 'exec'), scope)
    animation = scope['StingrayAnimation']()
    animation.load(scope['MemoryStream'](raw))
    parsed = decode(raw)
    errors = []
    for entry in animation.entries:
        if entry.subtype not in (4, 5, 6):
            continue
        channel = {4: 'position', 5: 'rotation', 6: 'scale'}[entry.subtype]
        track = parsed['tracks'][entry.bone][channel]
        time = entry.time / 1000.
        index = min(range(len(track['times'])), key=lambda i: abs(track['times'][i] - time))
        errors.extend(abs(a - b) for a, b in zip(track['values'][index], entry.data2))
    error = max(errors, default=0.)
    if error > 1e-6 or animation.bone_count != len(parsed['tracks']):
        raise ValueError('HD2SDK independent native curve check failed')
    return {'reader': 'HD2SDK Community Edition', 'bones': animation.bone_count,
            'keys': len(animation.entries), 'duration': animation.animation_length,
            'maxCurveValueError': error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/mg43-mobile-reload-visual-prototype')
    parser.add_argument('--mobile-mask', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text('utf-8'))
    records, evidence = [], []
    mappings = {}
    for record in manifest['resources']:
        name = int(record['name'], 16)
        kind = record['type']
        file_path = (args.manifest.parent / record['file']).resolve()
        if not file_path.is_file():
            file_path = (ROOT / record['file']).resolve()
        raw = file_path.read_bytes()
        original = name
        if args.mobile_mask and kind == 'animation' and name in RELOADS.values():
            state_index = next(state for state, old in RELOADS.items() if old == name)
            name = hash64(PRIVATE_NAMES[state_index])
            mappings[state_index] = name
        elif args.mobile_mask and kind == 'animation' and name in {hash64(v) for v in PRIVATE_NAMES.values()}:
            state_index = next(state for state, path in PRIVATE_NAMES.items() if hash64(path) == name)
            mappings[state_index] = name
            original = RELOADS[state_index]
        records.append((name, kind, raw))
        evidence.append({'name': f'{name:016x}', 'originalAnimation': f'{original:016x}',
                         'type': kind, 'size': len(raw), 'sha256': sha(raw)})
        if kind == 'animation':
            evidence[-1]['independentNativeCheck'] = verify_with_sdk(raw)
    state_evidence = None
    package_evidence = None
    package_records = []
    if args.mobile_mask:
        if set(mappings) != set(RELOADS):
            raise ValueError('--mobile-mask requires both original MG43 normal and fast edited animations')
        game = GameResources()
        source = game.resource(AVATAR, 'state_machine')
        changed, state_evidence = patch_mobile_state_machine(source, mappings)
        records.append((AVATAR, 'state_machine', changed))
        evidence.append({'name': f'{AVATAR:016x}', 'type': 'state_machine',
                         'size': len(changed), 'sha256': sha(changed)})
        source_package = game.resource(int(AVATAR_ARCHIVE, 16), 'package', BOOT_ARCHIVE)
        changed_package, package_evidence = patch_global_package(source_package, mappings.values())
        package_records = [(int(AVATAR_ARCHIVE, 16), 'package', changed_package)]
    packed = build_patch(records)
    verify_patch(packed[''], records)
    args.output.mkdir(parents=True, exist_ok=True)
    stem = AVATAR_ARCHIVE + '.patch_0'
    for suffix, raw in packed.items():
        (args.output / (stem + suffix)).write_bytes(raw)
    if package_records:
        package_packed = build_patch(package_records)
        verify_patch(package_packed[''], package_records)
        for suffix, raw in package_packed.items():
            (args.output / (BOOT_ARCHIVE + '.patch_0' + suffix)).write_bytes(raw)
    report = {'status': 'offline-visual-prototype-not-game-tested', 'archive': AVATAR_ARCHIVE,
              'resources': evidence, 'stateMachine': state_evidence,
              'packageDependencies': package_evidence,
              'movementLogic': 'requires ReloadAllowMove enabled separately; not changed by this asset patch',
              'ability': 'unchanged', 'validation': ['archive byte-for-byte readback', 'native animations decoded',
                                                   'HD2SDK independent native curve decoder',
                                                   'two private animation IDs declared in original global package'],
              'unverified': ['game loading of private animation IDs', 'engine blend behavior', 'reload interrupt and ammo timing']}
    (args.output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    readme = ('MG-43 移动换弹：离线视觉原型\n\n'
              '本目录由 pack_mod.py 生成；没有安装或写入游戏。\n'
              '动画资源与状态机已通过离线解码和归档读取校验，尚未进游戏验证。\n'
              '只对站立/蹲姿 MG-43 换弹接入新动画和上半身遮罩；原俯卧引用保留。\n'
              '另在原全局资源package列表添加两条新动画依赖，保留4243条原项；随包提供boot归档补丁。\n'
              '还需要独立开启 ReloadAllowMove 后才能实测移动；此资产包不修改行为编号或换弹时长。\n'
              '新动画资源加载、引擎混合、中断续接与弹药结算需要游戏内验证。\n')
    (args.output / 'README.txt').write_text(readme, 'utf-8')
    zip_path = args.output.with_suffix('.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as package:
        for path in sorted(args.output.iterdir()):
            if path.is_file():
                package.write(path, path.name)
    print(json.dumps({'output': str(args.output), 'zip': str(zip_path), 'resources': len(records),
                      'stateMachine': state_evidence, 'installed': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
