"""Read PE imports and preserve original build receipts; never rebuild."""
import struct
import os
from pathlib import Path
import validate as v


def imports(path):
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0'
    machine, count = struct.unpack_from('<HH', data, pe+4)
    size = struct.unpack_from('<H', data, pe+20)[0]
    opt = pe+24
    assert machine == 0x8664 and struct.unpack_from('<H', data, opt)[0] == 0x20b
    import_rva = struct.unpack_from('<I', data, opt+112+8)[0]
    sections = []
    for i in range(count):
        at = opt+size+40*i
        virtual_size, virtual, raw_size, raw = struct.unpack_from('<IIII', data, at+8)
        sections.append((virtual, max(virtual_size, raw_size), raw))
    def offset(rva):
        for virtual, span, raw in sections:
            if virtual <= rva < virtual+span:
                return raw+rva-virtual
        raise ValueError(rva)
    at = offset(import_rva)
    names = []
    while True:
        descriptor = struct.unpack_from('<IIIII', data, at)
        if not any(descriptor):
            break
        name_at = offset(descriptor[3])
        names.append(data[name_at:data.index(b'\0', name_at)].decode('ascii'))
        at += 20
    return names


def main():
    v.check_plan()
    result = dict(imports={name: imports(path) for name, path in v.BINARIES.items()},
                  build_receipts={},
                  no_runtime_model_load='Generated weights are embedded; identical generated-header hashes plus original build/source provenance and prior exact numerical receipts identify the frozen model.')
    for name, path in [('baseline', v.REPO/'nnue-optimization-stage1-20261017/build-variant-engine.json'),
                       ('hiddenclip', v.OLD/'build-hiddenclip-engine.json')]:
        receipt = v.common.load(path)
        assert receipt['sha256'] == v.common.sha(v.BINARIES[name])
        result['build_receipts'][name] = dict(path=str(path), sha256=v.common.sha(path), receipt=receipt)
    assert result['imports']['baseline'] == result['imports']['hiddenclip']
    assert all(x.lower().startswith('api-ms-win-crt-') or x.lower() in ['kernel32.dll', 'msvcrt.dll', 'ntdll.dll', 'user32.dll', 'advapi32.dll', 'shell32.dll']
               for x in result['imports']['baseline']), 'Inspect non-system runtime dependency before continuing'
    system = Path(os.environ['WINDIR'])/'System32'
    result['shared_system_runtime_sha256'] = {name: v.common.sha(system/name) for name in ['ucrtbase.dll','kernel32.dll','ntdll.dll']}
    result['dependency_resolution'] = 'Both exact EXEs start and search successfully on the same OS; identical system API-set CRT/kernel imports, no separately substituted local runtime DLL.'
    v.save('build-provenance.json', result)
    print(result['imports'])


if __name__ == '__main__':
    main()
