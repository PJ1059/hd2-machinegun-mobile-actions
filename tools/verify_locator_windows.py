"""Exercise actual Win32 calls on this test VM's allocation, never the game."""
import json
import os

from build_runtime_addon import ROOT, source, lua


def main():
    os.environ.setdefault('HD2_GAME_ROOT', 'G:/SteamLibrary/steamapps/common/Helldivers 2')
    from lua_offline import execute
    records = []
    entities = (ROOT.parent / 'spore-map/vendor/filediver/datalibrary/generated_entities.dl_bin').read_bytes()
    for addon in ('mg43', 'm1000'):
        body, profile, _ = source(addon)
        offset = profile['component_offset']
        framing = entities[offset - 4:offset + 28 + profile['indices'] * 16]
        # Replace only the executable identity check: the Lua VM is in Python,
        # and all queried/read/written target bytes are allocated by this fixture.
        actual = body.decode().replace('local memory = make_memory().new(runtime)',
            'local memory = make_memory().new(runtime)\nmemory.verify_build=function()return true end')
        for split in (False, True):
            prefix = r'''
local ffi=require('ffi')
ffi.cdef[[
 void *movement_test_Alloc(void *,size_t,uint32_t,uint32_t) __asm__("VirtualAlloc");
 int movement_test_Free(void *,size_t,uint32_t) __asm__("VirtualFree");
 int movement_test_Protect(void *,size_t,uint32_t,uint32_t *) __asm__("VirtualProtect");
]]
local windows=ffi.load('kernel32')
local p=PROFILE
local allocation=windows.movement_test_Alloc(nil,p.entity_region_size,0x3000,4)
assert(allocation~=nil,'test allocation failed')
local bytes=ffi.cast('uint8_t *',allocation)
local function unhex(s)return(s:gsub('..',function(v)return string.char(tonumber(v,16))end))end
ffi.copy(bytes,unhex(p.map_header),28)
ffi.copy(bytes+p.component_offset-4,unhex(FRAMING),FRAMING_LENGTH)
local record=p.component_offset+28+p.record_offset+p.record_index*p.stride
ffi.copy(bytes+record,unhex(p.record_hex),p.stride)
local old=ffi.new('uint32_t[1]')
assert(windows.movement_test_Protect(allocation,p.entity_region_size,2,old)~=0)
if SPLIT then assert(windows.movement_test_Protect(bytes+4096,4096,4,old)~=0)end
update=function()end
'''.replace('PROFILE', lua(profile)).replace('FRAMING_LENGTH', str(len(framing))).replace('FRAMING', lua(framing.hex())).replace('SPLIT', 'true' if split else 'false')
            suffix = r'''
local ok,why=pcall(function()
 local state=run_addon()
 for frame=1,10000 do
  update(0.016)
  if state.status=='active' or state.status=='failed' then break end
 end
 assert(state.status=='active',tostring(state.error)..'; status='..state.status)
 assert(state.writes==1 and bytes[record+p.field_offset]==p.after)
 assert(ffi.string(bytes+record,p.field_offset)==unhex(p.record_hex):sub(1,p.field_offset))
 assert(ffi.string(bytes+record+p.field_offset+1,p.stride-p.field_offset-1)==unhex(p.record_hex):sub(p.field_offset+2))
 state.close()
 assert(state.restored and ffi.string(bytes+record,p.stride)==unhex(p.record_hex))
end)
assert(windows.movement_test_Free(allocation,0,0x8000)~=0)
assert(ok,why)
return 'actual Win32 query/read/protect/write/restore; private fixture allocation freed'
'''
            value = execute((prefix + '\nlocal function run_addon()\n' + actual + '\nend\n' + suffix).encode()).decode()
            records.append({'addon': addon, 'splitProtection': split, 'result': value})
    report = {'passed': True, 'gameProcessAccess': False, 'cases': records}
    (ROOT / 'build/locator-windows-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
