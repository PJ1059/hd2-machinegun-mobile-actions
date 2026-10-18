import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (id) => document.getElementById(id);
const modeLabels = { stand: '站立', walk: '行走', run: '奔跑' };
const groundOffset = new THREE.Vector3();
const dom = Object.fromEntries(['viewport', 'loading', 'loadingTitle', 'loadingDescription', 'retry', 'statusText', 'activeLabel', 'play', 'playIcon', 'playLabel', 'reset', 'timeline', 'timeReadout', 'speed', 'currentStage', 'stageTicks', 'stageList', 'variantDescription', 'verificationText', 'modelInfo', 'clipInfo', 'sourceInfo', 'gridToggle', 'skeletonToggle', 'loopToggle'].map(id => [id, $(id)]));
const preview = window.__preview = {
  ready: false, meshCount: 0, boneCount: 0, currentClip: null,
  time: 0, duration: 0, variant: 'new', mode: 'stand', errors: [], clips: [], availableModes: [],
};
const state = { metadata: null, action: null, asset: null, model: null, mixer: null, skeleton: null, duration: 0, time: 0, playing: false, variant: 'new', mode: 'stand', stages: [], cameraView: 'threequarter', speed: 1, selectionRevision: 0, loadRevision: 0, modelBounds: null };
const cache = new Map();
const loader = new GLTFLoader();
const scene = new THREE.Scene();
scene.background = new THREE.Color('#252c2f');
scene.fog = new THREE.Fog('#252c2f', 9, 23);
const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
camera.position.set(3.1, 1.9, 4.5);
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  dom.viewport.prepend(renderer.domElement);
} catch (error) {
  showError('当前浏览器无法创建三维视口', error.message);
}
const controls = renderer ? new OrbitControls(camera, renderer.domElement) : null;
if (controls) {
  controls.target.set(0, 1, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;
  controls.minDistance = 0.25;
  controls.maxDistance = 15;
  controls.maxPolarAngle = Math.PI / 2 + 0.03;
}

scene.add(new THREE.HemisphereLight('#dfefff', '#77817e', 1.0));
const keyLight = new THREE.DirectionalLight('#fff0d2', 1.5);
keyLight.position.set(3, 5, 4);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.left = keyLight.shadow.camera.bottom = -3;
keyLight.shadow.camera.right = keyLight.shadow.camera.top = 3;
keyLight.shadow.normalBias = 0.015;
keyLight.shadow.bias = -0.0001;
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight('#bfd9e8', 1.0);
rimLight.position.set(-3, 3, -2);
scene.add(rimLight);
const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: '#30383a', roughness: 1, metalness: 0 }));
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.004;
floor.receiveShadow = true;
scene.add(floor);
const grid = new THREE.GridHelper(60, 120, '#424e51', '#424e51');
grid.position.y = 0.001;
grid.material.transparent = true;
grid.material.opacity = 0.65;
scene.add(grid);
const origin = new THREE.Group();
const axisMaterial = (color) => new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.65 });
origin.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-0.5, 0.003, 0), new THREE.Vector3(0.5, 0.003, 0)]), axisMaterial('#cb7c72')));
origin.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0.003, -0.5), new THREE.Vector3(0, 0.003, 0.5)]), axisMaterial('#739aba')));
scene.add(origin);

function report(error) {
  const message = error instanceof Error ? error.message : String(error);
  preview.errors.push(message);
  console.error(error);
  return message;
}
function showError(title, description) {
  preview.ready = false;
  dom.loading.hidden = false;
  dom.loading.classList.add('error');
  dom.loadingTitle.textContent = title;
  dom.loadingDescription.textContent = description;
  dom.retry.hidden = false;
  dom.statusText.textContent = '资源未就绪';
  dom.play.disabled = dom.reset.disabled = dom.timeline.disabled = true;
  dom.modelInfo.textContent = '未载入';
}
function setBusy(title) {
  preview.ready = false;
  dom.loading.hidden = false;
  dom.loading.classList.remove('error');
  dom.loadingTitle.textContent = title;
  dom.loadingDescription.textContent = '加载角色、武器与动作数据。';
  dom.retry.hidden = true;
  dom.statusText.textContent = '正在加载资源';
}
function assetUrl(asset) {
  return new URL(asset, new URL('assets/', location.href)).href;
}
function configFor(variant = state.variant, mode = state.mode) {
  const meta = state.metadata;
  if (!meta) return null;
  let entry = meta.clips?.[variant]?.[mode];
  if (!entry && mode === 'stand') entry = variant === 'new' ? (meta.newClip || 'MG43_New') : (meta.originalClip || 'MG43_Original');
  if (!entry) return null;
  if (typeof entry === 'string') entry = { clip: entry };
  return { ...entry, asset: entry.asset || meta.asset || 'preview.glb', duration: entry.duration || meta.duration };
}
async function getAsset(url) {
  if (!cache.has(url)) {
    const promise = loader.loadAsync(url).then(gltf => {
      const root = gltf.scene;
      let meshCount = 0, boneCount = 0;
      root.traverse(object => {
        if (object.isMesh) {
          meshCount++;
          object.castShadow = object.receiveShadow = true;
          // Animated bounds from exporters can be too small for standing / walking poses.
          object.frustumCulled = false;
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach(material => {
            if (material) {
              material.side = THREE.DoubleSide;
              if (material.map) material.map.colorSpace = THREE.SRGBColorSpace;
            }
          });
        }
        if (object.isBone) boneCount++;
      });
      return { gltf, root, mixer: new THREE.AnimationMixer(root), meshCount, boneCount };
    }).catch(error => { cache.delete(url); throw error; });
    cache.set(url, promise);
  }
  return cache.get(url);
}
function transformModel(model) {
  const meta = state.metadata;
  const transform = meta.transform || {};
  model.scale.setScalar(typeof transform.scale === 'number' ? transform.scale : 1);
  if (Array.isArray(transform.scale)) model.scale.fromArray(transform.scale);
  model.rotation.set(...(transform.rotation || [0, 0, 0]));
  model.position.fromArray(transform.position || [0, 0, 0]);
  model.updateMatrixWorld(true);
}
async function selectClip({ preserveTime = true } = {}) {
  const revision = ++state.selectionRevision;
  const config = configFor();
  const fraction = state.duration ? state.time / state.duration : 0;
  if (!config) {
    showError('此动作尚未制作', '当前没有可用的动作资源，请选择其他移动状态。');
    return;
  }
  try {
    setBusy('正在载入动作');
    const loaded = await getAsset(assetUrl(config.asset));
    if (revision !== state.selectionRevision) return;
    const clip = THREE.AnimationClip.findByName(loaded.gltf.animations, config.clip);
    if (!clip) throw new Error(`资源中未找到动作「${config.clip}」。可用动作：${loaded.gltf.animations.map(c => c.name).join('、') || '无'}`);
    if (state.asset !== loaded) {
      if (state.model) scene.remove(state.model);
      if (state.skeleton) { scene.remove(state.skeleton); state.skeleton.dispose(); }
      state.asset = loaded; state.model = loaded.root; state.mixer = loaded.mixer;
      transformModel(state.model);
      scene.add(state.model);
      state.skeleton = new THREE.SkeletonHelper(state.model);
      state.skeleton.material.depthTest = false;
      state.skeleton.material.transparent = true;
      state.skeleton.material.opacity = 0.7;
      state.skeleton.renderOrder = 10;
      state.skeleton.visible = dom.skeletonToggle.checked;
      scene.add(state.skeleton);
    }
    // Each clip contains its complete pose. Do not blend two full-body clips.
    state.mixer.stopAllAction();
    state.action = state.mixer.clipAction(clip);
    state.action.reset().setEffectiveWeight(1).setEffectiveTimeScale(1);
    state.action.setLoop(THREE.LoopOnce, 1);
    state.action.clampWhenFinished = true;
    state.action.play();
    state.duration = Number(config.duration) || clip.duration;
    if (!Number.isFinite(state.duration) || state.duration <= 0) throw new Error('动作没有有效的时长。');
    state.time = preserveTime ? Math.min(fraction * state.duration, state.duration) : 0;
    state.action.time = Math.min(state.time, clip.duration);
    state.action.paused = true;
    state.mixer.update(0);
    state.model.updateMatrixWorld(true);
    state.modelBounds = new THREE.Box3().setFromObject(state.model);
    if (state.metadata.cameraBounds) state.modelBounds = new THREE.Box3(new THREE.Vector3(...state.metadata.cameraBounds.min), new THREE.Vector3(...state.metadata.cameraBounds.max));
    preview.ready = true;
    preview.meshCount = loaded.meshCount;
    preview.boneCount = loaded.boneCount;
    preview.currentClip = clip.name;
    preview.clips = loaded.gltf.animations.map(c => ({ name: c.name, duration: c.duration }));
    preview.asset = config.asset;
    preview.duration = state.duration;
    dom.loading.hidden = true;
    dom.play.disabled = dom.reset.disabled = dom.timeline.disabled = false;
    dom.statusText.textContent = state.metadata.status || '离线预览已就绪';
    dom.modelInfo.textContent = `${loaded.meshCount} 个网格 · ${loaded.boneCount} 根骨骼`;
    dom.clipInfo.textContent = clip.name;
    dom.sourceInfo.textContent = state.metadata.source || '本机游戏资源';
    dom.variantDescription.textContent = config.description || state.metadata.descriptions?.[state.variant] || (state.variant === 'new' ? '站姿换弹动作原型' : '原版换弹动作参考');
    const verification = state.metadata.verification || '离线检查姿态、手部接触与穿模。游戏内状态切换及弹药逻辑仍需实测。';
    const groundNote = state.mode !== 'stand' && state.metadata.groundTracks?.[state.mode] ? ' 原地动作预览，网格按原生位移滚动。' : '';
    dom.verificationText.textContent = verification + groundNote + (state.mode === 'run' ? ' 奔跑仅为步态混合预览；游戏内奔跑及冲刺限制待测。' : '');
    dom.activeLabel.textContent = `${state.variant === 'new' ? '新版' : '原版'} · ${modeLabels[state.mode] || state.mode}换弹`;
    state.stages = (config.stages || state.metadata.stages || []).map(stage => ({ label: stage.label || stage.name, time: Number(stage.time ?? stage.start) || 0 })).sort((a, b) => a.time - b.time);
    renderStages();
    setCamera(state.cameraView);
    updateTime();
  } catch (error) {
    if (revision !== state.selectionRevision) return;
    showError('无法加载动作资源', report(error));
  }
}
function renderStages() {
  dom.stageList.replaceChildren(); dom.stageTicks.replaceChildren();
  if (!state.stages.length) {
    const li = document.createElement('li'); li.textContent = '未设置阶段标记'; li.className = 'empty-stage'; dom.stageList.append(li); return;
  }
  state.stages.forEach(stage => {
    const li = document.createElement('li');
    const button = document.createElement('button'); button.type = 'button'; button.textContent = stage.label;
    const time = document.createElement('time'); time.textContent = `${stage.time.toFixed(1)}s`; button.append(time);
    button.addEventListener('click', () => { setTime(stage.time); setPlaying(false); });
    li.append(button); dom.stageList.append(li);
    const tick = document.createElement('i'); tick.style.left = `${Math.min(1, stage.time / state.duration) * 100}%`; dom.stageTicks.append(tick);
  });
}
function updateTime() {
  preview.time = state.time; preview.variant = state.variant; preview.mode = state.mode; preview.playing = state.playing;
  updateGround();
  dom.timeline.max = String(state.duration || 1); dom.timeline.value = String(state.time);
  dom.timeline.style.setProperty('--progress', `${state.duration ? state.time / state.duration * 100 : 0}%`);
  dom.timeReadout.replaceChildren(document.createTextNode(state.time.toFixed(2) + ' '));
  const span = document.createElement('span'); span.textContent = `/ ${state.duration.toFixed(2)} s`; dom.timeReadout.append(span);
  let stageIndex = -1;
  for (let i = 0; i < state.stages.length; i++) if (state.time >= state.stages[i].time) stageIndex = i;
  dom.currentStage.textContent = stageIndex >= 0 ? state.stages[stageIndex].label : '动作起始';
  [...dom.stageList.querySelectorAll('button')].forEach((button, i) => { button.classList.toggle('active', i === stageIndex); button.setAttribute('aria-current', i === stageIndex ? 'step' : 'false'); });
}
function updateGround() {
  const track = state.metadata?.groundTracks?.[state.mode];
  const count = Math.min(track?.times?.length || 0, track?.positions?.length || 0);
  groundOffset.set(0, 0, 0);
  if (count) {
    // Tracks contain inverse native displacement in world space across all cycles.
    let low = 0, high = count - 1;
    while (low + 1 < high) {
      const mid = (low + high) >>> 1;
      if (track.times[mid] <= state.time) low = mid; else high = mid;
    }
    const first = track.positions[low], last = track.positions[high];
    const span = track.times[high] - track.times[low];
    const alpha = span > 0 ? THREE.MathUtils.clamp((state.time - track.times[low]) / span, 0, 1) : 0;
    groundOffset.set(
      THREE.MathUtils.lerp(first[0], last[0], alpha), 0,
      THREE.MathUtils.lerp(first[2], last[2], alpha),
    );
  }
  grid.position.x = THREE.MathUtils.euclideanModulo(groundOffset.x, 0.5);
  grid.position.z = THREE.MathUtils.euclideanModulo(groundOffset.z, 0.5);
  preview.groundOffset = groundOffset.toArray();
}
function setTime(time) {
  if (!preview.ready) return;
  state.time = THREE.MathUtils.clamp(Number(time) || 0, 0, state.duration);
  state.action.time = Math.min(state.time, state.action.getClip().duration);
  state.action.paused = true;
  state.action.enabled = true;
  state.mixer.update(0);
  updateTime();
}
function setPlaying(playing) {
  if (!preview.ready) return;
  state.playing = playing;
  dom.playIcon.setAttribute('d', playing ? 'M7 5h4v14H7zM14 5h4v14h-4z' : 'm9 5 11 7-11 7z');
  dom.playLabel.textContent = playing ? '暂停' : '播放';
  dom.play.setAttribute('aria-label', playing ? '暂停动作' : '播放动作');
  preview.playing = playing;
}
function setCamera(view) {
  if (!controls) return;
  state.cameraView = view;
  const bounds = state.modelBounds;
  if (!bounds || bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const height = Math.max(size.y, 1.5);
  const centerX = center.x, centerZ = center.z;
  const target = new THREE.Vector3(centerX, bounds.min.y + height * 0.52, centerZ);
  let offset;
  if (view === 'front') offset = new THREE.Vector3(0, height * 0.02, height * 1.8);
  else if (view === 'side') offset = new THREE.Vector3(height * 1.85, height * 0.04, 0);
  else if (view === 'hands') {
    target.y = bounds.min.y + height * 0.67;
    offset = new THREE.Vector3(height * 0.53, height * 0.1, height * 0.61);
  } else offset = new THREE.Vector3(height * 1.26, height * 0.28, height * 1.5);
  const preset = state.metadata?.cameras?.[view];
  if (preset?.target) target.fromArray(preset.target);
  controls.target.copy(target);
  if (preset?.position) camera.position.fromArray(preset.position); else camera.position.copy(target).add(offset);
  controls.update();
  document.querySelectorAll('[data-view]').forEach(button => { const active = button.dataset.view === view; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
}
function setSelection(variant, mode) {
  if (variant) state.variant = variant;
  if (mode) state.mode = mode;
  document.querySelectorAll('[data-variant]').forEach(button => { const active = button.dataset.variant === state.variant; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
  preview.availableModes = Object.keys(modeLabels).filter(key => Boolean(configFor(state.variant, key)));
  document.querySelectorAll('[data-mode]').forEach(button => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle('selected', active);
    button.setAttribute('aria-pressed', String(active));
    button.disabled = !preview.availableModes.includes(button.dataset.mode);
    button.title = button.disabled ? '此动作资源尚未制作' : '';
  });
  return selectClip();
}
async function loadMetadata() {
  const revision = ++state.loadRevision;
  try {
    setBusy('正在准备三维资源');
    const response = await fetch(`assets/preview.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('缺少 assets/preview.json。真实动作资源就绪后，点击重新加载。');
    const metadata = await response.json();
    if (revision !== state.loadRevision) return;
    state.metadata = metadata;
    const fallbackVariant = metadata.defaultVariant || 'new';
    const fallbackMode = metadata.defaultMode || 'stand';
    state.variant = fallbackVariant; state.mode = fallbackMode;
    document.querySelectorAll('[data-variant]').forEach(button => { button.disabled = !configFor(button.dataset.variant, 'stand'); });
    document.querySelectorAll('[data-mode]').forEach(button => { button.disabled = !configFor(state.variant, button.dataset.mode); });
    await setSelection(fallbackVariant, fallbackMode);
  } catch (error) {
    showError('真实动作资源尚未就绪', report(error));
  }
}

dom.play.addEventListener('click', () => {
  if (!state.playing && state.time >= state.duration) setTime(0);
  setPlaying(!state.playing);
});
dom.reset.addEventListener('click', () => { setTime(0); setPlaying(false); });
dom.timeline.addEventListener('input', () => { setTime(dom.timeline.value); setPlaying(false); });
dom.speed.addEventListener('change', () => { state.speed = Number(dom.speed.value); });
dom.gridToggle.addEventListener('change', () => { grid.visible = origin.visible = dom.gridToggle.checked; });
dom.skeletonToggle.addEventListener('change', () => { if (state.skeleton) state.skeleton.visible = dom.skeletonToggle.checked; });
dom.retry.addEventListener('click', () => loadMetadata());
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setCamera(button.dataset.view)));
document.querySelectorAll('[data-variant]').forEach(button => button.addEventListener('click', async () => {
  const next = button.dataset.variant;
  const mode = configFor(next, state.mode) ? state.mode : 'stand';
  document.querySelectorAll('[data-mode]').forEach(item => { item.disabled = !configFor(next, item.dataset.mode); });
  await setSelection(next, mode);
}));
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => setSelection(null, button.dataset.mode)));
window.addEventListener('keydown', (event) => {
  if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(event.target.tagName) || !preview.ready) return;
  if (event.code === 'Space') { event.preventDefault(); if (state.time >= state.duration) setTime(0); setPlaying(!state.playing); }
  if (event.code === 'ArrowLeft' || event.code === 'ArrowRight') { event.preventDefault(); setPlaying(false); setTime(state.time + (event.code === 'ArrowRight' ? 1 : -1) / 30); }
});
document.addEventListener('visibilitychange', () => { if (document.hidden) setPlaying(false); });
const resize = () => {
  if (!renderer) return;
  const width = dom.viewport.clientWidth, height = dom.viewport.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height; camera.updateProjectionMatrix();
};
new ResizeObserver(resize).observe(dom.viewport); resize();
let lastTime = performance.now();
function render(now) {
  const delta = Math.min((now - lastTime) / 1000, 0.05); lastTime = now;
  if (preview.ready && state.playing) {
    let next = state.time + delta * state.speed;
    if (next >= state.duration) {
      if (dom.loopToggle.checked) next %= state.duration;
      else { next = state.duration; setPlaying(false); }
    }
    setTime(next);
  }
  controls?.update();
  renderer?.render(scene, camera);
  requestAnimationFrame(render);
}
Object.assign(preview, { setTime, setSelection, setCamera, setPlaying, reload: loadMetadata, scene, camera });
if (renderer) { requestAnimationFrame(render); loadMetadata(); }
