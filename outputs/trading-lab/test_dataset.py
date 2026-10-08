import unittest
from datetime import datetime,timezone,timedelta
from backtest import Candle
from dataset import validate

class DatasetTests(unittest.TestCase):
 def test_clean_series(self):
  c=[Candle(datetime(2026,1,i,tzinfo=timezone.utc).timestamp(),1,1,1,1) for i in (1,2,3)]
  r=validate(c);self.assertEqual(r["duplicates"],0);self.assertEqual(r["non_monotonic"],0);self.assertEqual(r["gaps"],0)
 def test_duplicate_is_detected(self):
  c=[Candle(1,1,1,1,1),Candle(1,1,1,1,1),Candle(2,1,1,1,1)]
  self.assertEqual(validate(c)["duplicates"],1)

if __name__=="__main__":unittest.main()
