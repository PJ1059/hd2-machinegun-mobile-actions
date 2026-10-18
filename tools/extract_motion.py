"""Extract only the original motion needed for the authored reload and preview."""
from __future__ import annotations

import json
from game_resources import GameResources, ROOT
from native_animation import decode


def main():
    r = GameResources()
    bones, _ = r.bones()
    layers, masks = r.states()
    clips = {'mg43_normal': 'f9761fd85530ae0f', 'mg43_fast': 'b72125ac2aa44568',
             'stalwart_normal': '32622f93493bfd25', 'stalwart_fast': '4f77ddf9f7b1621e',
             'idle': 'b726036661e01b81', 'sprint': '0f93b8bf901345ea'}
    for i, name in enumerate(layers[0]['states'][86]['animations']):
        clips[f'walk_{i}'] = f'{name:016x}'
    out = ROOT / 'assets/source/motion'
    out.mkdir(parents=True, exist_ok=True)
    for label, name in clips.items():
        source = r.dump(name, 'animation')
        document = decode(source.read_bytes(), bones)
        (out / (label + '.json')).write_text(json.dumps(document), encoding='utf-8')
    weapon_bones, _ = r.bones(0x11C27D3BABB38956)
    for label, name in {'weapon_normal': '43b6c6c281fe5434', 'weapon_fast': '716bb3dc847b7dcf'}.items():
        source = r.dump(name, 'animation')
        document = decode(source.read_bytes(), weapon_bones)
        (out / (label + '.json')).write_text(json.dumps(document), encoding='utf-8')
    ref = ROOT / 'reference/source-clips.json'
    ref.parent.mkdir(exist_ok=True)
    ref.write_text(json.dumps({'clips': clips, 'bones': bones, 'masks': {'stalwart': masks[40]},
        'standingStates': {'mg43': [600, 601], 'stalwart': [750, 751]},
        'proneStates': {'mg43': [214, 215], 'stalwart': [366, 367]}}, indent=2), encoding='utf-8')
    print(f'Extracted {len(clips) + 2} clips; no game files changed.')


if __name__ == '__main__':
    main()
