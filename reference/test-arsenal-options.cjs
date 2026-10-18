// Read-only harness: executes the installed-source snapshot with filesystem writes stubbed.
// Run from the project directory: node reference/test-arsenal-options.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const sourceRoot = process.argv[2] || path.resolve(__dirname, '../../backups/arsenal-app-inspection/obfuscated_src');
const manifest = process.argv[3] ? JSON.parse(fs.readFileSync(process.argv[3], 'utf8')) : {
  Version: 1, Guid: '00000000-0000-4000-8000-000000000001', Name: 'Read-only fixture', Description: '',
  Options: [
    { Name: 'MG-43 移动换弹', Description: '', Include: ['MG43'] },
    { Name: 'M-1000 移动射击', Description: '', Include: ['M1000'], Default: false },
  ],
};
const avatar = '18235e0c9ec0e636', boot = '9ba626afa44a3aa3';
const triplet = (base, number) => ['', '.stream', '.gpu_resources'].map(ext => `${base}.patch_${number}${ext}`);
const files = new Map([
  [path.join('package', 'MG43'), [...triplet(avatar, 0), ...triplet(boot, 0)]],
  [path.join('package', 'M1000'), triplet(boot, 1)],
  ['package', ['manifest.json']],
]);
const copies = [];
const denyWrite = () => { throw new Error('Actual file writes are forbidden in this harness'); };
let allActive = true;
const readData = key => ({ modsList: [], setAllOptionsActive: allActive, setModsActive: false })[key];
const fsExtra = {
  access: async dir => { if (!files.has(dir)) throw new Error(`Unknown fixture directory ${dir}`); },
  readdir: async dir => { if (!files.has(dir)) throw new Error(`Unknown fixture directory ${dir}`); return files.get(dir); },
  copy: async (source, destination) => { copies.push({ source, destination }); },
};
const quietConsole = { log() {}, warn() {}, error() {} };
function load(relative, additions = '') {
  const sourceFile = path.join(sourceRoot, relative);
  const source = fs.readFileSync(sourceFile, 'utf8');
  const sandbox = {
    module: { exports: {} }, console: quietConsole, Buffer, setTimeout,
    require: name => {
      if (name === 'path') return path;
      if (name === 'fs') return new Proxy({}, { get: () => denyWrite });
      if (name === 'fs-extra') return fsExtra;
      if (name === './utils') return { readData, writeData: denyWrite };
      if (name === './modules/iconHandler') return { getModPackIcon: async () => null, getOptionIconPath: async () => null };
      return {};
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source + additions, sandbox, { timeout: 2000, filename: sourceFile });
  return { sandbox, sha256: crypto.createHash('sha256').update(source).digest('hex') };
}
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  const importer = load('main/modsHandler.js', '\nglobalThis.extractForTest = extractFromManifest;');
  const deployer = load('main/modules/modDeployer.js');
  const ModDeployer = deployer.sandbox.module.exports;
  const imported = await importer.sandbox.extractForTest(manifest, 'package', 'fixture');
  assert.deepEqual(plain(imported.options.map(option => option.enabled)), [true, true]);
  allActive = false;
  const firstOnly = await importer.sandbox.extractForTest(manifest, 'package', 'fixture');
  assert.deepEqual(plain(firstOnly.options.map(option => option.enabled)), [true, false]);

  for (const [mg43, m1000, expected] of [
    [true, false, ['MG43']], [false, true, ['M1000']],
    [true, true, ['MG43', 'M1000']], [false, false, []],
  ]) {
    const optionsConfig = imported.options.map((option, index) => ({ name: option.name, enabled: index === 0 ? mg43 : m1000 }));
    const options = ModDeployer.mergeOptionsWithConfig(imported.options, optionsConfig);
    assert.deepEqual(plain(ModDeployer.getValidFolders({ options })), expected);
  }
  const selected = ModDeployer.getValidFolders(imported);
  const existing = new Set([`${boot}.patch_0`]);
  const result = await ModDeployer.processModFiles('package', selected, existing, 'simulated-game-data');
  assert.equal(result.copiedCount, 9);
  assert.deepEqual(copies.map(item => path.basename(item.destination)), [
    ...triplet(avatar, 0), ...triplet(boot, 1), ...triplet(boot, 2),
  ]);
  copies.length = 0;
  await ModDeployer.processModFiles('package', [], new Set(), 'simulated-game-data');
  assert.equal(copies.length, 0); // No .patch_ files at package root.
  console.log(JSON.stringify({
    passed: true, actualWrites: 0,
    verified: ['native import defaults', 'independent option combinations', 'name-based optionsConfig merge', 'Include folder selection', 'same archive renumbering with intact triplets', 'empty root deploys nothing'],
    sources: { modsHandler: importer.sha256, modDeployer: deployer.sha256 },
    manifestSha256: crypto.createHash('sha256').update(JSON.stringify(manifest)).digest('hex'),
  }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
