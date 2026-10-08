import unittest
from unittest.mock import patch
from intraday import load_month,validate

class IntradayTests(unittest.TestCase):
 def test_normalizes_ohlc(self):
  raw={"Time Series FX (15min)":{"2026-01-02 12:00:00":{"1. open":"1.10","2. high":"1.12","3. low":"1.09","4. close":"1.11"}}}
  with patch.dict("os.environ",{"ALPHAVANTAGE_API_KEY":"test"}),patch("intraday._fetch",return_value=raw):
   c=load_month("EUR/USD","2026-01","15min")
  self.assertEqual(len(c),1);self.assertAlmostEqual(c[0].high,1.12)
 def test_detects_gap(self):
  c=load_month.__globals__["Candle"](0,1,1,1,1),load_month.__globals__["Candle"](3600,1,1,1,1)
  r=validate(list(c),15)
  self.assertEqual(r["gaps"],1)

if __name__=="__main__": unittest.main()
