"""Local PDB symbol sizes only; no sampling, search, downloads or cache claims."""
import ctypes as c
from ctypes import wintypes as w
import shutil
import experiment as p


class Symbol(c.Structure):
    _fields_=[('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_uint64*2),
        ('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_uint64),('Flags',w.ULONG),
        ('Value',c.c_uint64),('Address',c.c_uint64),('Register',w.ULONG),('Scope',w.ULONG),
        ('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*2048)]


original=p.REPO/'nnue-optimization-stage2-20261017/artifacts/sort/engine.pdb'
if original.exists() and not (p.ART/'sort/engine.pdb').exists():shutil.copy2(original,p.ART/'sort/engine.pdb')
kernel=c.WinDLL('kernel32');kernel.GetCurrentProcess.restype=w.HANDLE
process=kernel.GetCurrentProcess();dbg=c.WinDLL('dbghelp',use_last_error=True)
dbg.SymSetOptions.argtypes=[w.DWORD];dbg.SymSetOptions(0x2|0x4|0x200|0x400|0x80000)
dbg.SymInitialize.argtypes=[w.HANDLE,c.c_char_p,w.BOOL];dbg.SymInitialize.restype=w.BOOL
dbg.SymLoadModuleExW.argtypes=[w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD]
dbg.SymLoadModuleExW.restype=c.c_uint64
dbg.SymFromName.argtypes=[w.HANDLE,c.c_char_p,c.POINTER(Symbol)];dbg.SymFromName.restype=w.BOOL
Callback=c.WINFUNCTYPE(w.BOOL,c.POINTER(Symbol),w.ULONG,c.c_void_p)
dbg.SymEnumSymbols.argtypes=[w.HANDLE,c.c_uint64,c.c_char_p,Callback,c.c_void_p]
dbg.SymEnumSymbols.restype=w.BOOL
dbg.SymCleanup.argtypes=[w.HANDLE]
assert dbg.SymInitialize(process,str(p.ART).encode(),False)
out={}
try:
    for i,label in enumerate(['baseline','sort','selective']):
        module='stage21_'+label;path=p.ART/label/'engine.exe'
        base=dbg.SymLoadModuleExW(process,None,str(path),module,0x180000000+i*0x10000000,0,None,0)
        if not base:raise c.WinError(c.get_last_error())
        out[label]={}
        matches=[]
        def collect(pointer,unused_size,unused_context):
            info=pointer.contents
            name=c.string_at(c.addressof(info)+Symbol.Name.offset,info.NameLen).decode(errors='replace')
            matches.append(dict(symbol=name,function_bytes=info.Size,rva=hex(info.Address-base),tag=info.Tag))
            return True
        callback=Callback(collect)
        if not dbg.SymEnumSymbols(process,base,b'*nnue_update_search*',callback,None):
            raise c.WinError(c.get_last_error())
        out[label]['enumerated_update_symbols']=matches
        for name in ['nnue_update_search_states','nnue_update_search','nnue_side_to_move']:
            info=Symbol();info.SizeOfStruct=88;info.MaxNameLen=2048
            if not dbg.SymFromName(process,(module+'!chesslab::'+name).encode(),c.byref(info)):
                out[label][name]=dict(unavailable=True,error=c.get_last_error())
            else:out[label][name]=dict(function_bytes=info.Size,rva=hex(info.Address-base),symbol=info.Name.decode())
finally:dbg.SymCleanup(process)
p.save('linked-symbol-sizes.json',dict(builds=out,note='Local final-EXE/PDB function sizes; not runtime cache pressure or cycle measurements. No search was run.'))
print(out)
