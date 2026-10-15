"""Rolling walk-forward evaluation for FX strategies."""
def walk_forward(candles,backtester,strategy_factory,train_size=500,test_size=100):
    windows=[];start=0
    while start+train_size+test_size<=len(candles):
        train=candles[start:start+train_size];test=candles[start+train_size:start+train_size+test_size]
        # Baseline strategies have fixed parameters; training is deliberately isolated.
        is_result=backtester.run(train,strategy_factory());oos_result=backtester.run(test,strategy_factory())
        windows.append({"train_start":train[0].timestamp,"test_start":test[0].timestamp,"is":is_result,"oos":oos_result})
        start+=test_size
    oos=[w["oos"] for w in windows]
    total=sum(r["return_pct"] for r in oos)
    return {"windows":windows,"oos_windows":len(oos),"profitable_oos_windows":sum(r["return_pct"]>0 for r in oos),"oos_return_pct":total,"oos_sharpe":(sum(r["sharpe"] for r in oos)/len(oos) if oos else 0.0)}
