"""Build the separate one-byte movement addon, offline. Never installs it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / 'runtime-interface-lab/HD2Runtime/scripts'))
from hd2_archive import (ARCHIVE_NAME, make_archive, resource_hash, lua_resource,
                         make_resource_archive, read_archive)

RESOURCE = 'mods/hd2_local/mg43_mobile_reload'
ENTITY_HASH = 0x11C27D3BABB38956
ADDONS = {
    'mg43': {'addon_resource': RESOURCE, 'global_key': 'MG43MobileReloadV1',
             'guard_name': 'MG43MobileReload', 'component_name': 'WeaponReloadComponentData',
             'entity_hash': ENTITY_HASH, 'field_name': 'ReloadAllowMove',
             'field_offset': 1, 'before': 0, 'after': 1, 'expected_row': 308, 'expected_record': 235},
    'm1000': {'addon_resource': 'mods/hd2_local/m1000_mobile_fire', 'global_key': 'M1000MobileFireV1',
              'guard_name': 'M1000MobileFire', 'component_name': 'WeaponDataComponentData',
              'entity_hash': 0x43A58CB89CFA197C, 'field_name': 'stationary_while_firing',
              'field_offset': 387, 'before': 1, 'after': 0, 'expected_row': 116, 'expected_record': 348},
}


def lua(value):
    if isinstance(value, dict):
        return '{' + ','.join('[' + lua(k) + ']=' + lua(v) for k, v in value.items()) + '}'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def profile(addon='mg43'):
    spec = ADDONS[addon]
    runtime = WORKSPACE / 'runtime-interface-lab/HD2Runtime'
    builds = json.loads((runtime / 'schemas/build_profile.json').read_text('utf-8'))
    build = builds['builds'][builds['active']]
    schema = (runtime / 'schemas/current.lua').read_text('utf-8')
    component = re.search(r'\["' + re.escape(spec['component_name']) + r'"\]=\{([^}]+)\}', schema).group(1)
    fields = dict(re.findall(r'\["([^"]+)"\]=("[^"]*"|\d+)', component))
    fields = {key: json.loads(value) for key, value in fields.items()}
    entities = (WORKSPACE / 'spore-map/vendor/filediver/datalibrary/generated_entities.dl_bin').read_bytes()
    if hashlib.sha256(entities).hexdigest().upper() != build['datalibrary']['entitiesSha256']:
        raise ValueError('Entity reference does not match the active build')
    offset = fields['offset']
    if entities[offset:offset + 28] != bytes.fromhex(fields['header']):
        raise ValueError('Weapon component framing changed')
    selected = []
    for row in range(fields['indices']):
        name, record, reserved = struct.unpack_from('<QII', entities, offset + 28 + row * 16)
        if name == spec['entity_hash']:
            selected.append((row, record))
    if len(selected) != 1:
        raise ValueError('Weapon ownership absent/ambiguous')
    row, record = selected[0]
    if (row, record) != (spec['expected_row'], spec['expected_record']):
        raise ValueError('Pinned weapon resource mapping changed')
    owners = [n for n in range(fields['indices']) if struct.unpack_from('<QII', entities,
        offset + 28 + n * 16)[0] and struct.unpack_from('<I', entities, offset + 28 + n * 16 + 8)[0] == record]
    if len(owners) != 1:
        raise ValueError('Weapon record is shared')
    record_at = offset + 28 + fields['record_offset'] + record * fields['stride']
    raw = entities[record_at:record_at + fields['stride']]
    if raw[spec['field_offset']] != spec['before']:
        raise ValueError('Weapon movement baseline changed')
    if addon == 'mg43' and (struct.unpack_from('<I', raw, 4)[0] != 2811
                            or struct.unpack_from('<f', raw, 56)[0] != 4.5):
        raise ValueError('MG43 reload baseline changed')
    return {'exe_sha256': build['exeSha256'], 'game_sha256': build['gameDllSha256'],
            'entity_size': len(entities), 'entity_region_size': (len(entities) + 4095) // 4096 * 4096,
            'map_header': entities[:28].hex(),
            'component_offset': offset, 'component_index': fields['index'],
            'component_header': fields['header'], 'indices': fields['indices'],
            'records': fields['records'], 'record_offset': fields['record_offset'], 'stride': fields['stride'],
            'resource': f'{spec["entity_hash"]:016x}', 'index_row': row, 'record_index': record,
            'record_hex': raw.hex(), **{key: spec[key] for key in (
                'addon_resource', 'global_key', 'guard_name', 'component_name',
                'field_name', 'field_offset', 'before', 'after')}}


def render_template(data, runtime_source, memory_source):
    text = (ROOT / 'src/addon.lua').read_text('utf-8')
    return (text.replace('__BINGUS_RUNTIME__', runtime_source).replace('__BINGUS_MEMORY__', memory_source)
            .replace('__PROFILE__', lua(data)).replace('__ADDON_RESOURCE__', data['addon_resource']))


def source(addon='mg43'):
    # The existing inspected source resource vendors byte-identical upstream v1
    # helpers. Embed those small helpers without bundling the HD2Runtime SDK.
    reference = (WORKSPACE / 'mod-menu-zh-cn/reference/fd50351f21814b0e.lua').read_text('utf-8')
    modules = {}
    for name in ('bingus_runtime', 'bingus_memory'):
        marker = f'mom_files.{name} = function(...)\n'
        begin = reference.index(marker) + len(marker)
        end = reference.index('\nend\nmom_files.', begin)
        modules[name] = reference[begin:end]
    data = profile(addon)
    text = render_template(data, modules['bingus_runtime'], modules['bingus_memory'])
    if '__BINGUS_' in text or '__PROFILE__' in text:
        raise ValueError('Unresolved build substitution')
    return text.encode('utf-8'), data, {name: hashlib.sha256(value.encode()).hexdigest() for name, value in modules.items()}


def verify_offline(body, data, *, return_fixture=False):
    """Compile in HD2's standalone Lua VM and exercise synthetic memory only."""
    os.environ.setdefault('HD2_GAME_ROOT', 'G:/SteamLibrary/steamapps/common/Helldivers 2')
    from lua_offline import compile_chunk, execute
    compile_chunk(body)
    entities = (WORKSPACE / 'spore-map/vendor/filediver/datalibrary/generated_entities.dl_bin').read_bytes()
    offset = data['component_offset']
    framing = entities[offset - 4:offset + 28 + data['indices'] * 16]
    # Substitute only environmental adapters. The actual record selection,
    # allow-move write, protection restore and addon stop run unchanged.
    text = render_template(data, '''return {guard=function(options)
      return {install=function() fixture_step=options.step end,
              stop=function() options.stop() end} end}''',
        'return {new=function() return fixture_memory end}')
    text = text.replace("local windows = ffi.load('kernel32')", 'local windows = fixture_windows')
    prefix = r'''
local ffi=require('ffi')
ffi.cdef [[typedef struct bingus_memory1_region {
 uint32_t base_low,base_high,allocation_base_low,allocation_base_high;
 uint32_t allocation_protection;uint16_t partition,reserved;
 uint32_t size_low,size_high,state,protection,type,padding;
}bingus_memory1_region;]]
local p=PROFILE_DATA
local function unhex(s)return(s:gsub('..',function(v)return string.char(tonumber(v,16))end))end
local buffer=ffi.new('uint8_t[?]',p.entity_region_size)
local base=tonumber(ffi.cast('uintptr_t',buffer))
ffi.copy(buffer,unhex(p.map_header),28)
ffi.copy(buffer+p.component_offset-4,unhex(FRAMING_DATA),#FRAMING_DATA/2)
local record=p.component_offset+28+p.record_offset+p.record_index*p.stride
ffi.copy(buffer+record,unhex(p.record_hex),p.stride)
local protection=2
local function set(region,at,size,private)
 region.base_low=at%4294967296;region.base_high=math.floor(at/4294967296)
 region.allocation_base_low=region.base_low;region.allocation_base_high=region.base_high
 region.size_low=size%4294967296;region.size_high=math.floor(size/4294967296)
 region.state=private and 0x1000 or 0x10000;region.protection=private and protection or 0
 region.type=private and 0x20000 or 0
end
local kernel={GetCurrentProcess=function()return nil end,
 VirtualQuery=function(at,region,size)
  if at<base then set(region,0,base,false)
  elseif at<base+p.entity_region_size then set(region,base,p.entity_region_size,true)
  else set(region,base+p.entity_region_size,0x800000000000-base-p.entity_region_size,false)end
  return size end}
fixture_memory={windows={ffi=ffi,kernel32=kernel},
 read=function(address,size)return ffi.string(address,size)end,
 verify_build=function()return true end}
local protection_calls,writes=0,0
fixture_windows={hd2_weapon_movement_GetSystemInfo=function(info)
 info.page_size=4096;info.maximum_address=ffi.cast('void *',0x7fffffffffff)end,
 hd2_weapon_movement_VirtualProtect=function(page,size,value,old)
 assert(size==4096);old[0]=protection;protection=value;protection_calls=protection_calls+1;return 1 end,
 hd2_weapon_movement_WriteProcessMemory=function(_,address,bytes,size,count)
 assert(size==1 and tonumber(ffi.cast('uintptr_t',address))==base+record+p.field_offset)
 ffi.copy(address,bytes,size);count[0]=size;writes=writes+1;return 1 end}
'''
    prefix = prefix.replace('PROFILE_DATA', lua(data)).replace('FRAMING_DATA', lua(framing.hex()))
    suffix = r'''
local result=run_addon()
fixture_step()
assert(result.status=='active',result.error)
assert(buffer[record+p.field_offset]==p.after and writes==1 and protection==2 and protection_calls==2)
local expected=unhex(p.record_hex)
local changed=ffi.string(buffer+record,p.stride)
assert(changed:sub(1,p.field_offset)==expected:sub(1,p.field_offset)
 and changed:sub(p.field_offset+2)==expected:sub(p.field_offset+2))
result.close()
assert(result.restored and buffer[record+p.field_offset]==p.before and writes==2
 and protection==2 and protection_calls==4)
assert(ffi.string(buffer+record,p.stride)==expected)
-- A changed duration/ability/event byte must prevent the first write.
rawset(_G,p.global_key,nil)
buffer[record+4]=(buffer[record+4]+1)%256
local refused=run_addon();fixture_step()
assert(refused.status=='failed' and writes==2 and buffer[record+p.field_offset]==p.before)
-- Do not claim or roll back an enable flag already written by another addon.
rawset(_G,p.global_key,nil)
ffi.copy(buffer+record,unhex(p.record_hex),p.stride);buffer[record+p.field_offset]=p.after
local already=run_addon();fixture_step()
assert(already.status=='active' and not already.owned_change and writes==2)
already.close();assert(buffer[record+p.field_offset]==p.after and writes==2)
-- Changing this weapon's row to another record must also refuse writes.
rawset(_G,p.global_key,nil)
ffi.copy(buffer+record,unhex(p.record_hex),p.stride)
local mapping_at=p.component_offset+28+p.index_row*16+8
local mapped=ffi.cast('uint32_t*',buffer+mapping_at)
local previous_mapping=mapped[0];mapped[0]=(previous_mapping+1)%p.records
local wrong=run_addon();fixture_step()
assert(wrong.status=='failed' and writes==2);mapped[0]=previous_mapping
-- Another nonzero resource pointing to the selected record makes it shared.
rawset(_G,p.global_key,nil)
local alias_row=(p.index_row+1)%p.indices
local alias_at=p.component_offset+28+alias_row*16
local alias_old=ffi.string(buffer+alias_at,16)
ffi.fill(buffer+alias_at,16,0);buffer[alias_at]=1
ffi.cast('uint32_t*',buffer+alias_at+8)[0]=p.record_index
local shared=run_addon();fixture_step()
assert(shared.status=='failed' and writes==2)
ffi.copy(buffer+alias_at,alias_old,16)
return 'compile; unique weapon record; one-byte write; readback; page restored; shutdown rollback; changed record refusal; existing enabled setting preserved; wrong record mapping refused; shared record refused'
'''
    fixture = prefix + '\nlocal function run_addon()\n' + text + '\nend\n' + suffix
    if return_fixture:
        return fixture
    return execute(fixture.encode()).decode().split('; ')


def verify_pair_offline():
    """Both real Bingus update guards, with only synthetic memory adapters."""
    from lua_offline import execute
    mg_body, mg, _ = source('mg43')
    _, gatling, _ = source('m1000')
    fixture = verify_offline(mg_body, mg, return_fixture=True)
    environment = fixture.split('\nlocal function run_addon()\n', 1)[0]
    environment = environment.replace('==base+record+p.field_offset)',
        '==base+record+p.field_offset or tonumber(ffi.cast("uintptr_t",address))==pair_address)')
    text = mg_body.decode()
    begin = text.index('local make_runtime = function()\n') + len('local make_runtime = function()\n')
    end = text.index('\nend\nlocal make_memory = function()', begin)
    real_runtime = text[begin:end]
    primary = render_template(mg, real_runtime, 'return {new=function() return fixture_memory end}')
    secondary = render_template(gatling, real_runtime, 'return {new=function() return fixture_memory end}')
    primary = primary.replace("local windows = ffi.load('kernel32')", 'local windows = fixture_windows')
    secondary = secondary.replace("local windows = ffi.load('kernel32')", 'local windows = fixture_windows')
    entities = (WORKSPACE / 'spore-map/vendor/filediver/datalibrary/generated_entities.dl_bin').read_bytes()
    offset = gatling['component_offset']
    frame = entities[offset - 4:offset + 28 + gatling['indices'] * 16]
    extra = '\nlocal second=' + lua(gatling) + '\n'
    extra += 'ffi.copy(buffer+second.component_offset-4,unhex(' + lua(frame.hex()) + '),' + str(len(frame)) + ')\n'
    extra += '''local second_record=second.component_offset+28+second.record_offset+second.record_index*second.stride
ffi.copy(buffer+second_record,unhex(second.record_hex),second.stride)
pair_address=base+second_record+second.field_offset
local previous_calls=0
update=function() previous_calls=previous_calls+1 end
'''
    assertions = '''
local first=run_primary();local second_addon=run_secondary()
update(0.016)
assert(first.status=='active',first.error);assert(second_addon.status=='active',second_addon.error)
assert(buffer[record+p.field_offset]==p.after and buffer[second_record+second.field_offset]==second.after)
assert(writes==2 and protection==2 and previous_calls==1)
assert(BingusRuntime.statuses[p.guard_name]~=BingusRuntime.statuses[second.guard_name])
first.close();update(0.016)
assert(buffer[record+p.field_offset]==p.before and buffer[second_record+second.field_offset]==second.after)
assert(second_addon.status=='active' and writes==3 and previous_calls==2)
second_addon.close();update(0.016)
assert(buffer[second_record+second.field_offset]==second.before and writes==4 and previous_calls==3)
assert(protection==2 and protection_calls==8)
return 'independent resource/global/guard names; both addons active together; original update preserved; closing MG43 preserves M1000; both original bytes restored'
'''
    script = (environment + extra + '\nlocal function run_primary()\n' + primary + '\nend\n'
              + 'local function run_secondary()\n' + secondary + '\nend\n' + assertions)
    return execute(script.encode()).decode().split('; ')


def build_combined():
    """Use the existing Arsenal manifest shape; importing remains untested."""
    visual = ROOT / 'dist/mg43-mobile-reload-visual-prototype'
    movement = ROOT / 'dist/mg43-mobile-reload-movement-prototype'
    if not (visual / 'manifest.json').is_file():
        return None
    asset_report = json.loads((visual / 'manifest.json').read_text('utf-8'))
    runtime_report = json.loads((movement / 'build-report.json').read_text('utf-8'))
    description = ('站立/蹲姿 MG-43 换弹动作及独立移动开关，待实机验证。'
                   '需要另外安装 Bingus Shared Loader（API 1）。本包未部署。')
    manifest = {'Version': 1, 'Guid': '328ebc8a-691a-4a45-8129-c190a7a7c1ed',
                'Name': 'MG-43 自然移动换弹 v0.1 · 测试原型', 'Description': description,
                'Options': [{'Name': '动画与移动开关', 'Description': description,
                             'Include': ['Assets', 'Movement']}]}
    report = {'status': 'offline-prototype-not-game-tested', 'assetValidation': asset_report,
              'movementValidation': runtime_report, 'deployed': False, 'arsenalImportTested': False,
              'dependency': {'name': 'Bingus Shared Loader', 'api': 1, 'bundled': False},
              'manifestFormat': 'Version/Guid/Name/Description/Options Include, matching existing project packages'}
    files = {'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
             'validation-report.json': json.dumps(report, ensure_ascii=False, indent=2).encode(),
             'README.txt': ('MG-43 自然移动换弹 v0.1：测试原型\n\n'
                '包含原生动画/状态机归档与独立一字节移动开关。\n'
                '依赖：Bingus Shared Loader（API 1），本包不捆绑加载器。\n'
                'manifest结构沿用工作区既有Arsenal包；尚未实际导入管理器或进游戏测试。\n'
                '离线验证包括新动画独立解码、归档读回、Lua编译和合成内存写入/回滚。\n'
                'MG-43行为编号2811、时长4.5秒、武器事件和弹药规则未改；原俯卧动画引用保留。\n'
                '后续游戏内需确认新动画加载、移动步态、换弹中断、弹药结算与音画同步。\n'
                '本构建没有安装到游戏，也没有自动启动游戏。\n').encode('utf-8')}
    for part in visual.iterdir():
        if part.is_file() and part.name.startswith('18235e0c9ec0e636.patch_0'):
            files['Assets/' + part.name] = part.read_bytes()
    # The global-resources .package lives in the boot archive, as does the Lua
    # addon. Merge by typed resource ID into ONE boot patch instead of relying
    # on colliding patch names or making a third archive.
    boot = read_archive((movement / 'Addon' / ARCHIVE_NAME).read_bytes())
    package_patch = visual / ARCHIVE_NAME
    if not package_patch.is_file():
        raise ValueError('Global package dependency patch is required before combined build')
    package_resources = read_archive(package_patch.read_bytes())
    if boot.keys() & package_resources.keys():
        raise ValueError('Unexpected overlap between movement addon and package dependency resource')
    boot.update(package_resources)
    boot_main, boot_gpu = make_resource_archive(boot)
    if read_archive(boot_main, boot_gpu) != boot:
        raise ValueError('Merged boot archive readback failed')
    files['Movement/' + ARCHIVE_NAME] = boot_main
    files['Movement/' + ARCHIVE_NAME + '.gpu_resources'] = boot_gpu
    files['Movement/' + ARCHIVE_NAME + '.stream'] = b''
    assets = read_archive(files['Assets/18235e0c9ec0e636.patch_0'])
    global_package_key = (resource_hash('package'), int('18235e0c9ec0e636', 16))
    global_package = boot[global_package_key][0]
    count, = struct.unpack_from('<I', global_package, 8)
    if len(global_package) != 16 + count * 16:
        raise ValueError('Merged global package dependency count/extent mismatch')
    package_items = set(struct.iter_unpack('<QQ', global_package[16:]))
    private_ids = {int(change['animationAfter'], 16) for change in asset_report['stateMachine']['changes']}
    for private_id in private_ids:
        key = (resource_hash('animation'), private_id)
        if key not in package_items or key not in assets:
            raise ValueError('Private animation is absent from native package dependency closure')
    state_machine = assets[(resource_hash('state_machine'), int('4d1c334d294dfa97', 16))][0]
    for change in asset_report['stateMachine']['changes']:
        offset = change['offset']
        clip_count, clip_offset = struct.unpack_from('<II', state_machine, offset + 12)
        clip, = struct.unpack_from('<Q', state_machine, offset + clip_offset)
        mask, = struct.unpack_from('<i', state_machine, offset + 108)
        if clip_count != 1 or clip != int(change['animationAfter'], 16) or mask != 40:
            raise ValueError('Native state references do not match packaged animation dependency closure')
    report['packageDependencyClosure'] = {
        'package': 'packages/content/global_resources', 'sourceArchive': '9ba626afa44a3aa3',
        'declaredItems': count, 'privateAnimations': [f'{v:016x}' for v in sorted(private_ids)],
        'verified': 'state references -> package items -> native animation entries',
        'bootPatchResources': len(boot), 'assetPatchResources': len(assets)}
    files['validation-report.json'] = json.dumps(report, ensure_ascii=False, indent=2).encode()
    if len([name for name in files if '.patch_0' in name]) != 6:
        raise ValueError('Combined package must contain two complete archive triads')
    combined = ROOT / 'dist/MG43-Mobile-Reload-v0.1-offline-prototype.zip'
    with zipfile.ZipFile(combined, 'w', zipfile.ZIP_DEFLATED) as package:
        for name, raw in sorted(files.items()):
            package.writestr(name, raw)
    with zipfile.ZipFile(combined) as package:
        if package.testzip() is not None:
            raise ValueError('Combined ZIP CRC validation failed')
    return str(combined)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--movement-only', action='store_true',
                        help='Refresh only MG43 addon artifacts; leave the historical combined ZIP unchanged')
    args = parser.parse_args(argv)
    body, data, vendor_hashes = source()
    checks = verify_offline(body, data)
    coexistence = verify_pair_offline()
    archive = make_archive({resource_hash(RESOURCE): lua_resource(body)})
    report = {'name': 'MG43 ReloadAllowMove prototype', 'build': '25480438', 'resource': RESOURCE,
              'resourceHash': f'{resource_hash(RESOURCE):016x}', 'sourceSha256': hashlib.sha256(body).hexdigest(),
              'changedBytes': 1, 'recordIndex': data['record_index'], 'indexRow': data['index_row'],
              'fieldOffset': 1, 'before': 0, 'after': 1, 'abilityChanged': False,
              'durationChanged': False, 'vendorSha256': vendor_hashes, 'offlineChecks': checks,
              'globalKey': data['global_key'], 'guardName': data['guard_name'],
              'stride': data['stride'], 'unchangedOtherRecordBytes': data['stride'] - 1,
              'realBingusCoreCoexistenceChecks': coexistence,
              'deployed': False, 'liveGameTested': False}
    manifest = {'Version': 1, 'Guid': '65379eaf-4a8e-44c4-afb3-983f6260871a',
        'Name': 'MG-43 移动换弹开关 · 待实机验证',
        'Description': '仅开启原版 MG-43 的移动换弹字段。配合本项目动画包使用。需要 Bingus Shared Loader API 1。',
        'Options': [{'Name': '开启 MG-43 移动换弹', 'Include': ['Addon']}]}
    readme = ('MG-43 移动换弹开关：原型\n\n'
        '本包没有安装到游戏。需要 Bingus Shared Loader API 1，与动画资产包共同使用。\n'
        '只把标准 MG-43 的 ReloadAllowMove 一字节从0改为1。\n'
        '根据模块指纹、组件表、资源ID、唯一记录及原值定位；关闭时尝试还原自己写入的一字节。\n'
        '不改换弹行为编号、时长、弹药、声音或其他武器。\n'
        '尚未游戏内验证；离线测试不证明实际移动换弹已成功。\n')
    files = {'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
             'Addon/' + ARCHIVE_NAME: archive, 'Addon/' + ARCHIVE_NAME + '.stream': b'',
             'Addon/' + ARCHIVE_NAME + '.gpu_resources': b'',
             'build-report.json': json.dumps(report, ensure_ascii=False, indent=2).encode(),
             'README.txt': readme.encode('utf-8')}
    folder = ROOT / 'dist/mg43-mobile-reload-movement-prototype'
    folder.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (ROOT / 'build').mkdir(exist_ok=True)
    (ROOT / 'build/movement-addon.lua').write_bytes(body)
    path = folder.with_suffix('.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
        for name, raw in files.items():
            package.writestr(name, raw)
    combined = None if args.movement_only else build_combined()
    print(json.dumps({'zip': str(path), 'combinedZip': combined, **report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
