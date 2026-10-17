"""Materialize exactly the two predeclared independent head changes."""
import experiment as p

assert (p.ROOT/'profile-analysis.json').exists()
original=(p.ART/'baseline-source/stage1_head.hpp').read_text()
assert not (p.ROOT/'unroll4_head.hpp').exists(), 'Preserve frozen candidate sources'
needle='    for (int j = 0; j < 2 * w::WIDTH; ++j) {'
assert original.count(needle)==1
unroll=original.replace(needle,'    #pragma clang loop unroll_count(4)\n'+needle,1)
needle='    float output = w::fc2_bias[0];'
assert original.count(needle)==1
hidden=original.replace(needle,
    '    static_assert(w::HIDDEN % 8 == 0, "Hidden clipping requires complete lanes");\n'
    '    clip_inputs(hidden, hidden, w::HIDDEN);\n'+needle,1)
hidden=hidden.replace('w::fc2_weight[h] * std::clamp(hidden[h], 0.0f, 1.0f)',
                      'w::fc2_weight[h] * hidden[h]',1)
(p.ROOT/'unroll4_head.hpp').write_text(unroll)
(p.ROOT/'hiddenclip_head.hpp').write_text(hidden)
p.save('candidate-source-identity.json',dict(baseline_sha256=p.common.sha(p.ART/'baseline-source/stage1_head.hpp'),
    candidates={name:p.common.sha(p.ROOT/(name+'_head.hpp')) for name in ['unroll4','hiddenclip']},
    selection_sha256=p.common.sha(p.ROOT/'candidate-selection.json'),
    profile_sha256=p.common.sha(p.ROOT/'profile-analysis.json')))
print('Created two independent frozen head variants')
