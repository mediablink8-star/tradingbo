import unittest
from unittest.mock import patch
import historical

class HistoricalTests(unittest.TestCase):
 def test_usd_jpy_cross_rate(self):
  rows=[
   {"date":"2026-01-02","base":"EUR","quote":"JPY","rate":160.0},
   {"date":"2026-01-02","base":"EUR","quote":"USD","rate":1.20},
  ]
  with patch("historical._fetch",return_value=rows):
   c=historical.load_daily("USD/JPY","2026-01-01","2026-01-03")
  self.assertAlmostEqual(c[0].close,160/1.2)
  self.assertEqual(c[0].open,c[0].close)

 def test_json_roundtrip(self):
  import tempfile,os
  from backtest import Candle
  data=[Candle(1,1,1,1,1),Candle(2,1.1,1.1,1.1,1.1)]
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,"x.json");historical.save_json(data,p)
   got=historical.load_json(p)
  self.assertEqual(got,data)

if __name__=="__main__": unittest.main()
