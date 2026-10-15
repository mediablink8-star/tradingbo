"""FX quote-provider abstraction.
The paper engine consumes normalized mid/quote data and does not know provider details.
"""
from dataclasses import dataclass
from typing import Protocol
import os,time
@dataclass(frozen=True)
class FXQuote:
    pair:str
    mid:float
    bid:float
    ask:float
    observed:float
    provider_date:str|None
    source:str
class QuoteProvider(Protocol):
    def quotes(self,pairs:list[str])->dict[str,FXQuote]: ...
class FrankfurterProvider:
    def __init__(self,fetcher,spread_bps):
        self.fetcher=fetcher;self.spread_bps=spread_bps
    def quotes(self,pairs):
        raw=self.fetcher(pairs);return raw
