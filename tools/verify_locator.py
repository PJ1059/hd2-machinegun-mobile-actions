"""Regression fixtures for entity discovery. Own Lua memory only; no game access."""
import argparse
import json
import os

from build_runtime_addon import ROOT, source, verify_offline, lua


def run(expect_broken=False):
    os.environ.setdefault('HD2_GAME_ROOT', 'G:/SteamLibrary/steamapps/common/Helldivers 2')
    from lua_offline import execute
    scenarios = {
        'split_allocation': '''
kernel.VirtualQuery=function(at,region,size)
 if at<base then set(region,0,base,false)
 elseif at<base+4096 then set(region,base,4096,true)
 elseif at<base+p.entity_region_size then
  set(region,base+4096,p.entity_region_size-4096,true)
  region.allocation_base_low=base%4294967296
  region.allocation_base_high=math.floor(base/4294967296)
 else set(region,base+p.entity_region_size,0x800000000000-base-p.entity_region_size,false)end
 return size end
''',
        'larger_allocation': '''
kernel.VirtualQuery=function(at,region,size)
 if at<base then set(region,0,base,false)
 elseif at<base+p.entity_region_size+4096 then set(region,base,p.entity_region_size+4096,true)
 else set(region,base+p.entity_region_size+4096,0x800000000000-base-p.entity_region_size-4096,false)end
 return size end
''',
        'table_loaded_later': '''
ffi.fill(buffer,28,0)
''',
        'query_error': '''
kernel.VirtualQuery=function()error('fixture native query failure')end
''',
        'table_absent': '''
ffi.fill(buffer,28,0)
''',
    }
    duplicate_setup = '''
local duplicate=ffi.new('uint8_t[?]',p.entity_region_size)
ffi.copy(duplicate,buffer,p.entity_region_size)
local duplicate_base=tonumber(ffi.cast('uintptr_t',duplicate))
local allocations={base,duplicate_base};table.sort(allocations)
kernel.VirtualQuery=function(at,region,size)
 local previous=0
 for _,start in ipairs(allocations)do
  if at<start then set(region,previous,start-previous,false);return size end
  if at<start+p.entity_region_size then set(region,start,p.entity_region_size,true);return size end
  previous=start+p.entity_region_size
 end
 set(region,previous,0x800000000000-previous,false);return size end
'''
    scenarios['duplicate_valid_tables'] = duplicate_setup
    scenarios['header_decoy'] = duplicate_setup + 'duplicate[record+4]=(duplicate[record+4]+1)%256\n'
    results = []
    for addon in ('mg43', 'm1000'):
        body, data, _ = source(addon)
        fixture = verify_offline(body, data, return_fixture=True)
        environment, rest = fixture.split('\nlocal function run_addon()\n', 1)
        actual = rest.split('\nend\n\nlocal result=run_addon()', 1)[0]
        if expect_broken:
            actual = (ROOT / 'build/history/addon-v0.2.0.lua').read_text(encoding='utf-8')
            actual = (actual.replace('__BINGUS_RUNTIME__', '''return {guard=function(options)
 return {install=function()fixture_step=options.step end,stop=function()options.stop()end}end}''')
                .replace('__BINGUS_MEMORY__', 'return {new=function()return fixture_memory end}')
                .replace('__PROFILE__', lua(data)).replace('__ADDON_RESOURCE__', data['addon_resource'])
                .replace("local windows = ffi.load('kernel32')", 'local windows = fixture_windows'))
        for name, setup in scenarios.items():
            clock = '''
local fixture_clock=0
fixture_memory.time=function()return fixture_clock end
'''
            assertion = '''
local result=run_addon()
for frame=1,2000 do
 fixture_clock=fixture_clock+0.05
 if SCENARIO=='table_loaded_later' and fixture_clock>1 then ffi.copy(buffer,unhex(p.map_header),28)end
 fixture_step()
 if result.status=='active' or result.status=='failed' then break end
end
local expected_active=SCENARIO~='query_error' and SCENARIO~='table_absent' and SCENARIO~='duplicate_valid_tables' and not EXPECT_BROKEN
assert((result.status=='active')==expected_active,result.status..': '..tostring(result.error))
if expected_active then
 assert(writes==1 and buffer[record+p.field_offset]==p.after)
 result.close();assert(writes==2 and buffer[record+p.field_offset]==p.before)
else
 assert(writes==0)
 if not EXPECT_BROKEN then
  if SCENARIO=='query_error' then assert(result.error:find('query failed',1,true),result.error)
  elseif SCENARIO=='duplicate_valid_tables' then assert(result.error:find('ambiguous verified',1,true),result.error)
  else assert(result.error:find('scans=5',1,true),result.error)end
 end
end
return result.status..'|'..tostring(result.error)
'''.replace('SCENARIO', json.dumps(name)).replace('EXPECT_BROKEN', 'true' if expect_broken else 'false')
            script = environment + clock + setup + '\nlocal function run_addon()\n' + actual + '\nend\n' + assertion
            result = execute(script.encode()).decode()
            results.append({'addon': addon, 'scenario': name, 'result': result})
    report = {'expectedBroken': expect_broken, 'passed': True, 'gameProcessAccess': False, 'cases': results}
    out = ROOT / ('build/locator-before-fix.json' if expect_broken else 'build/locator-verification.json')
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expect-broken', action='store_true')
    run(parser.parse_args().expect_broken)
