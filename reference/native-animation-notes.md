# Native animation and packaging evidence

Status: offline prototype, generated 2026-10-18. No game installation, live write,
in-game test, networking test, or behavior success is claimed.

## Important correction to the initial investigation

The avatar's layer 10 MG43 states 214/215 and Stalwart states 366/367 belong to
the prone context. Standing/crouching MG43 uses states **600/601**, mask **-1**
(full body). Standing/crouching Stalwart uses **750/751**, mask **40**. The prior
observation that both reloads excluded legs applied to the prone states only.

Both MG43 contexts share the same main normal/fast animations. Replacing
`f9761fd85530ae0f` or `b72125ac2aa44568` would therefore also alter prone reloads.
The prototype creates private animations instead:

| State | Original animation | Private animation | Mask |
|---|---|---|---|
| 600 | f9761fd85530ae0f | 4cb7b7c50f25ddc0 | -1 → 40 |
| 601 | b72125ac2aa44568 | 7d8cc9583080a3a4 | -1 → 40 |

Private resource paths are `content/mods/mg43_mobile_reload/normal` and
`content/mods/mg43_mobile_reload/fast`, using the game's Murmur64 resource hash.
State-machine edits change exactly **24 bytes**: two 8-byte animation IDs and
two 4-byte masks. Every other byte, including prone state records, is identical.

Original state-machine SHA-256:
`f8e38f6beba1af4a8c880ebbf96c858714698a577a2eb16b6dbdc11644514571`.
Patched state-machine SHA-256:
`a89f3a0c890592bb198e5b414d7f42a2d269558816fd069145482bd2f78567d3`.

This is evidence of correct offline targeting. The private clips are also
declared in the native package list described below. Actual loading and
blending still require a game test.

## Native package dependency closure

The avatar archive `18235e0c9ec0e636` contains 4241 resource entries but **no
package resource**. The boot archive `9ba626afa44a3aa3` holds
`18235e0c9ec0e636.package`, resolved as `packages/content/global_resources`.
The original package contains 4243 sorted unique `(type, name)` pairs. It
explicitly lists both original MG43 animations and the avatar state machine,
as well as every avatar-archive resource; the two extra original entries are
textures and are retained. This disproves the assumption that adding a native
resource to the avatar archive alone establishes its residency.

`pack_mod.py` now inserts exactly the two private animation `(type, name)` pairs
into this original package. Item count becomes 4245 and byte length grows from
67904 to 67936. All 4243 original entries, original ordering among them, and
unknown header fields remain unchanged. The revised package is emitted as a
**boot archive patch**, matching its original resource location.

For the combined package, `build_runtime_addon.py` merges this package resource
and the movement Lua resource by typed ID into **one** boot patch. The other
patch remains the avatar archive containing two animations plus its state
machine, so the combined ZIP still contains two complete archive triads.
Every build checks the chain **state-machine animation references → original
global package's new items → actual native animation entries** from the final
archive bytes. This is an offline dependency closure check, not an observed
engine residency test.

Original global package SHA-256:
`6f34132bb0f3f0aebbd4bd5b2d3b7fa6713a16727a4d6a2a17d5e5e37a051fce`.
Revised global package SHA-256:
`9042f41ffab752799caa1b3757b9e387ffbcc131b5284caee24209b8d8d0c36b`.

Format reference: [Filediver package reader](https://github.com/xypwn/filediver/blob/master/stingray/package/package.go).

## Native animation codec

`tools/native_animation.py` exposes:

```python
document = decode(native_bytes, bone_names)
edited_native_bytes = encode(native_template_bytes, edited_document)
```

Document contract: `boneNames`, `duration` in seconds, `tracks` containing
`bone` names and optional `position`/`rotation`/`scale` channels, each with
`times` and vector `values`; `additive` is per-bone; `beats` contains `time`
and an eight-digit thin `hash`. Coordinates stay native local Z-up, with
quaternions `[x, y, z, w]`. Coordinate conversion belongs in preview export.

The decoder reads native compressed and uncompressed keys. The writer preserves
the original hashes, event records, initial transform bytes, and additive NaN
markers, replacing edited channels with supported uncompressed subtype 4/5/6
keys. A time-zero curve key supplies an edited initial pose. It preserves the
two playback blocks: total size in the first header and zero in the second
header, with each block's terminator offset in its trailer.

Actual source data:

| Animation | Bones | Duration | Native bytes |
|---|---:|---:|---:|
| MG43 normal f9761fd85530ae0f | 90 | 4.9833331108 s | 321008 |
| MG43 fast b72125ac2aa44568 | 90 | 4.1666665077 s | 219016 |
| Stalwart normal 32622f93493bfd25 | 90 | 5.8333334923 s | 66796 |

Source decode→encode→decode maximum value errors were 0, 0, and 6.71e-8.
Authored normal/fast native files were also loaded by the independent HD2SDK
codec classes: 90 bones, 12892/9803 keys, zero curve-value disagreement.
`pack_mod.py` repeats the independent SDK check when building.

The SDK's compressed-scale implementation differs from Filediver's current
implementation: current compressed scale is three half-float deltas plus 1,
with NaN marking additive transforms. The pure-Python codec follows Filediver
for this, while retaining original initial raw bytes for export. SDK checks
compare the authored uncompressed keys, not its older compressed-scale logic.

Primary references:

- [Filediver native animation reader](https://github.com/xypwn/filediver/blob/master/stingray/animation/animation.go)
- [HD2SDK native animation import/export](https://github.com/Boxofbiscuits97/HD2SDK-CommunityEdition/blob/main/stingray/animation.py)
- [HD2SDK current releases](https://github.com/Boxofbiscuits97/HD2SDK-CommunityEdition/releases)
- [Filediver archive layout](https://github.com/xypwn/filediver/blob/master/stingray/archive.go)

The SDK source is retained in `vendor/hd2sdk` for reproducibility. Nothing was
installed into Blender. The SDK's `load_from_armature` method is an additional
possible Blender authoring route, but this prototype writes native curves
directly and does not depend on Blender.

Filediver's full CLI could not independently open a minimal mock game folder:
it initializes unrelated skin/attachment metadata before exporting animations.
The independent codec check therefore uses SDK source classes directly. This
limitation is not evidence of an animation-format failure or an engine pass.

## Moving while reloading

Native `WeaponReloadComponent` establishes `ReloadAllowMove` at offset 1,
`Ability` at offset 4, and `Duration` at offset 56.
[Field definitions](https://github.com/xypwn/filediver/blob/master/datalibrary/weapon_reload_component.go)
say ability selects the wielder's ability and duration scales it; the schema
alone does not prove that changing ability 2811 → 2765 is safe or necessary.
The prototype therefore keeps **ability 2811 and duration 4.5 seconds**.

The standard MG43 entity path is
`content/fac_helldivers/equipment/support_weapons/machinegun/machinegun`, hash
`11c27d3babb38956`. In the pinned entity table its reload index row is **308**,
record **235**, stride **80**, component index **113**, component offset
**5737840**. This record has exactly one nonzero owner. Its movement flag is
0, ability 2811, duration 4.5. The separate catalog duplicate entity
`587878fb76f4b9b1` maps to record 90, ability 2326, and is deliberately untouched.

`src/addon.lua` and `tools/build_runtime_addon.py` implement a separate Bingus
Shared Loader API 1 addon that changes only this one byte. It embeds the small
Bingus Shared Runtime v1 core and memory reader already present in the inspected
Mod Options Menu source resource; it does not bundle or edit HD2Runtime. The
build records SHA-256 for the vendored helpers. Build checks the executable and
game.dll fingerprints, component header and unique resource mapping, and the
remaining 79 record bytes. On close it restores its byte when it still owns the
change. A read-only metadata page is temporarily writable for the one-byte write
and immediately restored to its original protection.

Offline verification uses only a synthetic buffer and the standalone `lua51.dll`
VM loaded into the Python test process. It does not attach to or launch the game.
Verified: Lua compilation, unique MG43 resolution, exactly one changed byte,
readback, original page protection restored, shutdown rollback, refusal when
another record byte differs, and preserving an enable flag already present
before this addon starts. This does not establish actual gameplay behavior.

## Reproduce builds

From the project directory:

```powershell
python tools/pack_mod.py assets/authored/resources.json --mobile-mask
python tools/build_runtime_addon.py
```

Final generated artifacts:

- `dist/MG43-Mobile-Reload-v0.1-offline-prototype.zip`: combined test package,
  956204 bytes at this build; two complete archive triads (Assets and Movement),
  plus `manifest.json`, `validation-report.json`, and `README.txt`.
- `dist/mg43-mobile-reload-visual-prototype.zip`: animation/state assets plus the
  original global package dependency patch.
- `dist/mg43-mobile-reload-movement-prototype.zip`: separate declared Lua addon.

The combined package uses the existing workspace Arsenal manifest shape:
`Version`, `Guid`, `Name`, `Description`, and `Options[].Include` naming the
Assets and Movement folders. Its ZIP CRC, six archive-part presence, addon
resource wrapper, and exact bundled Lua source were checked. **Actual Arsenal
import has not been tested**, so this is a package prepared for later import,
not a claim that manager import or runtime loading has succeeded. Bingus Shared
Loader API 1 is required and is not bundled.

The asset package contains two private animations, the avatar state machine,
and its original global package's two added declarations. The separate movement
package contains one declared Lua addon. Neither command deploys
them. `build_runtime_addon.py` also creates the combined test ZIP when the asset
package is present. Offline visual review requires no gameplay installation.

Final independent SDK decode: normal 636832 bytes / 12892 keys, fast 483052
bytes / 9803 keys; each has 90 bones and zero uncompressed-curve disagreement.
Combined ZIP SHA-256:
`6c0554342701e3180fcfd8524d8b45a89b1ffe13c8829049ea7a244fbbfa07f1`.

## Independent M1000 switch preparation (v0.2 work)

The user accepted the MG43 running-reload preview and requested a separate
manager switch for M1000 moving fire. `src/addon.lua` now serves both builds
through explicit pinned profiles. The MG43 defaults stay record 235 / offset 1 /
0→1. The M1000 build targets only `43a58cb89cfa197c`,
`WeaponDataComponentData` index row 116 / record 348 / stride 1232, setting
`stationary_while_firing` at offset 387 from 1→0. All other 1231 record bytes,
including firing stance and per-shot events, must match the pinned source and
remain unmodified. Fire rate, damage, and spin-up time are not edited.

The emitted addon resource is `mods/hd2_local/m1000_mobile_fire`, with global
`M1000MobileFireV1` and guard/log name `M1000MobileFire`. These differ from
MG43's `MG43MobileReloadV1` / `MG43MobileReload`; only the identical private
Win32 FFI declarations are shared. Both use Bingus Shared Loader API 1 and do
not require or change HD2Runtime.

```powershell
python tools/build_runtime_addon.py --movement-only
python tools/build_m1000_addon.py
```

M1000 staging output is `dist/m1000-mobile-fire/Addon/9ba626afa44a3aa3.patch_0`
plus its empty stream/GPU companions, with `dist/m1000-mobile-fire/build-report.json`.
Final v0.2 release packaging and its manager options belong to
`tools/build_release.py`; the M1000 staging builder does not author that manifest.
The prior MG43 movement ZIP is retained under
`build/history/mg43-mobile-reload-movement-prototype-v0.1.zip`, and the historical
v0.1 combined ZIP was left untouched.

Each current addon passes ten synthetic-memory/compile checks, including one
byte write/readback, page protection restore, close rollback, refusing a changed
record, refusing a wrong resource-to-record mapping, refusing a shared record,
and not owning a value already enabled by another mod. An additional test uses
the **real unmodified Bingus update core** with synthetic memory for both addons
together: both become active; the original update callback runs; closing MG43
keeps M1000 enabled; closing M1000 restores its original byte. No game process
is attached or started by these checks.

Read-only installation check on 2026-10-18: Arsenal default profile has Bingus
Shared Loader v19 enabled/deployed at the bottom with default priority. Its
library archive and game `9ba626afa44a3aa3.patch_90` are byte-identical, SHA-256
`295488f31ff583118bf9f3dbe05c096ddbcdd493bde33513b3219e683d3f08ea`.
Scanning 302 currently deployed boot Lua resources found M1000 names in runtime
metadata/general callable authoring modules and HUD/cost tables, but no explicit
active addon editing the M1000 WeaponData record. This does not establish the
record's current live value or rule out every third-party modification; the full
record check remains intact. Actual game behavior and manager import of v0.2
still require their own verification.
