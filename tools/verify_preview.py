"""Check the deliverable motion and that the user's preserved contacts survive."""
import json
import math
import struct

from author_motion import read, sample
from build_preview import load_glb
from game_resources import ROOT
from native_animation import decode


def main():
    report = {'checks': []}
    for label in ('normal', 'fast'):
        original = read('mg43_' + label)
        authored = json.loads((ROOT / f'assets/authored/mg43_upright_{label}.json').read_text())
        actual = decode((ROOT / f'assets/authored/mg43_upright_{label}.animation').read_bytes(), authored['boneNames'])
        changed = set(authored['authoring']['changedBones'])
        actual_map = {t['bone']: t for t in actual['tracks']}
        maximum = 0.
        for before in original['tracks']:
            bone = before['bone']
            if bone in changed:
                continue
            for path in ('position', 'rotation', 'scale'):
                for time, expected in zip(before[path]['times'], before[path]['values']):
                    got = sample(actual_map[bone][path], time, path == 'rotation')
                    maximum = max(maximum, max(abs(a - b) for a, b in zip(expected, got)))
        assert maximum < 2e-5, (label, 'untouched contact curve changed', maximum)
        report['checks'].append({'name': f'{label}: preserved original arm/contact and other unedited curves',
                                 'unchangedBones': len(original['tracks']) - len(changed), 'maxError': maximum})
    doc, binary = load_glb(ROOT / 'assets/preview.glb')
    required = {'MG43_New', 'MG43_New_Walk', 'MG43_New_Run', 'MG43_Original', 'MG43_Original_Walk', 'MG43_Original_Run'}
    clips = {c['name']: c for c in doc['animations']}
    assert set(clips) == required

    def accessor(index):
        a = doc['accessors'][index]
        v = doc['bufferViews'][a['bufferView']]
        offset = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[a['type']]
        return list(struct.unpack_from(f'<{a["count"] * width}f', binary, offset)), width

    max_quat_error = 0.
    thigh = next(i for i, n in enumerate(doc['nodes']) if n.get('name') == 'r_thigh')
    thigh_rotations = {}
    root = next(i for i, n in enumerate(doc['nodes']) if n.get('name') == 'StingrayEntityRoot')
    frozen_roots = 0
    for name, clip in clips.items():
        for channel in clip['channels']:
            assert 0 <= channel['target']['node'] < len(doc['nodes'])
            sampler = clip['samplers'][channel['sampler']]
            times, _ = accessor(sampler['input'])
            values, width = accessor(sampler['output'])
            assert len(values) == len(times) * width and all(math.isfinite(v) for v in values)
            assert times[0] == 0 and abs(times[-1] - 4.5) < 1e-6
            if name in ('MG43_New_Walk', 'MG43_New_Run') and channel['target'] == {'node': root, 'path': 'translation'}:
                assert all(abs(v - values[i % width]) < 1e-6 for i, v in enumerate(values)), 'Locomotion root jumps at gait loop'
                frozen_roots += 1
            if channel['target']['path'] == 'rotation':
                error = max(abs(math.sqrt(sum(x*x for x in values[i:i+4])) - 1) for i in range(0, len(values), 4))
                max_quat_error = max(max_quat_error, error)
                if channel['target']['node'] == thigh:
                    thigh_rotations[name] = values
    assert max_quat_error < .002, max_quat_error
    run_vs_walk = max(abs(a-b) for a,b in zip(thigh_rotations['MG43_New_Run'], thigh_rotations['MG43_New_Walk']))
    assert run_vs_walk > .05, 'Running is missing its independent native gait'
    report['checks'].append({'name': 'Six playable native-derived clips; finite transforms and correct channel dimensions',
                             'maxQuaternionNormError': max_quat_error})
    report['checks'].append({'name': 'Run has independent native leg motion, rather than sped-up walking',
                             'thighCurveDifference': run_vs_walk})
    metadata = json.loads((ROOT / 'assets/preview.json').read_text(encoding='utf-8'))
    assert frozen_roots == 2 and metadata['groundTracksSpace'] == 'world'
    for mode in ('walk', 'run'):
        ground = metadata['groundTracks'][mode]
        assert len(ground['times']) == len(ground['positions'])
        assert abs(ground['times'][-1] - 4.5) < 1e-6
        assert all(math.isfinite(v) for p in ground['positions'] for v in p)
        total = math.dist(ground['positions'][0], ground['positions'][-1])
        assert total > 1, (mode, total)
        max_step = max(math.dist(a, b) for a, b in zip(ground['positions'], ground['positions'][1:]))
        assert max_step < .5, (mode, 'ground jumps at gait loop', max_step)
        report['checks'].append({'name': mode + ': fixed character root and continuous cumulative native ground displacement',
                                 'distanceMetres': total, 'maxFrameDisplacement': max_step})
    report.update(status='passed', gameTested=False)
    out = ROOT / 'build/preview-verification.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
