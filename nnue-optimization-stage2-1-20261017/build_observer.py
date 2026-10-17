"""Isolated workload observer, exact baseline policy; counters perturb timing."""
import difflib
import shutil
import sys
import experiment as p

source=p.ART/'observer-source'
rebuild='--rebuild-unmeasured' in sys.argv
assert not source.exists() or (rebuild and not (p.ROOT/'workload-raw.jsonl').exists()), 'Preserve measured observer'
shutil.copytree(p.ART/'baseline-source',source,dirs_exist_ok=rebuild)
shutil.copy2(p.ROOT/'sort_observer.hpp',source/'sort_observer.hpp')
path=source/'nnue.cpp';text=path.read_text()
text=text.replace('#include "nnue.hpp"','#include "nnue.hpp"\n#include "sort_observer.hpp"')
text=text.replace('    NnueDelta delta;','''    sort_observer::kind = before.isCapture(move) ? 1 : 0;
    if (before.at(move.from()).type() == chess::PieceType::KING) sort_observer::kind=5;
    if (move.typeOf() == chess::Move::CASTLING) sort_observer::kind=3;
    if (move.typeOf() == chess::Move::ENPASSANT) sort_observer::kind=4;
    if (move.typeOf() == chess::Move::PROMOTION) sort_observer::kind=2;
    NnueDelta delta;''',1)
at=text.index('void nnue_update_search_states(')
body=text[at:].replace('std::sort(active.begin(), active.begin() + states.count)',
    'sort_observer::sort(active.data(), states.count, false)',1)
body=body.replace('std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); })',
    'sort_observer::sort(changes, size, true)',1)
text=text[:at]+body
# Rights-changing non-king moves can be identified from state deltas after move.
text=text.replace('    auto states = supplied_states;', '''    auto states = supplied_states;
    if (sort_observer::kind==0) {
        for (int f=768; f<772; ++f) {
            const auto& old=parent.features.active[0];
            const auto& next=states.active[0];
            const bool before=std::find(old.begin(),old.begin()+parent.features.count,f)!=old.begin()+parent.features.count;
            const bool after=std::find(next.begin(),next.begin()+states.count,f)!=next.begin()+states.count;
            if (before!=after) { sort_observer::kind=6; break; }
        }
    }''',1)
path.write_text(text)
path=source/'search.cpp';text=path.read_text()
text=text.replace('#include "nnue.hpp"','#include "nnue.hpp"\n#include "sort_observer.hpp"')
text=text.replace('        profiling::reset();','        profiling::reset();\n        sort_observer::reset();',1)
text=text.replace('        visit(ply, true);','        sort_observer::Phase sort_phase(1);\n        visit(ply, true);',1)
text=text.replace('        // A bounded extension budget','        sort_observer::Phase sort_phase(0);\n        // A bounded extension budget',1)
text=text.replace('                    ScopedNullMove passed(board);',
    '                    sort_observer::kind=7;\n                    ScopedNullMove passed(board);',1)
text=text.replace('        result_.profile = profiling::finish();',
    '        sort_observer::finish(board.getFen(),result_.nodes);\n        result_.profile = profiling::finish();',1)
path.write_text(text)
patch=[]
for name in ['nnue.cpp','search.cpp']:
    patch.extend(difflib.unified_diff((p.ART/'baseline-source'/name).read_text().splitlines(True),
        (source/name).read_text().splitlines(True),fromfile='a/'+name,tofile='b/observer/'+name,n=0))
(p.ROOT/'observer.patch').write_text(''.join(patch))
p.build('observer','engine')
