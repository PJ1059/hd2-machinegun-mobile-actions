"""Build only the independent M1000 movement addon; root owns final packaging."""
from pathlib import Path
import hashlib
import json

from build_runtime_addon import (ROOT, ARCHIVE_NAME, resource_hash, lua_resource, make_archive,
                                 read_archive, source, verify_offline, verify_pair_offline)


def main():
    body, data, vendors = source('m1000')
    checks = verify_offline(body, data)
    coexistence = verify_pair_offline()
    resource = data['addon_resource']
    payload = lua_resource(body)
    archive = make_archive({resource_hash(resource): payload})
    reread = read_archive(archive)
    if reread != {(resource_hash('lua'), resource_hash(resource)): (payload, b'')}:
        raise ValueError('M1000 archive readback failed')
    report = {
        'name': 'M1000 mobile firing switch', 'build': '25480438', 'resource': resource,
        'resourceHash': f'{resource_hash(resource):016x}', 'globalKey': data['global_key'],
        'guardName': data['guard_name'], 'sourceSha256': hashlib.sha256(body).hexdigest(),
        'entity': data['resource'], 'component': data['component_name'],
        'recordIndex': data['record_index'], 'indexRow': data['index_row'], 'stride': data['stride'],
        'field': data['field_name'], 'fieldOffset': data['field_offset'],
        'before': data['before'], 'after': data['after'], 'changedBytes': 1,
        'unchangedOtherRecordBytes': data['stride'] - 1,
        'rateOfFireChanged': False, 'damageChanged': False, 'spinupChanged': False,
        'animationEventsChanged': False, 'requires': 'Bingus Shared Loader API 1',
        'vendorSha256': vendors, 'offlineChecks': checks,
        'realBingusCoreCoexistenceChecks': coexistence, 'archiveReadback': True,
        'deployed': False, 'liveGameTested': False, 'finalManifest': 'owned by root packaging',
    }
    folder = ROOT / 'dist/m1000-mobile-fire'
    addon = folder / 'Addon'
    addon.mkdir(parents=True, exist_ok=True)
    (addon / ARCHIVE_NAME).write_bytes(archive)
    (addon / (ARCHIVE_NAME + '.stream')).write_bytes(b'')
    (addon / (ARCHIVE_NAME + '.gpu_resources')).write_bytes(b'')
    (folder / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    (ROOT / 'build').mkdir(exist_ok=True)
    (ROOT / 'build/m1000-mobile-fire.lua').write_bytes(body)
    print(json.dumps({'output': str(folder), **report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
