"""Bake native round-trip motion plus the original locomotion layer into glTF.

The browser plays complete poses, not an arbitrary full-body crossfade. Native
mask 40 is evaluated per bone before export, with the actual firearm animation.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from author_motion import read, sample, slerp
from game_resources import ROOT


def load_glb(path):
    data = path.read_bytes()
    magic, version, total = struct.unpack_from('<III', data)
    if (magic, version, total) != (0x46546C67, 2, len(data)):
        raise ValueError('Invalid GLB')
    js_len, js_type = struct.unpack_from('<II', data, 12)
    document = json.loads(data[20:20 + js_len])
    at = 20 + js_len
    bin_len, bin_type = struct.unpack_from('<II', data, at)
    if js_type != 0x4E4F534A or bin_type != 0x004E4942:
        raise ValueError('Expected JSON and BIN chunks')
    return document, bytearray(data[at + 8:at + 8 + bin_len])


def write_glb(path, doc, binary):
    binary.extend(b'\0' * (-len(binary) % 4))
    doc['buffers'] = [{'byteLength': len(binary)}]
    js = json.dumps(doc, separators=(',', ':'), ensure_ascii=False).encode()
    js += b' ' * (-len(js) % 4)
    body = struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(binary), 0x004E4942) + binary
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, len(body) + 12) + body)


class AnimationWriter:
    def __init__(self, document, binary):
        self.doc, self.binary = document, binary

    def accessor(self, values, dimensions, time=False):
        self.binary.extend(b'\0' * (-len(self.binary) % 4))
        offset = len(self.binary)
        flat = values if dimensions == 1 else [v for row in values for v in row]
        self.binary.extend(struct.pack(f'<{len(flat)}f', *flat))
        view = len(self.doc.setdefault('bufferViews', []))
        self.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(flat) * 4})
        accessor = {'bufferView': view, 'componentType': 5126, 'count': len(values),
                    'type': {1: 'SCALAR', 3: 'VEC3', 4: 'VEC4'}[dimensions]}
        if time:
            accessor.update(min=[min(values)], max=[max(values)])
        index = len(self.doc.setdefault('accessors', []))
        self.doc['accessors'].append(accessor)
        return index

    def animation(self, name, times, tracks):
        samplers, channels = [], []
        input_accessor = self.accessor(times, 1, True)
        for node, channel, values in tracks:
            output_accessor = self.accessor(values, 4 if channel == 'rotation' else 3)
            channels.append({'sampler': len(samplers), 'target': {'node': node, 'path': channel}})
            samplers.append({'input': input_accessor, 'output': output_accessor, 'interpolation': 'LINEAR'})
        self.doc.setdefault('animations', []).append({'name': name, 'samplers': samplers, 'channels': channels})


def main():
    doc, binary = load_glb(ROOT / 'assets/source/combined.glb')
    mapping = json.loads((ROOT / 'assets/source/combined-manifest.json').read_text(encoding='utf-8'))
    nodes = mapping['avatar']['bones']
    weapon_nodes = mapping['sources']['weapon']['boneNames']
    ref = json.loads((ROOT / 'reference/source-clips.json').read_text(encoding='utf-8'))
    mask = dict(zip(ref['bones'], ref['masks']['stalwart']))
    idle = read('idle')
    walk = read('walk_1')
    sprint = read('sprint')
    original = read('mg43_normal')
    authored = json.loads((ROOT / 'assets/authored/mg43_upright_normal.decoded.json').read_text())
    weapon = read('weapon_normal')
    writer = AnimationWriter(doc, binary)
    duration = 4.5
    times = [i / 30 for i in range(round(duration * 30) + 1)]
    ground_tracks = {}
    for mode, locomotion in [('walk', walk), ('run', sprint)]:
        root_track = next(t['position'] for t in locomotion['tracks'] if t['bone'] == 'StingrayEntityRoot')
        first = sample(root_track, 0.)
        last = sample(root_track, locomotion['duration'])
        displacement = [b - a for a, b in zip(first, last)]
        positions = []
        for time in times:
            cycles = math.floor(time / locomotion['duration'])
            phase = time - cycles * locomotion['duration']
            local = sample(root_track, phase)
            p = [v - start + cycles * delta for v, start, delta in zip(local, first, displacement)]
            # Opposite of native Z-up -> glTF Y-up -> model's 180-degree yaw.
            positions.append([p[0], 0., -p[1]])
        ground_tracks[mode] = {'times': times, 'positions': positions,
                              'nativeCycleDuration': locomotion['duration'], 'nativeDisplacement': displacement}
    diagnostics = []
    for name, mode, new in [('MG43_New', 'stand', True), ('MG43_New_Walk', 'walk', True),
                            ('MG43_New_Run', 'run', True), ('MG43_Original', 'stand', False),
                            ('MG43_Original_Walk', 'walk', False), ('MG43_Original_Run', 'run', False)]:
        moving = mode != 'stand'
        base = sprint if mode == 'run' else (walk if moving else idle)
        base_map = {t['bone']: t for t in base['tracks']}
        reload = authored if new else original
        tracks = []
        for track in reload['tracks']:
            bone = track['bone']
            if bone not in nodes:
                continue
            weight = mask.get(bone, 0) if new else 1.
            for channel in ('position', 'rotation', 'scale'):
                if channel not in track:
                    continue
                values = []
                for time in times:
                    clip_time = min(reload['duration'], time / duration * reload['duration'])
                    value = sample(track[channel], clip_time, channel == 'rotation')
                    if new and weight < 1 and bone in base_map:
                        # The native character locomotion layer is cyclic and independent
                        # of the reload timer, exactly as the proposed game integration.
                        base_time = time % base['duration'] if moving else base['duration']
                        before = sample(base_map[bone][channel], base_time, channel == 'rotation')
                        if channel == 'rotation':
                            value = slerp(before, value, weight)
                        else:
                            value = [a + (b - a) * weight for a, b in zip(before, value)]
                    if new and moving and bone == 'StingrayEntityRoot' and channel == 'position':
                        # Root displacement is shown by the moving ground. Keeping it
                        # out of the skin clip prevents teleporting at each gait loop.
                        value = sample(base_map[bone][channel], 0.)
                    if bone == 'StingrayEntityRoot':
                        # Native Z-up to glTF Y-up; all other bones stay native-local.
                        if channel == 'position':
                            value = [value[0], value[2], -value[1]]
                        elif channel == 'rotation':
                            x, y, z, w = value
                            c = math.sqrt(.5)
                            value = [c * x - c * w, c * y + c * z, c * z - c * y, c * w + c * x]
                    values.append(value)
                tracks.append((nodes[bone], {'position': 'translation'}.get(channel, channel), values))
        for track in weapon['tracks']:
            bone = track['bone']
            # The firearm is already in the avatar's native basis at its attachment.
            if bone not in weapon_nodes or bone in ('StingrayEntityRoot', 'FbxAxisSystem_ConvertNode'):
                continue
            for channel in ('position', 'rotation', 'scale'):
                if channel in track:
                    values = [sample(track[channel], t / duration * weapon['duration'], channel == 'rotation') for t in times]
                    tracks.append((weapon_nodes[bone], {'position': 'translation'}.get(channel, channel), values))
        writer.animation(name, times, tracks)
        diagnostics.append({'clip': name, 'duration': duration, 'channels': len(tracks), 'frames': len(times),
            'base': 'native sprint' if mode == 'run' else ('native walk' if moving else 'native idle'),
            'reloadMask': 40 if new else -1})
    # Neutral matte materials reveal joint contacts without pretending to reproduce
    # the game's proprietary layered armor shader.
    for node in doc['nodes']:
        if 'mesh' not in node:
            continue
        label = node.get('name', '').lower()
        gun = label.startswith('weapon::') or label.startswith('magazine::')
        dark = any(word in label for word in ('under', 'glove', 'cloth'))
        color = [.12, .15, .16, 1.] if gun else ([.1, .12, .13, 1.] if dark else [.35, .38, .37, 1.])
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            material = doc['materials'][primitive['material']]
            pbr = material.setdefault('pbrMetallicRoughness', {})
            pbr['baseColorFactor'] = color
            pbr['metallicFactor'] = .4 if gun else .15
            pbr['roughnessFactor'] = .55 if gun else .8
    # Strip extraction-only controller extras to keep the distributable viewer small.
    doc.pop('extras', None)
    doc['asset']['generator'] = 'MG43 native motion preview; source Filediver; native codec round-trip'
    out = ROOT / 'assets/preview.glb'
    write_glb(out, doc, binary)
    metadata = {'asset': 'preview.glb', 'duration': duration, 'defaultVariant': 'new', 'defaultMode': 'stand',
        'clips': {'new': {'stand': 'MG43_New', 'walk': 'MG43_New_Walk',
                          'run': {'clip': 'MG43_New_Run', 'description': '原生 sprint 奔跑步态与新换弹的骨骼组合；游戏内持续冲刺换弹尚未实测。'}},
                  'original': {'stand': 'MG43_Original', 'walk': 'MG43_Original_Walk', 'run': 'MG43_Original_Run'}},
        'stages': [{'time': 0, 'label': '起始姿势'}, {'time': 1.1, 'label': '前段动作'},
                   {'time': 2.25, 'label': '中段动作'}, {'time': 3.4, 'label': '后段动作'}, {'time': 4.45, 'label': '完成姿势'}],
        'descriptions': {'new': '保留 MG-43 原有双臂、手指与枪械操作；使用直立躯干姿势和上半身骨骼权重。',
                         'original': '原版全身换弹参考：站立时仍播放原有跪姿。'},
        'source': '本机原版角色、B-01 护甲、MG-43、大供弹盒、行走及 sprint 奔跑动画 · Steam build 25480438',
        'status': '动作原型 · 灰模预览',
        'groundTracks': ground_tracks, 'groundTracksSpace': 'world',
        'verification': '动画已原生编码并重新解码；预览按骨骼权重组合。游戏引擎、弹药结算与中断续接尚未实测。',
        'cameraBounds': {'min': [-.65, -.05, -.65], 'max': [.65, 1.9, .65]},
        'transform': {'rotation': [0, math.pi, 0], 'position': [0, 0, 0], 'scale': 1}}
    (ROOT / 'assets/preview.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'assets/preview-build-report.json').write_text(json.dumps({'glbBytes': out.stat().st_size,
        'clips': diagnostics, 'source': str(out.relative_to(ROOT)), 'nativeRoundTrip': True}, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(out), 'bytes': out.stat().st_size, 'clips': diagnostics}))


if __name__ == '__main__':
    main()
