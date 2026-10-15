# Forex AI agents

The collaboration layer is designed for FX paper trading. Roles analyze supplied currency-pair observations and may recommend long/short paper actions.

The roles are:
- Market researcher
- Macro analyst
- Strategy analyst
- Risk critic
- Portfolio coordinator

Agents have no wallet, blockchain, broker, signing or arbitrary execution tools. Their output is advisory; the deterministic FX risk layer remains authoritative.

The default scripted provider requires no credentials. OpenAI inference can be enabled through `OPENAI_API_KEY`; never place credentials in source code or chat.

Live-money execution is not enabled by this migration.