"""Inspect actual compiler output and local PDB function sizes; no profiler install."""
import collections
import ctypes as c
from ctypes import wintypes as w
import json
import re
import experiment as p

def function_assembly(label):
    text=(p.ART/(label+'.s')).read_text()
    marker='\n_ZN8chesslab17nnue_side_to_moveERKN5chess5BoardERKNS_15NnueAccumulatorE:'
    start=text.index(marker)
    end=text.index('\n\t.seh_endproc',start)
    body=text[start:end]
    lines=[];instructions=collections.Counter();branches=collections.Counter()
    for line in body.splitlines():
        match=re.match(r'\s+([a-z][a-z0-9]+)\s+([^#]*)',line)
        if match:
            name=match[1];instructions[name]+=1
            if name.startswith('j'):branches[name]+=1
            lines.append(line.split('#')[0].rstrip())
        elif re.match(r'^\.LBB|^_ZN|\s*\.seh_stackalloc',line):lines.append(line)
    (p.ROOT/(label+'-head-assembly.txt')).write_text('\n'.join(lines)+'\n')
    return {'static_instructions':instructions,'static_branches':branches,
            'seh_stackalloc_bytes':[int(v) for v in re.findall(r'\.seh_stackalloc\s+(\d+)',body)],
            'annotated_spills':len(re.findall(r'\bSpill\b',body)),
            'annotated_reloads':len(re.findall(r'\bReload\b',body)),
            'callee_saved_xmm_slots':len(re.findall(r'\.seh_savexmm',body)),
            'fma_instructions':sum(n for k,n in instructions.items() if k.startswith(('vfm','vfnm'))),
            'note':'Dispatch function contains both the unchanged integer branch and original scalar path. Counts are static assembly, not dynamic execution counts, cycles or miss rates. Stack stores can be explicit buffers/callee saves, not necessarily spills.'}

class Symbol(c.Structure):
    _fields_=[('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_uint64*2),('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_uint64),('Flags',w.ULONG),('Value',c.c_uint64),('Address',c.c_uint64),('Register',w.ULONG),('Scope',w.ULONG),('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*2048)]

def pdb_sizes():
    kernel=c.WinDLL('kernel32');kernel.GetCurrentProcess.restype=w.HANDLE
    process=kernel.GetCurrentProcess();dbg=c.WinDLL('dbghelp',use_last_error=True)
    dbg.SymSetOptions.argtypes=[w.DWORD];dbg.SymSetOptions(0x2|0x4|0x200|0x400|0x80000)
    dbg.SymInitialize.argtypes=[w.HANDLE,c.c_char_p,w.BOOL];dbg.SymInitialize.restype=w.BOOL
    dbg.SymLoadModuleExW.argtypes=[w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD];dbg.SymLoadModuleExW.restype=c.c_uint64
    dbg.SymFromName.argtypes=[w.HANDLE,c.c_char_p,c.POINTER(Symbol)];dbg.SymFromName.restype=w.BOOL
    dbg.SymCleanup.argtypes=[w.HANDLE]
    if not dbg.SymInitialize(process,str(p.ART).encode(),False):raise c.WinError(c.get_last_error())
    out={}
    try:
        for i,label in enumerate(['baseline','variant']):
            module=label+'64';path=p.ART/label/'engine.exe'
            base=dbg.SymLoadModuleExW(process,None,str(path),module,0x180000000+i*0x10000000,0,None,0)
            if not base:raise c.WinError(c.get_last_error())
            info=Symbol();info.SizeOfStruct=88;info.MaxNameLen=2048
            if not dbg.SymFromName(process,(module+'!chesslab::nnue_side_to_move').encode(),c.byref(info)):raise c.WinError(c.get_last_error())
            out[label]={'function_bytes':info.Size,'rva':hex(info.Address-base),'symbol':info.Name.decode()}
    finally:dbg.SymCleanup(process)
    return out

out={label:function_assembly(label) for label in ['baseline','variant']}
out['pdb_function_sizes']=pdb_sizes()
config=p.common.load(p.ROOT/'build-variant-engine.json')
# A cached Zig -v invocation can emit nothing. CodeView records the actual
# compiler command in the generated assembly, including its effective ISA set.
features=(p.ART/'variant.s').read_text().replace('\\','')
out['compiler_trace_source']='CodeView command embedded in generated variant assembly'
out['compiler_cpu']=sorted(set(re.findall(r'"?-target-cpu"?\s+"?([a-zA-Z0-9_-]+)',features)))
out['avx2_codegen_enabled']=bool(re.search(r'"?-target-feature"?\s+"?\+avx2',features))
out['fma_contraction_disabled']='-ffp-contract=off' in config['command']
assert all(out[label]['fma_instructions']==0 for label in ['baseline','variant'])
assert out['variant']['static_instructions'].get('vmaxps',0)>0 and out['variant']['static_instructions'].get('vminps',0)>0
p.save('assembly-audit.json',out)
print(json.dumps(out,indent=2))
