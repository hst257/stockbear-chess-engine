"""Read-only CPU-accounting sensitivity; not a replacement primary estimator."""
import collections
import math
import statistics as s
import analyze as a
import validate as v


def main():
    groups=collections.defaultdict(list)
    records=[]
    for pair in v.read_lines('pairs.jsonl'):
        rows={r['binary']:r for r in pair['records']}
        baseline,candidate=rows['baseline'],rows['hiddenclip']
        groups[(baseline['suite'],baseline['mode'],baseline['budget'],baseline['position'])].append((baseline,candidate))
        records.extend(pair['records'])
    out=dict(method='Secondary read-only diagnostic after noticing short-control CPU/wall disagreement; 10000-draw nested CPU-NPS ratio intervals use the same grouped bootstrap and seed. Ratio of summed CPU times per fixture reduces quantized single-search division effects. Neither changes wall primary results or acceptance criteria.',
             accounting_quantum_seconds=1/64,
             deltas_not_on_quantum_grid=sum(abs(r['process_cpu_seconds']*64-round(r['process_cpu_seconds']*64))>1e-7 for r in records),
             cpu_wall_above_one=sum(r['process_cpu_seconds']>r['wall_seconds'] for r in records),
             summaries=[])
    primary=v.load('analysis.json')
    for summary in primary['summaries']:
        suite,mode,budget=summary['suite'],summary['mode'],summary['budget']
        selected=[ps for key,ps in groups.items() if key[:3]==(suite,mode,budget)]
        logs=[]
        summed=[]
        by_build={name:[] for name in ['baseline','hiddenclip']}
        for ps in selected:
            logs.append([math.log(y['cpu_nps']/x['cpu_nps']) for x,y in ps if x['cpu_nps'] and y['cpu_nps']])
            summed.append(math.log((sum(y['nodes'] for x,y in ps)/sum(y['process_cpu_seconds'] for x,y in ps))/
                                   (sum(x['nodes'] for x,y in ps)/sum(x['process_cpu_seconds'] for x,y in ps))))
            for x,y in ps:
                by_build['baseline'].append(x['process_cpu_seconds'])
                by_build['hiddenclip'].append(y['process_cpu_seconds'])
        out['summaries'].append(dict(suite=suite,mode=mode,budget=budget,wall_factor=summary['factor'],
            cpu_factor=summary['cpu_factor'],cpu_diagnostic95=a.interval(logs),
            summed_cpu_nps_factor=math.exp(s.mean(summed)),
            process_cpu_seconds={name:a.describe(values) for name,values in by_build.items()},
            accounting_quantum_over_median_cpu={name:(1/64)/s.median(values) for name,values in by_build.items()}))
    v.save('cpu-diagnostics.json',out)
    for row in out['summaries']:
        print(row['suite'],row['mode'],row['budget'],'CPU',row['cpu_factor'],row['cpu_diagnostic95'],'summed',row['summed_cpu_nps_factor'])


if __name__=='__main__':
    main()
