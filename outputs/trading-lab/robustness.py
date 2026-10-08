"""Research robustness checks for deterministic FX strategies.

These checks stay offline: they evaluate hypothetical historical signals and do
not place orders or connect to a broker.
"""
import statistics

def sensitivity(candles, backtester_factory, strategy_factories):
    out={}
    for name,factory in strategy_factories.items():
        result=backtester_factory().run(candles,factory)
        out[name]={
            "return_pct":result["return_pct"],
            "sharpe":result["sharpe"],
            "max_drawdown":result["max_drawdown"],
            "profit_factor":result["profit_factor"],
            "expectancy":result["expectancy"],
            "trades":len(result["trades"]),
        }
    return out

def robustness_summary(results):
    if not results:
        return {"strategies":0,"median_sharpe":0.0,"median_return_pct":0.0,"median_max_drawdown":0.0}
    sharpes=[float(x["sharpe"]) for x in results.values()]
    returns=[float(x["return_pct"]) for x in results.values()]
    drawdowns=[float(x["max_drawdown"]) for x in results.values()]
    return {
        "strategies":len(results),
        "median_sharpe":statistics.median(sharpes),
        "median_return_pct":statistics.median(returns),
        "median_max_drawdown":statistics.median(drawdowns),
    }
