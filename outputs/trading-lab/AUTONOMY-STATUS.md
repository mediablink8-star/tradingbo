# Current automation status

| Capability | Status |
|---|---|
| Active instruments | Five supported Forex pairs only |
| AI committee | Six agents; every response required for an AI paper action |
| Risk controls | Deterministic paper limits remain authoritative |
| Automation | Operator-started; off after restart; five-minute default interval |
| Model limits | Six-call minimum per cycle; daily call and spend caps enforced |
| Audit | Persistent quote snapshot, recommendation, gate, paper action and account |
| Broker access | None; no IB Gateway adapter or live orders |
| Local executor | Loopback control service, durable kill switch and signed replay-safe disarm commands; no arm/order endpoint |
| Render | Deployed Forex-only release; health and API universe verified |

See [the roadmap](AUTONOMY-ROADMAP.md) and [release boundary](LIVE-AUTONOMY.md)
for completed stages and outstanding live-trading requirements.
