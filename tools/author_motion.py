"""Repose the MG-43 reload while preserving its original arm/hand choreography.

Only shared torso and stance ancestors are changed. Both arm chains, fingers,
weapon-relative hand paths, animation duration, and weapon animation stay native.
"""
from __future__ import annotations

import bisect
import copy
import json
import math
from pathlib import Path

from game_resources import ROOT, hash64
from native_animation import decode, encode

FPS = 30


def normalize(q):
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q] if n else [0., 0., 0., 1.]


def slerp(a, b, t):
    a, b = normalize(a), normalize(b)
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = [-x for x in b], -dot
    dot = max(-1., min(1., dot))
    if dot > .9995:
        return normalize([x + (y - x) * t for x, y in zip(a, b)])
    angle = math.acos(dot)
    a_weight = math.sin((1 - t) * angle) / math.sin(angle)
    b_weight = math.sin(t * angle) / math.sin(angle)
    return [x * a_weight + y * b_weight for x, y in zip(a, b)]


def sample(channel, time, rotation=False):
    times, values = channel['times'], channel['values']
    if time <= times[0]:
        return list(values[0])
    if time >= times[-1]:
        return list(values[-1])
    right = bisect.bisect_right(times, time)
    left = right - 1
    mix = (time - times[left]) / (times[right] - times[left])
    if rotation:
        return slerp(values[left], values[right], mix)
    return [a + (b - a) * mix for a, b in zip(values[left], values[right])]


def read(label):
    return json.loads((ROOT / 'assets/source/motion' / f'{label}.json').read_text(encoding='utf-8'))


def repose(original, donor):
    result = copy.deepcopy(original)
    donor_map = {t['bone']: t for t in donor['tracks']}
    # These bones are common ancestors of both arm chains. No arm/contact path
    # is transferred from a different weapon.
    torso = {'spine1', 'spine2', 'chest', 'neck', 'head'}
    stance = {'root', 'boss', 'boss_aim', 'hips', 'r_thigh', 'r_calf', 'r_foot', 'r_toe',
              'l_thigh', 'l_calf', 'l_foot', 'l_toe', 'l_toe_end', 'r_toe_end'}
    changed = []
    times = [i / FPS for i in range(math.ceil(result['duration'] * FPS))] + [result['duration']]
    for track in result['tracks']:
        bone = track['bone']
        if bone not in donor_map or bone not in torso | stance:
            continue
        changed.append(bone)
        source = donor_map[bone]
        for channel in ('position', 'rotation', 'scale'):
            if channel not in source:
                continue
            if bone in stance:
                values = [sample(source[channel], 0, channel == 'rotation') for _ in times]
            else:
                values = [sample(source[channel], t / result['duration'] * donor['duration'], channel == 'rotation') for t in times]
            track[channel] = {'times': times, 'values': values}
    result['authoring'] = {'method': 'MG43 native arm choreography with upright common-ancestor pose',
        'changedBones': changed, 'armTracks': 'byte-equivalent numeric curves to original before encoding',
        'gameMask': 40, 'gameplayVerification': 'not yet tested in game'}
    return result


def main():
    out = ROOT / 'assets/authored'
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'version': 1, 'resources': []}
    report = []
    for label in ('normal', 'fast'):
        original, donor = read('mg43_' + label), read('stalwart_' + label)
        result = repose(original, donor)
        doc_path = out / f'mg43_upright_{label}.json'
        doc_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        source_hash = {'normal': 'f9761fd85530ae0f', 'fast': 'b72125ac2aa44568'}[label]
        template = (ROOT / 'assets/source/native' / f'{source_hash}.animation').read_bytes()
        native = encode(template, result)
        path = out / f'mg43_upright_{label}.animation'
        path.write_bytes(native)
        decoded = decode(native, result['boneNames'])
        # The preview reads the actual re-encoded file, including float rounding.
        (out / f'mg43_upright_{label}.decoded.json').write_text(json.dumps(decoded), encoding='utf-8')
        name = f'{hash64("content/mods/mg43_mobile_reload/" + label):016x}'
        manifest['resources'].append({'name': name, 'type': 'animation', 'file': str(path.relative_to(ROOT)).replace('\\', '/')})
        originals = {t['bone']: t for t in original['tracks']}
        untouched = [t['bone'] for t in result['tracks'] if t == originals[t['bone']]]
        report.append({'clip': label, 'duration': result['duration'], 'changedBones': result['authoring']['changedBones'],
            'untouchedBones': untouched, 'nativeBytes': len(native), 'resource': name})
    (out / 'resources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (out / 'authoring-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{'clip': x['clip'], 'changedBones': len(x['changedBones']), 'untouchedBones': len(x['untouchedBones']), 'nativeBytes': x['nativeBytes']} for x in report]))


if __name__ == '__main__':
    main()
