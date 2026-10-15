def dispatch(root,cfg,args):
    from .label import benchmark,label
    if args.command=="benchmark": return benchmark(root,cfg)
    if args.command=="label": return label(root,cfg,args.size or 200000,args.limit)
    from .runner import run
    return run(root,cfg)
