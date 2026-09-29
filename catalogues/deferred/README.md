# Deferred risks

Two OWASP risks written as valid schema-v2 documents but not shipped. Each fails in a store the
probe cannot see, so all the agent's answer offers is its own account of its state, and a
self-report is not evidence. Spanish only, since they may be rewritten once they can be measured.

| Risk | File | Where it fails | What would unblock it |
|---|---|---|---|
| Memory Poisoning | `memory-poisoning.json` | memory carried to later sessions or other users | a second session against the same store **and** a read of the backend |
| Denial of Wallet | `denial-of-wallet.json` | the bill | a cost meter read from the side that spends: tokens, tool calls, depth |

For memory, a second session alone only upgrades "the agent says so" to "the agent behaves
differently"; behaviour does not identify what was stored. For cost, agreement and spend are not
correlated, so a judge reading text is rating the wrong variable.

Until then, a report must say both were **not measured**.
