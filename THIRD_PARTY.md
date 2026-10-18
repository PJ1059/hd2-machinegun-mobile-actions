# Third-party components and sources

- [Bingus Shared Runtime](https://github.com/CowboyBingus/BingusSharedRuntime), by CowboyBingus: the release's Lua plugins embed byte-identical `bingus_runtime` and `bingus_memory` v1 helpers. Upstream uses the Zero-Clause BSD license; see [the preserved license](licenses/BingusSharedRuntime-LICENSE.txt). Source templates in this repository use build placeholders for these helpers.
- [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader): external runtime dependency, not bundled.
- [Filediver](https://github.com/xypwn/filediver): archive extraction and format/field references used during development. The full tool checkout and decoded game definitions are not redistributed here.
- [HD2SDK Community Edition](https://github.com/Boxofbiscuits97/HD2SDK-CommunityEdition): used for independent native animation decoding. Not bundled.
- [Three.js](https://github.com/mrdoob/three.js): MIT-licensed npm dependency used by the local viewer. Install through npm; `node_modules` is not committed.
- The animation authoring and archive tools also reference the author's separate HD2Runtime workspace. That workspace is not bundled or required to run the release.

Helldivers 2 models, animations and other game-derived content retain their respective owners' rights. The screenshot shows a local gray-material preview. This repository does not include full original model or animation exports. The installable release contains the native patches needed for this MOD.
