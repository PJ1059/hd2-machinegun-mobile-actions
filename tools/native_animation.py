"""Read and write HD2 native animation curves without Blender.

Coordinates are native bone-local, Z-up. Quaternions are x, y, z, w.
The codec follows xypwn/filediver stingray/animation/animation.go. The
uncompressed key encoder follows HD2SDK Community Edition animation.py.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct


class AnimationError(ValueError):
    pass


def _quat(word):
    values = [(((word >> shift) & 1023) - 512) / 512 * .75 for shift in (2, 12, 22)]
    largest = word & 3
    result = [0.] * 4
    result[largest] = math.sqrt(max(0., 1 - sum(v * v for v in values)))
    for offset, value in enumerate(values, 1):
        result[(largest + offset) % 4] = value
    return result


def _half_scale(raw):
    return [1. if math.isnan(v) else 1. + v for v in struct.unpack('<3e', raw)]


class _Reader:
    def __init__(self, data, offset=0):
        self.data, self.pos = bytes(data), offset

    def take(self, size):
        result = self.data[self.pos:self.pos + size]
        if len(result) != size:
            raise AnimationError(f'Truncated animation at byte {self.pos}, need {size}')
        self.pos += size
        return result

    def get(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))


def _parse(data, offset=0):
    r = _Reader(data, offset)
    unknown, count, duration, size, hash_count, beat_count = r.get('IIfIII')
    if count > 10000 or hash_count > 10000 or beat_count > 10000 or not math.isfinite(duration):
        raise AnimationError('Implausible native animation header')
    hashes = r.take(hash_count * 8)
    beats = [{'time': time, 'hash': f'{name:08x}'} for time, name in (r.get('fI') for _ in range(beat_count))]
    unknown2 = r.take(2)
    compression = r.take(((count * 3 + 7) // 8 + 1) // 2 * 2)
    initial = []
    initial_raw = []
    additive = []
    for bone in range(count):
        channels, raws = {}, {}
        is_additive = False
        for channel, bit, floats in (('position', 0, 3), ('rotation', 1, 4), ('scale', 2, 3)):
            index = bone * 3 + bit
            compressed = bool(compression[index // 8] & (1 << (index % 8)))
            raw = r.take((4 if channel == 'rotation' else 6) if compressed else floats * 4)
            if compressed and channel == 'position':
                value = [(v - 32767) * (10. / 32767) for v in struct.unpack('<3H', raw)]
            elif compressed and channel == 'rotation':
                value = _quat(struct.unpack('<I', raw)[0])
            elif compressed:
                value = _half_scale(raw)
                is_additive = any(math.isnan(v) for v in struct.unpack('<3e', raw))
            else:
                value = list(struct.unpack('<' + str(floats) + 'f', raw))
                if channel == 'scale':
                    is_additive = any(math.isnan(v) for v in value)
                    value = [1. if math.isnan(v) else v for v in value]
            channels[channel] = value
            raws[channel] = {'compressed': compressed, 'data': raw}
        initial.append(channels)
        initial_raw.append(raws)
        additive.append(is_additive)
    hash_floats = r.take(hash_count * 4)
    prefix_end = r.pos
    entries = []
    while True:
        start = r.pos
        kind, = r.get('H')
        entry_type = kind >> 14
        if entry_type:
            bottom, = r.get('H')
            bone = (kind & 0x3ff0) >> 4
            time = (((kind & 15) << 16) | bottom) / 1000.
            channel = {1: 'scale', 2: 'position', 3: 'rotation'}[entry_type]
            if entry_type == 3:
                value = _quat(r.get('I')[0])
            elif entry_type == 2:
                value = [(v - 32767) * (10. / 32767) for v in r.get('3H')]
            else:
                value = _half_scale(r.take(6))
        else:
            if kind == 3:
                trailer, = r.get('I')
                break
            bone, time = r.get('If')
            if kind == 2:
                channel, value = None, None
            elif kind in (4, 5, 6):
                channel = {4: 'position', 5: 'rotation', 6: 'scale'}[kind]
                value = list(r.get('4f' if kind == 5 else '3f'))
            else:
                raise AnimationError(f'Unknown native key subtype {kind} at byte {start}')
        if channel and bone >= count:
            raise AnimationError(f'Key bone {bone} exceeds header bone count {count}')
        entries.append({'bone': bone, 'time': time, 'channel': channel, 'value': value, 'raw': r.data[start:r.pos]})
    return {'unknown': unknown, 'bone_count': count, 'duration': duration, 'size': size,
            'hash_count': hash_count, 'beat_count': beat_count, 'hashes': hashes, 'beats': beats,
            'unknown2': unknown2, 'compression': compression, 'initial': initial,
            'initial_raw': initial_raw, 'additive': additive, 'hash_floats': hash_floats,
            'prefix_end': prefix_end, 'entries': entries, 'end': r.pos, 'trailer': trailer}


def decode(data: bytes, bone_names=None) -> dict:
    """Decode native bytes into editable JSON-compatible, native-local tracks."""
    parsed = _parse(data)
    count = parsed['bone_count']
    names = list(bone_names) if bone_names is not None else [str(i) for i in range(count)]
    if len(names) != count:
        raise AnimationError(f'Expected {count} bone names, got {len(names)}')
    tracks = [{'bone': name, **{channel: {'times': [0.], 'values': [value]}
               for channel, value in initial.items()}} for name, initial in zip(names, parsed['initial'])]
    for entry in parsed['entries']:
        if entry['channel'] is None:
            continue
        channel = tracks[entry['bone']][entry['channel']]
        if channel['times'][-1] == entry['time']:
            channel['values'][-1] = entry['value']
        else:
            channel['times'].append(entry['time'])
            channel['values'].append(entry['value'])
    return {'boneNames': names, 'duration': parsed['duration'], 'tracks': tracks,
            'additive': parsed['additive'], 'beats': parsed['beats']}


def _channel_entries(bone, channel, track):
    times, values = track['times'], track['values']
    if len(times) != len(values) or not times:
        raise AnimationError(f'Invalid {channel} track for bone {bone}')
    subtype, width = {'position': (4, 3), 'rotation': (5, 4), 'scale': (6, 3)}[channel]
    previous = -1.
    result = []
    for time, value in zip(times, values):
        if not math.isfinite(time) or time < 0 or time < previous:
            raise AnimationError('Track times must be finite, nonnegative, and sorted')
        if len(value) != width or not all(math.isfinite(v) for v in value):
            raise AnimationError(f'Invalid {channel} value')
        previous = time
        result.append((time, struct.pack('<HIf' + str(width) + 'f', subtype, bone, time, *value)))
    return result


def encode(template: bytes, document: dict) -> bytes:
    """Replace supplied channels; retain original event bytes and native metadata.

    Curves use supported uncompressed keys. Initial transforms, including the
    NaN additive markers, remain byte-identical. A key at time zero overrides
    the corresponding initial transform for playback. Unspecified channels
    retain their original encoded keys.
    """
    parsed = _parse(template)
    names = document.get('boneNames', [str(i) for i in range(parsed['bone_count'])])
    if len(names) != parsed['bone_count'] or len(set(names)) != len(names):
        raise AnimationError('boneNames must match the template bone count and be unique')
    index = {name: bone for bone, name in enumerate(names)}
    replacements = {}
    generated = []
    duration = float(document.get('duration', parsed['duration']))
    if duration <= 0 or not math.isfinite(duration):
        raise AnimationError('Animation duration must be positive')
    for track in document.get('tracks', []):
        name = track['bone']
        bone = index[name] if name in index else name if isinstance(name, int) else None
        if bone is None or bone < 0 or bone >= parsed['bone_count']:
            raise AnimationError(f'Unknown bone {name!r}')
        for channel in ('position', 'rotation', 'scale'):
            if channel in track:
                if (bone, channel) in replacements:
                    raise AnimationError(f'Duplicate channel {name}/{channel}')
                replacements[bone, channel] = track[channel]
                generated.extend(_channel_entries(bone, channel, track[channel]))
    for entry in parsed['entries']:
        if entry['channel'] is None or (entry['bone'], entry['channel']) not in replacements:
            generated.append((entry['time'], entry['raw']))
    if generated and max(time for time, _ in generated) > duration + .01:
        raise AnimationError('Keys extend beyond animation duration')
    prefix = bytearray(template[:parsed['prefix_end']])
    struct.pack_into('<f', prefix, 8, duration)
    # Preserve native beat hashes, optionally retime explicit beat timestamps.
    if 'beats' in document:
        beats = document['beats']
        if len(beats) != parsed['beat_count']:
            raise AnimationError('Beat count must match template')
        offset = 24 + parsed['hash_count'] * 8
        for beat, original in zip(beats, parsed['beats']):
            if str(beat.get('hash', original['hash'])).lower() != original['hash']:
                raise AnimationError('Beat hashes must remain unchanged')
            struct.pack_into('<f', prefix, offset, float(beat['time']))
            offset += 8
    keys = b''.join(raw for _, raw in sorted(generated, key=lambda item: item[0]))
    # Native resources usually contain two identical playback blocks. Preserve
    # that topology, and retain any unknown suffix after the final block.
    block_without_trailer = bytes(prefix) + keys + struct.pack('<H', 3)
    block_length = len(block_without_trailer) + 4
    block = block_without_trailer + struct.pack('<I', block_length - 4)
    tail = template[parsed['end']:]
    duplicated = False
    if len(tail) >= 24:
        try:
            other = _parse(tail)
            duplicated = other['unknown'] == parsed['unknown'] and other['bone_count'] == parsed['bone_count']
        except (AnimationError, struct.error):
            duplicated = False
    if duplicated:
        tail = tail[other['end']:]
        result = bytearray(block + block + tail)
        struct.pack_into('<I', result, 12, len(result))
        # The second playback copy reserves this field as zero in game files.
        struct.pack_into('<I', result, block_length + 12, other['size'])
    else:
        result = bytearray(block + tail)
        struct.pack_into('<I', result, 12, len(result))
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    dec = sub.add_parser('decode')
    dec.add_argument('source', type=Path)
    dec.add_argument('output', type=Path)
    dec.add_argument('--bones', type=Path)
    enc = sub.add_parser('encode')
    enc.add_argument('template', type=Path)
    enc.add_argument('tracks', type=Path)
    enc.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'decode':
        names = json.loads(args.bones.read_text('utf-8')) if args.bones else None
        document = decode(args.source.read_bytes(), names)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, ensure_ascii=False), 'utf-8')
        print(f"Decoded {len(document['tracks'])} bones, {document['duration']:.3f} seconds")
    else:
        result = encode(args.template.read_bytes(), json.loads(args.tracks.read_text('utf-8')))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(result)
        print(f'Encoded {len(result)} native bytes; not installed in game')


if __name__ == '__main__':
    main()
