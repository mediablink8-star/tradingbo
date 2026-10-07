# Ember Company OS

The Company OS adds organizational autonomy without giving LLMs direct trading authority.

## Loop

Observe -> Research -> Debate -> Decide -> Act -> Measure -> Learn -> Re-plan.

The final market path remains: AI proposals -> deterministic policy/risk controller -> paper execution -> immutable accounting -> independent evaluation.

## Departments

Executive/CEO, Research, Risk, Data, Operations, Performance and Audit.

## New capabilities

- Persistent SQLite company memory for hypotheses, work orders, experiments and audit findings.
- Bounded resource budget for research slots.
- Independent evaluator that scores recorded metrics rather than asking a proposing agent to score itself.
- Executive cycles that turn operational signals into prioritized work.
- First-class audit findings.
- Explicit execution-authority boundary: deterministic controller only.

## Research lifecycle

1. Propose a measurable hypothesis and baseline.
2. Schedule a bounded experiment.
3. Freeze development and evaluation policies.
4. Respect a chronological embargo for lookback, holding and latency.
5. Evaluate from recorded data using the independent evaluator.
6. Store the result in company memory.
7. Let the executive layer create follow-up work; never auto-change production policy.

## Safety

This module has no wallet, signer, exchange, broker or transaction API. It cannot change capital, risk limits or production strategy. It is designed to sit above the existing hard controller.
