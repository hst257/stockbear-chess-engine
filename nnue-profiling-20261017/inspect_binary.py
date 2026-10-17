"""Compare symbolized NNUE function bytes against the preserved release binary."""
import collections
import hashlib
import re
import struct
import run_profile as p
import sample_native

sample_native.symbols(p.common.load(p.ROOT/'native-samples.json'))
symbols=p.common.load(p.ROOT/'native-symbols.json')
modules=p.common.load(p.ROOT/'native-samples.json')['modules']
base=next(m['base'] for m in modules if m['name']=='mapped.exe')

def rva_bytes(path,rva,size):
    data=path.read_bytes();pe=struct.unpack_from('<I',data,60)[0]
    start=pe+24+struct.unpack_from('<H',data,pe+20)[0]
    for i in range(struct.unpack_from('<H',data,pe+6)[0]):
        header=start+40*i
        virtual_size,va,raw_size,offset=struct.unpack_from('<IIII',data,header+8)
        if va<=rva<va+virtual_size:return data[offset+rva-va:offset+rva-va+size]
    raise ValueError(rva)

checks=[]
for target in ['chesslab::nnue_side_to_move','chesslab::nnue_move_delta']:
    value=next(v for v in symbols.values() if v['symbol']==target)
    rva=value['symbol_address']-base;size=value['symbol_size']
    assert size>0
    a=rva_bytes(p.ART/'mapped.exe',rva,size);b=rva_bytes(p.ART/'release/engine.exe',rva,size)
    checks.append({'function':target,'rva':hex(rva),'bytes':size,'identical':a==b,'symbolized_sha256':hashlib.sha256(a).hexdigest(),'release_sha256':hashlib.sha256(b).hexdigest()})
assembly=(p.ART/'nnue.s').read_text()
start=assembly.index('\n_ZN8chesslab17nnue_side_to_move')
end=assembly.index('\n\t.globl\t_ZN8chesslab16nnue_white_score',start)
text=assembly[start:end]
instructions=collections.Counter()
for line in text.splitlines():
    match=re.match(r'\s+([a-z][a-z0-9]+)\s',line)
    if match:instructions[match[1]]+=1
excerpt='\n'.join(line for line in text.splitlines() if re.match(r'\s+(vmulps|vaddps|vbroadcastss|vpmaddwd|vpsr[al]|vucomiss|j[a-z]+)\b',line))
(p.ROOT/'head-instruction-excerpt.txt').write_text(excerpt+'\n')
p.save('binary-inspection.json',{'function_byte_checks':checks,'head_assembly_static_instruction_counts':instructions,'note':'Counts are static compiler output, not retired instructions, dynamic branch counts, cycles or cache events. Frozen scalar-named kernel already autovectorizes float YMM and integer XMM code. No explicit AVX2 implementation added.'})
print(checks)
