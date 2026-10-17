"""Disassemble real linked float head and inspect its emitted compiler assembly."""
import collections
import ctypes as c
from ctypes import wintypes as w
import re
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
import experiment as p

label=sys.argv[1] if len(sys.argv)>1 else 'baseline'


class Symbol(c.Structure):
    _fields_=[('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_uint64*2),
        ('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_uint64),('Flags',w.ULONG),
        ('Value',c.c_uint64),('Address',c.c_uint64),('Register',w.ULONG),('Scope',w.ULONG),
        ('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*2048)]


def symbol_info():
    kernel=c.WinDLL('kernel32');kernel.GetCurrentProcess.restype=w.HANDLE
    process=kernel.GetCurrentProcess();dbg=c.WinDLL('dbghelp',use_last_error=True)
    dbg.SymSetOptions.argtypes=[w.DWORD];dbg.SymSetOptions(0x2|0x4|0x200|0x400|0x80000)
    dbg.SymInitialize.argtypes=[w.HANDLE,c.c_char_p,w.BOOL];dbg.SymInitialize.restype=w.BOOL
    dbg.SymLoadModuleExW.argtypes=[w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD]
    dbg.SymLoadModuleExW.restype=c.c_uint64
    dbg.SymFromName.argtypes=[w.HANDLE,c.c_char_p,c.POINTER(Symbol)];dbg.SymFromName.restype=w.BOOL
    dbg.SymCleanup.argtypes=[w.HANDLE]
    assert dbg.SymInitialize(process,str(p.ART/label).encode(),False)
    try:
        base=dbg.SymLoadModuleExW(process,None,str(p.ART/label/'engine.exe'),'stage3',0x180000000,0,None,0)
        assert base
        info=Symbol();info.SizeOfStruct=88;info.MaxNameLen=2048
        assert dbg.SymFromName(process,b'stage3!chesslab::nnue_side_to_move',c.byref(info))
        return info.Address-base,info.Size
    finally:dbg.SymCleanup(process)


blob=(p.ART/label/'engine.exe').read_bytes()
pe=struct.unpack_from('<I',blob,0x3c)[0]
assert blob[pe:pe+4]==b'PE\0\0'
sections=struct.unpack_from('<H',blob,pe+6)[0]
opt_size=struct.unpack_from('<H',blob,pe+20)[0]
optional=pe+24
assert struct.unpack_from('<H',blob,optional)[0]==0x20b
table=optional+opt_size
rva,size=symbol_info()
for i in range(sections):
    row=table+40*i
    virtual_size,virtual_rva,raw_size,raw_offset=struct.unpack_from('<IIII',blob,row+8)
    if virtual_rva<=rva<virtual_rva+max(virtual_size,raw_size):
        offset=raw_offset+rva-virtual_rva
        code=blob[offset:offset+size]
        break
else:raise RuntimeError('Head not mapped to PE section')
decoder=Cs(CS_ARCH_X86,CS_MODE_64)
instructions=[dict(rva=i.address,bytes=i.bytes.hex(),mnemonic=i.mnemonic,operands=i.op_str) for i in decoder.disasm(code,rva)]
assert sum(len(bytes.fromhex(i['bytes'])) for i in instructions)==size
counts=collections.Counter(i['mnemonic'] for i in instructions)
assert not any(name.startswith(('vfm','vfnm')) for name in counts)
out=dict(build=label,engine_sha256=p.common.sha(p.ART/label/'engine.exe'),head_rva=rva,
    head_bytes=size,instructions=instructions,mnemonics=counts,
    static_branches=sum(v for k,v in counts.items() if k.startswith('j')),
    hardware_counters='Unavailable; static disassembly and RIP samples do not establish cache/branch misses or stalls.')
asm=(p.ART/label/'nnue.s').read_text()
start=asm.index('_ZN8chesslab17nnue_side_to_move')
# Skip the .def declaration and find the actual function label.
match=re.search(r'^_ZN8chesslab17nnue_side_to_move[^\n]*:',asm,re.M)
body=asm[match.start():asm.index('\n\t.seh_endproc',match.start())]
out['assembly']=dict(stack_bytes=[int(v) for v in re.findall(r'\.seh_stackalloc\s+(\d+)',body)],
    spills=len(re.findall(r'\bSpill\b',body)),reloads=len(re.findall(r'\bReload\b',body)),
    callee_saved_xmm_slots=len(re.findall(r'\.seh_savexmm',body)),
    note='Includes all retained reference/scalar/quantized dispatch paths; not selected-kernel dynamic spill counts.')
out['isa']=dict(cpu=sorted(set(re.findall(r'"?-target-cpu"?\s+"?([a-zA-Z0-9_-]+)',asm.replace('\\','')))),
    features=sorted(set(re.findall(r'"?-target-feature"?\s+"?([+-][a-zA-Z0-9._-]+)',asm.replace('\\','')))),
    avx2=bool(re.search(r'"?-target-feature"?\s+"?\+avx2',asm.replace('\\',''))),
    contract_off=True)
(p.ROOT/(label+'-head-assembly.txt')).write_text(body)
(p.ROOT/(label+'-linked-head.txt')).write_text('\n'.join(f"{i['rva']:x} {i['bytes']:<24} {i['mnemonic']} {i['operands']}".rstrip() for i in instructions)+'\n')
p.save('head-inspection-'+label+'.json',out)
print(dict(build=label,linked_head_bytes=size,instructions=len(instructions),counts=counts,assembly=out['assembly'],isa=out['isa']))
