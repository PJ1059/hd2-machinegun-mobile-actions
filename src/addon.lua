-- HD2-Addon: __ADDON_RESOURCE__
-- One scoped weapon movement byte, selected by the build's pinned profile.
-- The build embeds unmodified Bingus Shared Runtime v1 read/update helpers.
local PROFILE = __PROFILE__
local previous = rawget(_G, PROFILE.global_key)
if previous then return previous end
local make_runtime = function()
__BINGUS_RUNTIME__
end
local make_memory = function()
__BINGUS_MEMORY__
end
local runtime = make_runtime()
local memory = make_memory().new(runtime)
local ffi = memory.windows.ffi
local kernel = memory.windows.kernel32
local state = {status = 'waiting', writes = 0, restored = false, live_game_tested = false}
rawset(_G, PROFILE.global_key, state)
local loader = rawget(_G, 'CowboyBingusModLoader')
local log_file
if loader and type(loader.open_log) == 'function' then
    pcall(function() log_file = loader.open_log(PROFILE.guard_name .. '.log') end)
end
local function note(message)
    if log_file then log_file:write('[' .. PROFILE.guard_name .. '] ' .. message .. '\n'); log_file:flush() end
end
local function unhex(value)
    return (value:gsub('..', function(pair) return string.char(tonumber(pair, 16)) end))
end
local function u32(value, offset)
    local a, b, c, d = value:byte(offset + 1, offset + 4)
    return a + b * 256 + c * 65536 + d * 16777216
end
local function resource(value, offset)
    return string.format('%08x%08x', u32(value, offset + 4), u32(value, offset))
end
local function read(address, size)
    return assert(memory.read(ffi.cast('const void *', address), size), 'unreadable weapon metadata')
end
local region = ffi.new('bingus_memory1_region')
local function query(address)
    local ok, count = pcall(kernel.VirtualQuery, address, region, ffi.sizeof(region))
    assert(ok and count == ffi.sizeof(region),
        string.format('memory query failed at 0x%X: %s', address, tostring(count)))
    return {base = region.base_low + region.base_high * 4294967296,
        allocation = region.allocation_base_low + region.allocation_base_high * 4294967296,
        size = region.size_low + region.size_high * 4294967296,
        state = region.state, protection = region.protection, type = region.type}
end
if not pcall(ffi.typeof, 'hd2_weapon_movement_write_fn') then
    ffi.cdef [[
        typedef int (*hd2_weapon_movement_write_fn)(void *,void *,const void *,size_t,size_t *);
        int hd2_weapon_movement_WriteProcessMemory(void *,void *,const void *,size_t,size_t *) __asm__("WriteProcessMemory");
        int hd2_weapon_movement_VirtualProtect(void *,size_t,uint32_t,uint32_t *) __asm__("VirtualProtect");
        typedef struct hd2_weapon_movement_system_info {
            uint32_t architecture,page_size; void *minimum_address,*maximum_address;
            size_t processor_mask; uint32_t processors,processor_type,allocation_granularity;
            uint16_t processor_level,processor_revision;
        } hd2_weapon_movement_system_info;
        void hd2_weapon_movement_GetSystemInfo(hd2_weapon_movement_system_info *) __asm__("GetSystemInfo");
    ]]
end
local windows = ffi.load('kernel32')
local process = kernel.GetCurrentProcess()
local original = unhex(PROFILE.record_hex)
local component_header = unhex(PROFILE.component_header)
local root_header = unhex(PROFILE.map_header)
local function same_record(bytes)
    local offset = PROFILE.field_offset
    local value = bytes:byte(offset + 1)
    return bytes:sub(1, offset) == original:sub(1, offset)
        and bytes:sub(offset + 2) == original:sub(offset + 2)
        and (value == PROFILE.before or value == PROFILE.after)
end
local function locate_record(base)
    assert(read(base, 28) == root_header, 'entity map changed')
    local framing = read(base + PROFILE.component_offset - 4, 32 + PROFILE.indices * 16)
    assert(u32(framing, 0) == PROFILE.component_index and framing:sub(5, 32) == component_header,
        'weapon component header changed')
    local found, aliases = nil, 0
    for row = 0, PROFILE.indices - 1 do
        local offset = 32 + row * 16
        local key = resource(framing, offset)
        local record = u32(framing, offset + 8)
        assert(record < PROFILE.records and u32(framing, offset + 12) == 0, 'weapon component index changed')
        if key == PROFILE.resource then
            assert(found == nil and row == PROFILE.index_row and record == PROFILE.record_index,
                'weapon ownership changed')
            found = record
        end
        if key ~= '0000000000000000' and record == PROFILE.record_index then aliases = aliases + 1 end
    end
    assert(found ~= nil and aliases == 1, 'weapon record absent or shared')
    local address = base + PROFILE.component_offset + 28 + PROFILE.record_offset + found * PROFILE.stride
    assert(same_record(read(address, PROFILE.stride)), 'weapon record fields changed')
    return address
end
local function write_flag(address, value)
    local info = query(address)
    assert(info.state == 0x1000 and info.type == 0x20000 and (info.protection == 2 or info.protection == 4),
        'weapon movement flag is not private metadata')
    local page = math.floor(address / 4096) * 4096
    local old = ffi.new('uint32_t[1]')
    local changed = info.protection == 2
    if changed then
        assert(windows.hd2_weapon_movement_VirtualProtect(ffi.cast('void *', page), 4096, 4, old) ~= 0,
            'cannot unlock weapon metadata page')
    end
    local count = ffi.new('size_t[1]')
    local byte = string.char(value)
    local ok = windows.hd2_weapon_movement_WriteProcessMemory(process, ffi.cast('void *', address), byte, 1, count) ~= 0
        and tonumber(count[0]) == 1
    if changed then
        local ignored = ffi.new('uint32_t[1]')
        assert(windows.hd2_weapon_movement_VirtualProtect(ffi.cast('void *', page), 4096, old[0], ignored) ~= 0,
            'cannot restore metadata page protection')
    end
    assert(ok and read(address, 1):byte() == value, 'weapon movement flag readback failed')
end
local function work()
    local matched, why = memory.verify_build({exe_sha256 = PROFILE.exe_sha256, game_sha256 = PROFILE.game_sha256})
    assert(matched, why)
    local system = ffi.new('hd2_weapon_movement_system_info')
    windows.hd2_weapon_movement_GetSystemInfo(system)
    local finish = tonumber(ffi.cast('uintptr_t', system.maximum_address)) + 1
    assert(system.page_size == 4096 and finish > 65536 and finish <= 0x800000000000,
        'unsupported application address space')
    local function readable(info)
        return info.state == 0x1000 and info.type == 0x20000
            and (info.protection == 2 or info.protection == 4)
    end
    local function covers(base)
        local cursor, required = base, base + PROFILE.entity_size
        while cursor < required do
            local info = query(cursor)
            if not readable(info) or info.allocation ~= base or info.base > cursor
                or info.base + info.size <= cursor then return false end
            cursor = info.base + info.size
        end
        return true
    end
    for attempt = 1, 5 do
        local cursor, candidates, queries, headers, rejected = 65536, {}, 0, 0, nil
        while cursor < finish do
            local info = query(cursor)
            assert(info.size > 0 and info.base + info.size > cursor, 'invalid memory region')
            cursor = info.base + info.size
            -- VirtualQuery reports a same-protection REGION, not an entire
            -- allocation. Prove the allocation extent and target component,
            -- rather than assuming one region has the file's rounded size.
            if info.base == info.allocation and readable(info) and info.size >= 28 then
                if read(info.base, 28) == root_header then
                    headers = headers + 1
                    if covers(info.base) then
                        local ok, address = pcall(locate_record, info.base)
                        if ok then candidates[#candidates + 1] = {base = info.base, address = address}
                        else rejected = tostring(address) end
                    else rejected = 'entity allocation extent or protection changed' end
                end
            end
            queries = queries + 1
            if queries % 64 == 0 then coroutine.yield() end
        end
        state.scan = {attempt = attempt, regions = queries, headers = headers, candidates = #candidates}
        local summary = string.format('v0.2.1 scans=%d regions=%d headers=%d candidates=%d',
            attempt, queries, headers, #candidates)
        note(summary .. (rejected and (' rejected=' .. rejected) or ''))
        assert(#candidates <= 1, 'ambiguous verified entity allocations; ' .. summary)
        if #candidates == 1 then
            state.base = candidates[1].base
            state.record_address = candidates[1].address
            break
        end
        assert(headers == 0, 'entity candidate rejected; ' .. summary .. '; ' .. tostring(rejected))
        assert(attempt < 5, 'entity allocation unavailable; ' .. summary)
        state.status = 'waiting'
        local retry_at = memory.time() + 1
        repeat coroutine.yield() until memory.time() >= retry_at
        state.status = 'locating'
    end
    local before = read(state.record_address + PROFILE.field_offset, 1):byte()
    if before == PROFILE.before then
        write_flag(state.record_address + PROFILE.field_offset, PROFILE.after)
        state.writes = 1
    end
    state.status = 'active'
    state.owned_change = before == PROFILE.before
    note(PROFILE.field_name .. '=' .. PROFILE.after .. '; all other weapon bytes unchanged. Game behavior unverified.')
end
local task = coroutine.create(work)
local function step()
    if state.status == 'active' or state.status == 'failed' then return end
    state.status = 'locating'
    local ok, why = coroutine.resume(task)
    if not ok then state.status = 'failed'; state.error = tostring(why); note(state.error) end
end
local function stop()
    if state.owned_change and state.base and state.record_address then
        if locate_record(state.base) == state.record_address
            and read(state.record_address + PROFILE.field_offset, 1):byte() == PROFILE.after then
            write_flag(state.record_address + PROFILE.field_offset, PROFILE.before)
            state.restored = true
            state.owned_change = false
            note('Restored original ' .. PROFILE.field_name .. '=' .. PROFILE.before .. '.')
        end
    end
    state.status = 'stopped'
end
local guard = runtime.guard({name = PROFILE.guard_name, step = step, stop = stop, log = note, env = _G})
guard.install()
state.close = function() guard.stop('closed') end
return state
