"""Read-only inspection of native locomotion blend weights (no model/UI edits)."""
from __future__ import annotations

import argparse
import json
import math
import struct

from game_resources import AVATAR, GameResources

OPS = {
    0:('add',2), 1:('sub',2), 2:('mul',2), 3:('div',2), 4:('neg',1),
    5:('plus',1), 6:('sin',1), 7:('cos',1), 8:('abs',1), 9:('match',2),
    10:('match2d',4), 11:('match_range',4), 12:('match_range2d',8),
    13:('rand',2), 18:('clamp',3),
}


def u32(raw, at):return struct.unpack_from('<I',raw,at)[0]


def postfix(words, variables):
    stack=[]
    for word in words:
        if word & 0xfff00000 == 0x7f800000:
            name,count=OPS[word-0x7f800000]
            assert len(stack)>=count
            args=stack[-count:];del stack[-count:]
            stack.append({'op':name,'args':args})
        elif word & 0xffff0000 == 0x7f900000:
            index=word-0x7f900000
            stack.append({'variable':variables[index]['name'],'index':index})
        else:stack.append(struct.unpack('<f',struct.pack('<I',word))[0])
    assert len(stack)==1, stack
    return stack[0]


def expression(n):
    if isinstance(n,(int,float)):return f'{n:g}'
    if 'variable' in n:return n['variable']
    return n['op']+'('+', '.join(expression(a) for a in n['args'])+')'


def variables_in(n):
    if isinstance(n,(int,float)):return set()
    if 'variable' in n:return {n['index']}
    return set().union(*(variables_in(a) for a in n['args']))


def evaluate(n, values):
    if isinstance(n,(int,float)):return n
    if 'variable' in n:return values[n['variable']]
    a=[evaluate(v,values) for v in n['args']]
    op=n['op']
    clamp=lambda v: min(1.,max(0.,v))
    def triangle(value,minimum,center,maximum):
        if minimum==center:minimum-=1
        if maximum==center:maximum+=1
        return clamp((value-minimum)/(center-minimum))-clamp((value-center)/(maximum-center))
    if op=='match_range':return triangle(*a)
    if op=='match_range2d':return triangle(*a[:4])*triangle(*a[4:])
    if op=='add':return a[0]+a[1]
    if op=='sub':return a[0]-a[1]
    if op=='mul':return a[0]*a[1]
    if op=='div':return a[0]/a[1]
    if op=='neg':return -a[0]
    if op=='plus':return a[0]
    if op=='sin':return math.sin(a[0])
    if op=='cos':return math.cos(a[0])
    if op=='abs':return abs(a[0])
    if op=='clamp':return min(a[2],max(a[1],a[0]))
    raise ValueError(f'Unimplemented evaluator op {op}')


def parse_state(raw, state, variables):
    at=state['offset'];count,off=struct.unpack_from('<II',raw,at+80)
    words=struct.unpack_from(f'<{count}I',raw,at+off) if count and off else []
    functions=[];pending=[]
    for word in words:
        if word==0x7fa00000:
            functions.append(postfix(pending,variables));pending=[]
        else:pending.append(word)
    if pending:raise ValueError('Unterminated custom blend function')
    # Mirrors Filediver's ParseBlendFunction plus Blend/Time state exception.
    influences_only=(len(functions)==len(state['animations']) and state['type'] in (2,3))
    items=[]
    for i,fn in enumerate(functions):
        kind='influence' if i>0 or influences_only else 'playback_speed'
        clip_index=i if influences_only else i-1
        clip=state['animations'][clip_index] if kind=='influence' and clip_index<len(state['animations']) else None
        if kind=='influence' and clip is None:kind='auxiliary_unresolved'
        items.append({'kind':kind,'clipIndex':clip_index if clip else None,
                      'clip':f'{clip:016x}' if clip else None,
                      'expression':expression(fn),'tree':fn})
    used=set().union(*(variables_in(fn) for fn in functions))
    wc,wo=struct.unpack_from('<II',raw,at+20)
    ic,io=struct.unpack_from('<II',raw,at+64)
    return {'name':state['name'],'offset':at,'type':state['type'],
            'clips':[f'{a:016x}' for a in state['animations']],
            'animationWeights':list(struct.unpack_from(f'<{wc}f',raw,at+wo)) if wc else [],
            'weightIdIndexes':list(struct.unpack_from(f'<{ic}I',raw,at+io)) if ic else [],
            'blendVariableIndex':u32(raw,at+120),
            'blendVariable':variables[u32(raw,at+120)] if state['type']==3 else None,
            'loop':bool(u32(raw,at+32)),
            'emitEndEventHash':f'{u32(raw,at+72):08x}',
            'emitEndTransition':state['events'].get(f'{u32(raw,at+72):08x}'),
            'variables':[variables[i] for i in sorted(used)],'functions':items}


def seam_report(r, clip_hash):
    """Compare original clip endpoints; no root-motion removal or pose editing."""
    from native_animation import decode
    from author_motion import sample
    from export_assets import OUT, glb_json
    bones,_=r.bones()
    motion=decode(r.resource(clip_hash,'animation'),bones)
    tracks={t['bone']:t for t in motion['tracks']}
    doc=glb_json(OUT/'avatar/content/fac_helldivers/cha_avatar/avatar_helldiver.unit.glb')
    nodes={n['name']:i for i,n in enumerate(doc['nodes'])}
    parents={c:i for i,n in enumerate(doc['nodes']) for c in n.get('children',[])}
    def length(v):return math.sqrt(sum(a*a for a in v))
    def difference(a,b):return length([x-y for x,y in zip(a,b)])
    def angle(a,b):
        dot=sum(x*y for x,y in zip(a,b))/(length(a)*length(b))
        return math.degrees(2*math.acos(min(1.,abs(dot))))
    def matrix(pos,q,scl):
        size=length(q);x,y,z,w=[v/size for v in q]
        rows=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
              [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
              [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
        return [[rows[i][j]*scl[j] for j in range(3)]+[pos[i]] for i in range(3)]+[[0,0,0,1]]
    def multiply(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    cache={}
    def world(i,time):
        key=(i,time)
        if key in cache:return cache[key]
        node=doc['nodes'][i];track=tracks.get(node['name'])
        if track:
            m=matrix(sample(track['position'],time),sample(track['rotation'],time,True),sample(track['scale'],time))
        else:m=matrix(node.get('translation',[0,0,0]),node.get('rotation',[0,0,0,1]),node.get('scale',[1,1,1]))
        if i in parents:m=multiply(world(parents[i],time),m)
        cache[key]=m;return m
    out={}
    duration=motion['duration']
    for name in ('StingrayEntityRoot','root','boss','hips','r_thigh','l_thigh','r_knee','l_knee','r_foot','l_foot','r_ball','l_ball'):
        t=tracks[name]
        qa,qb=[sample(t['rotation'],v,True) for v in (0,duration)]
        pa,pb=[sample(t['position'],v) for v in (0,duration)]
        wa,wb=[world(nodes[name],v) for v in (0,duration)]
        ra,rb=[world(nodes['StingrayEntityRoot'],v) for v in (0,duration)]
        late=sample(t['rotation'],max(0,duration-.25),True)
        out[name]={'localAngleDegrees':round(angle(qa,qb),6),
                   'localPositionMeters':round(difference(pa,pb),8),
                   'globalPositionMeters':round(difference([row[3] for row in wa[:3]],[row[3] for row in wb[:3]]),8),
                   'rootRelativeGlobalPositionMeters':round(difference(
                       [wa[i][3]-ra[i][3] for i in range(3)],
                       [wb[i][3]-rb[i][3] for i in range(3)]),8),
                   'lastQuarterSecondAngleDegrees':round(angle(late,qb),6)}
    return {'clip':clip_hash,'duration':duration,'endpointDifferences':out}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--states',nargs='*',type=int,default=[75,78,86,59,93])
    ap.add_argument('--seams',action='store_true')
    args=ap.parse_args()
    r=GameResources();raw=r.resource(AVATAR,'state_machine')
    if args.seams:
        for clip in ('280f6a48a012814a','0f93b8bf901345ea','b726036661e01b81'):
            print(json.dumps(seam_report(r,clip),indent=2))
        return
    count,at=struct.unpack_from('<II',raw,20)
    hashes=struct.unpack_from(f'<{count}I',raw,at)
    defaults=struct.unpack_from(f'<{count}f',raw,at+4*count)
    variables=[{'index':i,'hash':f'{h:08x}','name':r.thin.get(h,f'{h:08x}'),
                'default':defaults[i]} for i,h in enumerate(hashes)]
    layers,_=r.states()
    for index in args.states:
        d=parse_state(raw,layers[0]['states'][index],variables)
        inputs={v['name']:v['default'] for v in d['variables']}
        inputs.update(move_angle=0.)
        if index==86:inputs['move_speed']=2.
        if index==78:inputs['move_speed']=6.5
        d['forwardInputs']=inputs
        d['evaluatedFunctions']=[evaluate(f['tree'],inputs) for f in d['functions']]
        d['forwardClipWeights']=[w for f,w in zip(d['functions'],d['evaluatedFunctions']) if f['kind']=='influence']
        expected={75:[0,0,1,0,0],78:[1,0,0,0,0,0,0,0,0],
                  86:[0,1,0,0,0,0],93:[0,0,0,0,1,0,0,0,0]}
        if index in expected:assert d['forwardClipWeights']==expected[index]
        print(json.dumps({'state':index,**d},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
