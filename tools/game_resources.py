"""Read installed HD2 slim archives. Writes only explicitly requested project exports."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / 'runtime-interface-lab/HD2Runtime/scripts'))
import hd2_game_data as gd

GAME = Path('G:/SteamLibrary/steamapps/common/Helldivers 2')
AVATAR = 0x4D1C334D294DFA97
AVATAR_ARCHIVE = '18235e0c9ec0e636'


def lz4(src: bytes, size: int) -> bytes:
    """Same LZ4 block format as the existing reader, using bulk overlap copies."""
    dst = bytearray(size)
    s = d = 0
    while s < len(src):
        token = src[s]
        s += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[s]
                s += 1
                lit += b
                if b != 255:
                    break
        dst[d:d + lit] = src[s:s + lit]
        s += lit
        d += lit
        if s >= len(src):
            break
        off = src[s] | src[s + 1] << 8
        s += 2
        match = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                b = src[s]
                s += 1
                match += b
                if b != 255:
                    break
        if not 0 < off <= d:
            raise ValueError('Invalid LZ4 back reference')
        while match:
            n = min(match, off)
            dst[d:d + n] = dst[d - off:d - off + n]
            d += n
            match -= n
    if d != size:
        raise ValueError(f'LZ4 decoded {d}, expected {size}')
    return bytes(dst)


gd.lz4_block = lz4
gd.chunk = lru_cache(maxsize=64)(gd.chunk)


def hash64(name: str) -> int:
    return gd.murmur64(name.encode())


def u32(data, at):
    return struct.unpack_from('<I', data, at)[0]


class GameResources:
    def __init__(self, game=GAME):
        self.data = gd.Data(str(Path(game) / 'data'))
        self._archives = {}
        self.names = {}
        self.thin = {}
        hashes = WORKSPACE / 'spore-map/vendor/filediver/hashes'
        for line in (hashes / 'hashes.txt').read_text(encoding='utf-8').splitlines():
            if line and not line.startswith('//'):
                self.names[hash64(line)] = line
        for line in (hashes / 'thinhashes.txt').read_text(encoding='utf-8').splitlines():
            if line and not line.startswith('//'):
                self.thin[hash64(line) >> 32] = line

    def entries(self, archive):
        if archive not in self._archives:
            head = self.data.item_bytes(archive, 0, 72)
            types, files = struct.unpack_from('<II', head, 4)
            raw = self.data.item_bytes(archive, 72 + 32 * types, 80 * files)
            self._archives[archive] = list(struct.iter_unpack('<7Q6I', raw))
        return self._archives[archive]

    def resource(self, name: int | str, kind: str, archive=AVATAR_ARCHIVE):
        if isinstance(name, str):
            name = int(name, 16) if len(name.removeprefix('0x')) == 16 else hash64(name)
        kt = hash64(kind)
        found = next((e for e in self.entries(archive) if e[:2] == (name, kt)), None)
        if found is not None:
            return self.data.read(archive, (found[2], found[7]))
        ar, part, _, _ = self.data.find({(name, kt)})[(name, kt)]
        return self.data.read(ar, part)

    def dump(self, name: int | str, kind: str):
        number = int(name, 16) if isinstance(name, str) else name
        path = ROOT / 'assets/source/native' / f'{number:016x}.{kind}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.resource(number, kind))
        return path

    def bones(self, resource=AVATAR):
        raw = self.resource(resource, 'bones')
        count, unknown = struct.unpack_from('<II', raw)
        hashes = list(struct.unpack_from(f'<{count}I', raw, 8 + 4 * unknown))
        names = [n.decode() for n in raw[8 + 8 * unknown + 4 * count:].split(b'\0')[:count]]
        return names, hashes

    def states(self, resource=AVATAR):
        raw = self.resource(resource, 'state_machine')
        groups_at = u32(raw, 8)
        groups = struct.unpack_from(f'<{u32(raw, groups_at)}I', raw, groups_at + 4)
        layers = []
        for go in groups:
            group = groups_at + go
            offsets = struct.unpack_from(f'<{u32(raw, group + 8)}I', raw, group + 12)
            states = []
            for offset in offsets:
                at = group + offset
                name = struct.unpack_from('<Q', raw, at)[0]
                ac, ao = struct.unpack_from('<II', raw, at + 12)
                anims = list(struct.unpack_from(f'<{ac}Q', raw, at + ao)) if ac else []
                ec, eo, lc, lo = struct.unpack_from('<4I', raw, at + 40)
                events = {}
                for i in range(ec):
                    event, link = struct.unpack_from('<Ii', raw, at + eo + 8 * i)
                    if 0 <= link < lc:
                        target, blend, typ, beat = struct.unpack_from('<IfII', raw, at + lo + 16 * link)
                        events[self.thin.get(event, f'{event:08x}')] = {'target': target, 'blend': blend, 'type': typ}
                states.append({'name': self.names.get(name, f'{name:016x}'), 'offset': at,
                    'type': u32(raw, at + 8), 'animations': anims,
                    'mask': struct.unpack_from('<i', raw, at + 108)[0],
                    'additive': bool(u32(raw, at + 36)), 'events': events})
            layers.append({'default': u32(raw, group + 4), 'states': states})
        masks_at = u32(raw, 32)
        masks = []
        if masks_at:
            offsets = struct.unpack_from(f'<{u32(raw, masks_at)}I', raw, masks_at + 4)
            for offset in offsets:
                at = masks_at + offset
                masks.append(list(struct.unpack_from(f'<{u32(raw, at)}f', raw, at + 4)))
        return layers, masks


if __name__ == '__main__':
    resources = GameResources()
    names, _ = resources.bones()
    layers, masks = resources.states()
    for index, layer in enumerate(layers):
        default = layer['states'][layer['default']]
        print(json.dumps({'layer': index, 'count': len(layer['states']), 'default': layer['default'],
            'defaultName': default['name'], 'animations': [f'{a:016x}' for a in default['animations']],
            'defaultEvents': {k: v['target'] for k, v in default['events'].items()
                if any(s in k for s in ('stand', 'walk', 'crouch', 'prone', 'move', 'reload_mg'))}}, ensure_ascii=False))
