"""Localize exact Stage 1 samples using its real linked instruction addresses."""
import collections
import statistics as s
import experiment as p

inspection=p.common.load(p.ROOT/'head-inspection-baseline.json')
ins=inspection['instructions']
# Dispatch on Kernel::CLIP (4); locate its actual target and vector dense loop.
dispatch=next(i for i,r in enumerate(ins[:-1]) if r['mnemonic']=='cmp' and r['operands']=='eax, 4')
assert ins[dispatch+1]['mnemonic']=='je'
guard=int(ins[dispatch+1]['operands'],16)
clip=next(r['rva'] for r in ins if r['rva']>=guard and r['mnemonic']=='vmaxps')
dense_index=next(i for i,r in enumerate(ins) if r['rva']>clip and r['mnemonic']=='vmulps')
assert ins[dense_index-1]['mnemonic']=='vbroadcastss'
dense=ins[dense_index-1]['rva']
end_index=next(i for i,r in enumerate(ins) if r['rva']>dense and r['mnemonic']=='jne' and int(r['operands'],16)<=dense)
end=ins[end_index]['rva']+len(bytes.fromhex(ins[end_index]['bytes']))
fallbacks=[int(r['operands'],16) for r in ins if guard<=r['rva']<clip and r['mnemonic']=='je' and int(r['operands'],16)>end]
assert fallbacks
# Cold one-time ISA initialization may be another forward target. The first
# forward region after selected-kernel output is the retained scalar fallback.
output_end=min(fallbacks)
samples=p.common.load(p.ROOT/'native-samples.json')
symbols=p.common.load(p.ROOT/'native-symbols.json')
base=next(r['base'] for r in samples['modules'] if r['name'].lower()=='mapped.exe')
counts=collections.Counter();opcodes=collections.Counter();per_position={}
lookup={r['rva']:r for r in ins}
for record in samples['records']:
    if not record['sampled']:continue
    local=collections.Counter()
    for address,n in record['rip_counts'].items():
        ip=int(address,16)-base
        if inspection['head_rva']<=ip<inspection['head_rva']+inspection['head_bytes']:
            group='head_other'
            if clip<=ip<dense:group='input_clip_and_bias'
            elif dense<=ip<end:group='dense_loop'
            elif end<=ip<output_end:group='hidden_clip_and_output'
            if ip in lookup:opcodes[lookup[ip]['mnemonic']]+=n
        else:group='outside_head'
        counts[group]+=n;local[group]+=n
    per_position.setdefault(record['position'],collections.Counter()).update(local)
overhead=[]
for record in samples['records']:
    if record['sampled']:
        other=next(r for r in samples['records'] if not r['sampled'] and r['position']==record['position'] and r['repeat']==record['repeat'])
        overhead.append((record['nodes']/record['wall_seconds'])/(other['nodes']/other['wall_seconds']))
out=dict(counts=counts,per_position=per_position,head_sample_mnemonics=opcodes,
    regions=dict(clip=clip,dense=dense,dense_end=end,output_end=output_end),
    dense_loop_instructions=ins[dense_index-1:end_index+1],
    sampling_speed_ratio=dict(median=s.median(overhead),minimum=min(overhead),maximum=max(overhead)),
    valid_samples=sum(counts.values()),failed_samples=sum(r['failed_samples'] for r in samples['records']),
    suspension_ns_median=s.median(v for r in samples['records'] for v in r['suspension_ns']),
    note='Exact baseline engine. Coarse exclusive instruction pointers, four selected positions; suspension/inlining bias, no hardware events. Region boundaries come from the actual CLIP branch and back-edge, not whole-dispatch counts. Output includes clipping, reduction and stores, not isolated branch cycles.')
p.save('profile-analysis.json',out)
print(out)
