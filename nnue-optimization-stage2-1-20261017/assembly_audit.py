"""Inspect generated updater/head code; static counts are not cycle estimates."""
import collections
import re
import sys
import experiment as p

label = sys.argv[1]
out = {'candidate': label, 'note': 'Static assembly from the recorded strict-float compiler command; '
       'counts include inactive dispatch branches, not dynamic costs. No hardware cache/cycle counters available.'}
for build in ['baseline', label]:
    text = (p.ART / build / 'nnue.s').read_text()
    sections = {}
    for kind, token in [('updater', '25nnue_update_search_states'),
                        ('search_wrapper', '18nnue_update_search'), ('head', '17nnue_side_to_move')]:
        match = re.search(r'^_ZN8chesslab' + token + r'[^\n]*:', text, re.M)
        assert match
        body = text[match.start():text.index('\n\t.seh_endproc',match.start())]
        lines = []
        instructions = collections.Counter()
        calls = []
        for line in body.splitlines():
            found = re.match(r'\s+([a-z][a-z0-9]+)\s+([^#]*)',line)
            if found:
                instructions[found[1]] += 1
                lines.append(line.split('#')[0].rstrip())
                if found[1].startswith('call'):
                    calls.append(found[2].strip())
            elif re.match(r'^\.LBB|^_ZN|\s*\.seh_stackalloc',line):
                lines.append(line)
        (p.ROOT / f'{build}-{kind}-assembly.txt').write_text('\n'.join(lines)+'\n')
        sections[kind] = dict(instructions=instructions,calls=calls,
            stack_bytes=[int(v) for v in re.findall(r'\.seh_stackalloc\s+(\d+)',body)],
            fma=sum(v for k,v in instructions.items() if k.startswith(('vfm','vfnm'))))
        assert sections[kind]['fma']==0
    out[build] = sections
assert p.common.sha(p.ART / label / 'engine.exe') == p.common.load(p.ROOT / f'build-{label}-engine.json')['sha256']
assert p.common.sha(p.ART / 'baseline/engine.exe') == p.common.load(p.ROOT / 'plan.json')['baseline_binary_sha256']
out['identical_head_instruction_counts'] = out['baseline']['head']['instructions'] == out[label]['head']['instructions']
out['head_header_sha256'] = p.common.sha(p.ART / label / 'stage1_head.hpp') if (p.ART / label / 'stage1_head.hpp').exists() else p.common.sha(p.ART / (label+'-source') / 'stage1_head.hpp')
assert out['head_header_sha256'] == p.common.sha(p.OLD / 'stage1_head.hpp')
p.save('assembly-audit-' + label + '.json',out)
print({b:{k: {'instructions':sum(v['instructions'].values()),'stack':v['stack_bytes'],
       'sort_calls':sum('sort' in c for c in v['calls'])} for k,v in out[b].items()} for b in ['baseline',label]})
