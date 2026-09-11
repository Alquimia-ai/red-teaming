# Live tests

The tier that reaches real things: an assistant on an Alquimia runtime and a judge on a real
provider. It costs money and needs credentials, so it never runs in CI; a person runs it, on
purpose, with the environment below set. Anything unset skips the test rather than failing it.

| Variable | What |
|---|---|
| `LIVE_ASSISTANT_ENDPOINT` | the runtime's base URL, e.g. `https://runtime.example.com/api` |
| `LIVE_ASSISTANT_ID` | the assistant the registry answers for |
| `LIVE_ASSISTANT_AGENTSPACE` | optional; the runtime's default when unset |
| `LIVE_TARGET_TOKEN` | the runtime's token; the spec names it by this reference |
| `LIVE_JUDGE_MODEL` | the control judge's model id, e.g. a Qwen3 8B served by vLLM or a hosted id |
| `LIVE_JUDGE_PROVIDER` | `openrouter` or `openai_compatible` |
| `LIVE_JUDGE_ENDPOINT` | required for `openai_compatible`: the server's `/v1` |
| `LIVE_JUDGE_KEY` | the judge's credential; the spec names it by this reference |
| `LIVE_REPLICAS` | optional; `1` by default |

```bash
export LIVE_ASSISTANT_ENDPOINT=... LIVE_ASSISTANT_ID=... LIVE_TARGET_TOKEN=...
export LIVE_JUDGE_MODEL=... LIVE_JUDGE_PROVIDER=openrouter LIVE_JUDGE_KEY=...
uv run pytest -m live tests/live -s
```

The test runs the platform in process -- the memory store, the real target adapter, the real judge
-- over the seed's standing half narrowed to its one-turn strategies, and asserts what a real run
must show: every unit closed, a profile graded through the declared serving path (never the
stand-in), and a manifest whose components name the judge that graded. It prints the manifest's
coverage so the person running it can read what the assistant did.
