"""Read the installed game and export selected source assets; never writes to it."""
from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OUT = ROOT / 'assets/source'
FILEDIVER = WORKSPACE / 'spore-map/vendor/filediver-cli/filediver-cli/filediver.exe'
GAME = Path('G:/SteamLibrary/steamapps/common/Helldivers 2')


def run_export(label, includes, *, single=False, raw=False, archives=None):
    out = OUT / label
    out.mkdir(parents=True, exist_ok=True)
    args = [str(FILEDIVER), '-g', str(GAME), '-o', str(out), '-T', 'unit',
            '-i', includes, '--model-format', 'raw' if raw else 'glb']
    if single:
        args += ['--unit-single-file']
    if archives:
        args += ['-a', archives]
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    lines = [s for s in (result.stdout + result.stderr).replace('\r', '\n').splitlines()
             if s and '[STATUS]' not in s]
    (out / 'export.log').write_text('\n'.join(lines), encoding='utf-8')
    print(label, 'exit', result.returncode, '\n'.join(lines[-12:]), flush=True)
    return list(out.rglob('*.glb'))


def glb_json(path):
    b = path.read_bytes()
    assert b[:4] == b'glTF'
    size, kind = struct.unpack_from('<II', b, 12)
    assert kind == 0x4e4f534a
    return json.loads(b[20:20+size])


def load_glb(path):
    raw = path.read_bytes()
    n = struct.unpack_from('<I', raw, 12)[0]
    d = json.loads(raw[20:20+n])
    at = 20+n
    data = raw[at+8:at+8+struct.unpack_from('<I', raw, at)[0]]
    return d, data


def write_glb(path, doc, data):
    doc['buffers'] = [{'byteLength':len(data)}]
    js = json.dumps(doc, separators=(',',':')).encode()
    js += b' ' * (-len(js) % 4)
    data += b'\0' * (-len(data) % 4)
    raw = struct.pack('<4sII', b'glTF',2,28+len(js)+len(data))
    raw += struct.pack('<II',len(js),0x4e4f534a)+js
    raw += struct.pack('<II',len(data),0x004e4942)+data
    path.write_bytes(raw)


def combine():
    """Share avatar joints, then mount independent weapon/magazine skeletons."""
    avatar_path = OUT/'avatar/content/fac_helldivers/cha_avatar/avatar_helldiver.unit.glb'
    doc, binary = load_glb(avatar_path)
    avatar = {n['name']:i for i,n in enumerate(doc['nodes']) if 'mesh' not in n}
    for n in doc['nodes']:
        # Avatar's geometry is the authoring body/cape placeholder.
        n.pop('mesh',None)
        n.pop('skin',None)
        n.pop('extensions',None)
    doc.pop('extensions',None)
    doc.pop('extensionsRequired',None)
    doc['extensionsUsed'] = []
    doc.pop('extras',None)
    manifest = {'avatar':{'path':str(avatar_path.relative_to(ROOT)), 'bones':avatar},
                'bindings':[], 'sources':{},
                'notes':['avatar indices are unchanged; canonical avatar node names remain unprefixed',
                         'armor shares matching avatar joints; armor-specific auxiliary joints have namespaced names',
                         'weapon/magazine are mounted in native coordinates; their source axis-conversion rotation is removed',
                         'avatar body and cape placeholder meshes are omitted; B-01 stocky pieces supply visible body']}

    def merge(path, prefix, *, share=False, mount=None):
        nonlocal binary
        src, blob = load_glb(path)
        arrays = ('bufferViews','accessors','images','samplers','textures','materials','meshes','skins')
        off = {key:len(doc.setdefault(key,[])) for key in arrays}
        boff = len(binary)
        binary += blob
        binary += b'\0' * (-len(binary)%4)
        node_map = {}
        shared = set()
        alias = {'standard_medium':'cha_avatar'}
        for i,n in enumerate(src['nodes']):
            name = alias.get(n['name'],n['name'])
            if share and 'mesh' not in n and name in avatar:
                node_map[i] = avatar[name]
                shared.add(i)
            elif share and i in src['scenes'][src.get('scene',0)]['nodes']:
                node_map[i] = avatar['StingrayEntityRoot']
                shared.add(i)
            else:
                node_map[i] = len(doc['nodes'])
                doc['nodes'].append({})
        for v in src.get('bufferViews',[]):
            v=copy.deepcopy(v);v['buffer']=0;v['byteOffset']=v.get('byteOffset',0)+boff
            doc['bufferViews'].append(v)
        for a in src.get('accessors',[]):
            a=copy.deepcopy(a)
            if 'bufferView' in a:a['bufferView']+=off['bufferViews']
            if 'sparse' in a:
                for key in ('indices','values'):a['sparse'][key]['bufferView']+=off['bufferViews']
            doc['accessors'].append(a)
        for im in src.get('images',[]):
            im=copy.deepcopy(im)
            if 'bufferView' in im:im['bufferView']+=off['bufferViews']
            doc['images'].append(im)
        doc['samplers'].extend(copy.deepcopy(src.get('samplers',[])))
        for t in src.get('textures',[]):
            t=copy.deepcopy(t)
            if 'sampler' in t:t['sampler']+=off['samplers']
            if 'source' in t:t['source']+=off['images']
            for ext in t.get('extensions',{}).values():
                if 'source' in ext:ext['source']+=off['images']
            doc['textures'].append(t)
        def texrefs(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k.endswith('Texture') and isinstance(v,dict) and 'index' in v:v['index']+=off['textures']
                    else:texrefs(v)
            elif isinstance(obj,list):
                for v in obj:texrefs(v)
        for m in src.get('materials',[]):
            m=copy.deepcopy(m);texrefs(m);doc['materials'].append(m)
        for m in src.get('meshes',[]):
            m=copy.deepcopy(m)
            for p in m['primitives']:
                p['attributes']={k:v+off['accessors'] for k,v in p['attributes'].items()}
                if 'indices' in p:p['indices']+=off['accessors']
                if 'material' in p:p['material']+=off['materials']
                for target in p.get('targets',[]):
                    for k in target:target[k]+=off['accessors']
                p.pop('extensions',None)
            doc['meshes'].append(m)
        for skin in src.get('skins',[]):
            skin=copy.deepcopy(skin)
            skin['joints']=[node_map[i] for i in skin['joints']]
            skin['name']=prefix+'::'+skin.get('name','skin')
            if 'inverseBindMatrices' in skin:skin['inverseBindMatrices']+=off['accessors']
            if 'skeleton' in skin:skin['skeleton']=avatar['StingrayEntityRoot'] if share else node_map[skin['skeleton']]
            doc['skins'].append(skin)
        for i,n in enumerate(src['nodes']):
            dest=node_map[i]
            children=[node_map[c] for c in n.get('children',[]) if node_map[c]!=dest]
            if i in shared:
                # Shared canonical parents must never be re-parented under source wrappers.
                new=[node_map[c] for c in n.get('children',[]) if c not in shared]
                if new:doc['nodes'][dest].setdefault('children',[]).extend(new)
                continue
            v=copy.deepcopy(n);v['name']=prefix+'::'+v['name']
            v.pop('extensions',None)
            if children:v['children']=children
            else:v.pop('children',None)
            if 'mesh' in v:v['mesh']+=off['meshes']
            if 'skin' in v:v['skin']+=off['skins']
            if not share and n['name']=='StingrayEntityRoot':
                v.pop('rotation',None);v.pop('matrix',None)
            doc['nodes'][dest]=v
        roots=[node_map[i] for i in src['scenes'][src.get('scene',0)]['nodes']]
        if mount is not None:doc['nodes'][mount].setdefault('children',[]).extend(roots)
        for ext in src.get('extensionsUsed',[]):
            if ext in ('MSFT_texture_dds',) and ext not in doc['extensionsUsed']:doc['extensionsUsed'].append(ext)
        mapped={n['name']:node_map[i] for i,n in enumerate(src['nodes']) if 'mesh' not in n}
        manifest['sources'][prefix]={'path':str(path.relative_to(ROOT)).replace('\\','/'),
            'nodeMap':node_map,'boneNames':mapped,'sharedNodes':sorted(shared),'sourceRoots':roots}
        return mapped

    merge(OUT/'armor-stocky/combined_unit.combined.glb','armor',share=True)
    gun=merge(OUT/'weapon/content/fac_helldivers/equipment/support_weapons/machinegun/machinegun.unit.glb',
              'weapon',mount=avatar['attach_hand_r'])
    mag=merge(OUT/'box/content/fac_helldivers/equipment/attachment/magazine/machinegun_box_large.unit.glb',
              'magazine',mount=gun['attach_mag'])
    manifest['bindings']=[{'child':'weapon','parent':'avatar.attach_hand_r','parentNode':avatar['attach_hand_r']},
                          {'child':'magazine','parent':'weapon.attach_mag','parentNode':gun['attach_mag']}]
    manifest['bindingEvidence']={
        'source':'Filediver bundled generated_entities.dl_bin, EquipmentComponentData and WeaponCustomizationComponentData',
        'weaponResource':'11c27d3babb38956', 'equipmentRecord':326,
        'wieldNodeHash':'4fdd3337','wieldNode':'attach_hand_r',
        'wieldRotationOffset':[0,0,0],'wieldPositionOffset':[0,0,0],
        'attachableOffset':[0,0,0],'attachableRotationOffset':[0,0,0],
        'magazinePath':'9d81323b153dc429',
        'magazineUnit':'content/fac_helldivers/equipment/attachment/magazine/machinegun_box_large',
        'magazinePathMemberOffset':128}
    target=OUT/'combined.glb'
    write_glb(target,doc,binary)
    manifest['combined']={'path':str(target.relative_to(ROOT)).replace('\\','/'),
                          'nodes':len(doc['nodes']),'skins':len(doc['skins']),
                          'visibleMeshes':sum('mesh' in n for n in doc['nodes'])}
    (OUT/'combined-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('combined',manifest['combined'],flush=True)
    return target


def verify_combined():
    d=glb_json(OUT/'combined.glb')
    parents=defaultdict(list)
    for i,n in enumerate(d['nodes']):
        for c in n.get('children',[]):parents[c].append(i)
    assert not [(i,p) for i,p in parents.items() if len(p)>1], 'multiple node parents'
    active,done=set(),set()
    def visit(i):
        assert i not in active, f'cycle at {i}'
        if i in done:return
        active.add(i)
        for c in d['nodes'][i].get('children',[]):visit(c)
        active.remove(i);done.add(i)
    for root in d['scenes'][d.get('scene',0)]['nodes']:visit(root)
    assert len(done)==len(d['nodes']), (len(done),len(d['nodes']))
    print('Verified hierarchy:',len(done),'reachable nodes, no cycles/multiple parents')
    code='''import bpy, math
from mathutils import Vector
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
print('IMPORT_QA meshes',len(meshes),'armatures',len([o for o in bpy.context.scene.objects if o.type=='ARMATURE']))
points=[o.matrix_world @ Vector(p) for o in meshes for p in o.bound_box]
lo=Vector([min(p[i] for p in points) for i in range(3)])
hi=Vector([max(p[i] for p in points) for i in range(3)])
print('IMPORT_QA bounds',list(lo),list(hi))
bpy.ops.object.camera_add(location=(3,-5,2.5))
cam=bpy.context.object
target=Vector((0,0,1))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO';cam.data.ortho_scale=3
bpy.context.scene.camera=cam
for loc,energy,size in [((2,-4,5),1200,4),((-3,-1,3),800,3),((1,3,4),1400,3)]:
 bpy.ops.object.light_add(type='AREA',location=loc)
 light=bpy.context.object;light.data.energy=energy;light.data.shape='DISK';light.data.size=size
 light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
scene=bpy.context.scene
scene.world.color=(.12,.12,.12)
scene.render.engine='CYCLES';scene.cycles.samples=16
scene.render.resolution_x=900;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.filepath=PNG
bpy.ops.render.render(write_still=True)
'''.replace('GLB',repr(str(OUT/'combined.glb')))
    # Assign paths without interpolating them into shell code.
    code=code.replace("scene.render.filepath=PNG",'scene.render.filepath='+repr(str(OUT/'qa-combined.png')))
    result=subprocess.run([r'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe',
        '-b','--factory-startup','--python-expr',code],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (OUT/'qa-combined.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    print('\n'.join(s for s in result.stdout.splitlines() if 'IMPORT_QA' in s or 'Error' in s))
    print('Blender QA exit',result.returncode)


def summarize(path):
    d = glb_json(path)
    ns = d.get('nodes', [])
    return dict(path=str(path.relative_to(ROOT)).replace('\\','/'), size=path.stat().st_size,
                meshes=len(d.get('meshes', [])), skins=len(d.get('skins', [])),
                nodes=len(ns), animations=len(d.get('animations', [])),
                bones=[n.get('name') for n in ns if 'mesh' not in n],
                mesh_nodes=[dict(index=i, name=n.get('name'), skin=n.get('skin')) for i,n in enumerate(ns) if 'mesh' in n])


def armor_parts():
    # Existing workspace catalog records the base B-01 pieces; read-only reference.
    catalog = json.loads((WORKSPACE / 'transmog-zh-cn/reference/current_catalog.json').read_text())
    armor = catalog['kits']['621795009']
    selected = [p for body in armor['bodies'] if body['type'] in (0,3)
                for p in body['pieces'] if p['slot'] != 1]
    selected += [{'path':'bc20d0b4efff128c','slot':0,'type':0}]
    (OUT / 'b01-pieces.json').write_text(json.dumps(selected, indent=2), encoding='utf-8')
    return selected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('targets', nargs='*', default=['avatar','weapon','box','armor','raw','combine'])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for target in args.targets:
        if target == 'avatar':
            run_export('avatar', 'content/fac_helldivers/cha_avatar/avatar_helldiver.unit')
        elif target == 'weapon':
            run_export('weapon', '*support_weapons/machinegun/machinegun*')
        elif target == 'box':
            run_export('box', '*attachment/magazine/machinegun_box*')
        elif target == 'armor':
            parts = armor_parts()
            run_export('armor-stocky', '{' + ','.join('0x' + p['path'] + '.unit' for p in parts) + '}', single=True)
        elif target == 'raw':
            run_export('raw', '{content/fac_helldivers/cha_avatar/avatar_helldiver.unit,*support_weapons/machinegun/machinegun.unit,*attachment/magazine/machinegun_box*}', raw=True)
        elif target == 'combine':
            combine()
        elif target == 'verify':
            verify_combined()
    summaries = [summarize(p) for p in OUT.rglob('*.glb')]
    (OUT / 'asset-summary.json').write_text(json.dumps(summaries, indent=2), encoding='utf-8')
    for s in summaries:
        print(s['path'], 'meshes',s['meshes'],'skins',s['skins'],'nodes',s['nodes'],'bytes',s['size'])


if __name__ == '__main__':
    main()
