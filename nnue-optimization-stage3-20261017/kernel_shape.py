"""Inspect only the linked CLIP path; keep it separate from fallback counts."""
import collections
import re
import experiment as p

out={}
for label in ['baseline','unroll4','hiddenclip']:
    path=p.ROOT/('head-inspection-'+label+'.json')
    if not path.exists():continue
    data=p.common.load(path);ins=data['instructions']
    dispatch=next(i for i,r in enumerate(ins[:-1]) if r['mnemonic']=='cmp' and r['operands']=='eax, 4')
    guard=int(ins[dispatch+1]['operands'],16)
    clip=next(r['rva'] for r in ins if r['rva']>=guard and r['mnemonic']=='vmaxps')
    multiply=next(r['rva'] for r in ins if r['rva']>clip and r['mnemonic']=='vmulps')
    backedge=next(r for r in ins if r['rva']>multiply and r['mnemonic']=='jne' and clip<=int(r['operands'],16)<=multiply)
    dense=int(backedge['operands'],16)
    end=backedge['rva']+len(bytes.fromhex(backedge['bytes']))
    fallback=min(int(r['operands'],16) for r in ins if guard<=r['rva']<clip and r['mnemonic']=='je' and int(r['operands'],16)>end)
    body=[r for r in ins if dense<=r['rva']<end]
    output=[r for r in ins if end<=r['rva']<fallback]
    counts=collections.Counter(r['mnemonic'] for r in body)
    out[label]=dict(dense_rva=dense,dense_loop_bytes=end-dense,dense_static_instructions=len(body),
        dense_counts=counts,dense_registers=sorted(set(re.findall(r'\b[xyz]mm\d+\b',' '.join(r['operands'] for r in body)))),
        dense_stack_operands=[r for r in body if 'rsp' in r['operands'] or 'rbp' in r['operands']],
        dense_control=[r for r in body if r['mnemonic'] in ['add','sub','cmp','jne']],
        output_static_instructions=len(output),output_counts=collections.Counter(r['mnemonic'] for r in output),
        output_conditional_branches=sum(r['mnemonic'].startswith('j') and r['mnemonic']!='jmp' for r in output),
        note='Selected CLIP path only; static instructions per loop body, not executed cycles. Output spans hidden stores/clipping/reduction, not isolated clipping time.')
p.save('kernel-shapes.json',out)
print(out)
