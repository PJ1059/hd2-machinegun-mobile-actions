"""Read-only M-1000 firing-movement inspection; never patches/deploys game files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from game_resources import AVATAR, GAME, GameResources, ROOT, WORKSPACE

RUNTIME=WORKSPACE/'runtime-interface-lab/HD2Runtime'
sys.path.insert(0,str(RUNTIME/'scripts'))
from scan.tables import EntityTables

ENTITY=0x43A58CB89CFA197C
OFFSET=387


def sha(data):return hashlib.sha256(data).hexdigest().upper()


def inspect(include_record=False):
    profiles=json.loads((RUNTIME/'schemas/build_profile.json').read_text())
    profile=profiles['builds'][profiles['active']]
    identity={name:sha((GAME/path).read_bytes()) for name,path in {
        'exeSha256':'bin/helldivers2.exe','gameDllSha256':'data/game/game.dll'}.items()}
    assert all(identity[key]==profile[key] for key in identity), 'Installed build differs from reference profile'
    folder=WORKSPACE/'spore-map/vendor/filediver/datalibrary'
    tables=EntityTables(folder,verify=False)
    assert sha(tables.entities)==profile['datalibrary']['entitiesSha256']
    assert sha(tables.typelib_bytes)==profile['datalibrary']['typelibSha256']
    component=tables.component('WeaponDataComponentData')
    member=component.member(OFFSET)
    assert (member.size,member.storage,member.name_length)==(1,'UINT8',23)
    record=component.record_of(ENTITY)
    assert record is not None
    owners=component.owners(record)
    assert owners==[ENTITY]
    selected=[(row,index) for row,owner,index in component.rows() if owner==ENTITY]
    assert len(selected)==1
    row,_=selected[0]
    raw=component.raw(record)
    assert raw[OFFSET]==1 and component.record_size==1232
    enabled=[index for index in range(component.count) if component.raw(index)[OFFSET]]
    assert enabled==[record], 'Restriction no longer unique to the Maxigun'
    schema=(RUNTIME/'schemas/current.lua').read_text()
    descriptor=re.search(r'\["WeaponDataComponentData"\]=\{([^}]+)\}',schema).group(1)
    fields=dict(re.findall(r'\["([^"]+)"\]=("[^"]*"|\d+)',descriptor))
    fields={key:json.loads(value) for key,value in fields.items()}
    assert fields['offset']==component.frame_offset
    assert fields['record_offset']==component.records_offset and fields['stride']==component.record_size
    at=component.frame_offset+28+component.records_offset+record*component.record_size
    assert tables.entities[at:at+component.record_size]==raw
    events={}
    for offset in (388,392,928):
        value=struct.unpack_from('<I',raw,offset)[0]
        events[offset]={'hash':f'{value:08x}','name':tables.thin.get(value)}
    assert [events[o]['name'] for o in (388,392,928)]==['brace','brace_exit','fire_minigun']
    changed=bytearray(raw);changed[OFFSET]=0
    diff=[i for i,(a,b) in enumerate(zip(raw,changed)) if a!=b]
    assert diff==[OFFSET]
    ability=tables.component('AbilityComponentData')
    ai=ability.record_of(ENTITY)
    spawn=list(struct.iter_unpack('<II',ability.raw(ai))) if ai is not None else []
    windup=tables.component('WeaponWindUpComponentData')
    wi=windup.record_of(ENTITY)
    windup_values=struct.unpack_from('<ff',windup.raw(wi))
    game=GameResources();layers,masks=game.states();bone_names,_=game.bones()
    lower=('boss','hips','r_thigh','l_thigh','r_knee','l_knee','r_foot','l_foot')
    upper=('spine1','spine2','chest')
    states=[]
    for li,layer in enumerate(layers):
        targets={event:set() for event in ('brace','brace_exit','fire_minigun')}
        for state in layer['states']:
            for event,link in state['events'].items():
                if event in targets:targets[event].add(link['target'])
        for event,indexes in targets.items():
            for si in sorted(indexes):
                state=layer['states'][si];mask=state['mask']
                weights={name:masks[mask][bone_names.index(name)] for name in lower+upper} if mask>=0 else None
                states.append({'event':event,'layer':li,'state':si,'name':state['name'],
                    'mask':mask,'maskWeights':weights,'additive':state['additive'],
                    'animations':[f'{a:016x}' for a in state['animations']]})
    shot=next(s for s in states if s['event']=='fire_minigun')
    assert (shot['layer'],shot['state'],shot['mask'],shot['additive'])==(12,19,60,True)
    assert all(shot['maskWeights'][bone]==0 for bone in lower)
    out={
        'build':profiles['active'],'installedBuildFingerprints':identity,
        'referenceEntitiesSha256':sha(tables.entities),
        'identity':{'weapon':'M-1000 Maxigun','resource':f'{ENTITY:016x}'},
        'component':{'name':component.name,'componentIndex':fields['index'],
            'frameOffset':component.frame_offset,'frameHeader':tables.entities[component.frame_offset:component.frame_offset+28].hex(),
            'indexCapacity':component.capacity,'recordCount':component.count,
            'recordOffset':component.records_offset,'stride':component.record_size,
            'indexRow':row,'recordIndex':record,'owners':[f'{o:016x}' for o in owners],
            'absoluteReferenceRecordOffset':at,'recordSha256':sha(raw)},
        'minimalChange':{'field':'FirePreventsMovement / weapon.stationary_while_firing',
            'recordOffset':OFFSET,'storage':'u8','before':raw[OFFSET],'after':0,
            'absoluteReferenceByteOffset':at+OFFSET,'memoryOnlyDiffOffsets':diff},
        'unchangedEvents':events,
        'unchangedAbilitySpawn':{'record':ai,'jobAbilityPairs':spawn},
        'unchangedWindup':{'record':wi,'windUpSeconds':windup_values[0],'windDownSeconds':windup_values[1]},
        'relevantAnimationStates':states,
        'nativeConsumerEvidence':{
            'source':'runtime-interface-lab/HD2Runtime/scripts/research_weapon_movement.py',
            'model':'WeaponData +387 gates brace/brace_exit and wielder action bit 55; +928 fire_minigun remains separate.',
            'readerSignature':'80b88301000000 .. 837e0800 .. 83b88801000000 .. 83b88401000000',
            'actionBitSignature':'480fbae837',
            'rerunThisSession':False,
            'limit':'Retained unpacked .hd2snap is absent locally; code-reader proof is inherited from existing local research, not re-executed.'},
        'liveEffectVerified':False,'gameWrites':0,'modelWrites':0}
    if include_record:out['component']['recordHex']=raw.hex()
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profile',action='store_true')
    args=ap.parse_args()
    print(json.dumps(inspect(args.profile),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
