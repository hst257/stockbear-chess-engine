"""Correctness-only internal restoration assertions; never benchmark this binary."""
import difflib
import shutil
import sys
import experiment as p

label = sys.argv[1]
source = p.ART / ('restore-'+label+'-source')
assert not source.exists(), 'Do not overwrite a frozen observer source'
shutil.copytree(p.ART / (label+'-source'),source)
path = source/'search.cpp'
original = path.read_text()
text = original.replace('#include <memory>', '#include <memory>\n#include <stdexcept>\n#include <cstring>')
start = '''        const auto stage2_saved_board = board;
        NnueAccumulator stage2_saved_root;
        if (nnue_stack_) stage2_saved_root = (*nnue_stack_)[0];
'''
text = text.replace('        chess::Movelist moves;\n        generate(moves, board);',
                    start+'        chess::Movelist moves;\n        generate(moves, board);',1)
finish = '''        if (!board.fullyEquals(stage2_saved_board))
            throw std::logic_error("Stage 2 interrupted board restoration failed");
        if (nnue_stack_ && (std::memcmp(&(*nnue_stack_)[0].values,
            &stage2_saved_root.values, sizeof(stage2_saved_root.values)) ||
            (*nnue_stack_)[0].features.active != stage2_saved_root.features.active ||
            (*nnue_stack_)[0].features.count != stage2_saved_root.features.count))
            throw std::logic_error("Stage 2 interrupted root accumulator changed");
'''
text = text.replace('        result_.profile = profiling::finish();',finish+'        result_.profile = profiling::finish();',1)
assert text.count('stage2_saved_board')==2
path.write_text(text)
(p.ROOT/('restoration-'+label+'.patch')).write_text(''.join(difflib.unified_diff(
    original.splitlines(True),text.splitlines(True),fromfile='a/engine/src/search.cpp',tofile='b/observer-only/search.cpp',n=0)))
meta = p.common.load(p.ROOT/('build-'+label+'-engine.json'))
args = [v.replace(str(p.ART/(label+'-source')),str(source)) for v in meta['command']]
out = p.ART/('restore-'+label)/'engine.exe'
out.parent.mkdir(exist_ok=True)
args[-1] = str(out)
p.command(args,'restoration-observer-build')
p.save('build-restoration-observer.json',dict(command=args,sha256=p.common.sha(out),
       search_source_sha256=p.common.sha(path),purpose=__doc__))
print('Built internal board/root restoration assertion observer',flush=True)
