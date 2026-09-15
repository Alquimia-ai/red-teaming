# Packages

Libraries under `packages/`, import names `redteam_<name>`, distributions `red-teaming-<name>`.
What each may import is a guard (`tests/guards/test_isolation.py`); a package absent from the table
cannot be imported by anyone.

```
contracts, settings, secrets, delivery -> nothing
store -> contracts                          dispatch -> contracts, settings, secrets
knowledge -> contracts   (the only importer of pyboltzmann)
judges -> contracts      target -> contracts
catalogue -> contracts, store
probes -> contracts, store, catalogue, knowledge, judges       probes never imports target
engine -> contracts, store, catalogue, target, judges          engine never imports knowledge or probes
api -> contracts, settings, secrets, store, dispatch, catalogue
runner -> composes probes and engine (the only place both meet)
cli -> contracts
```

| Package | Owns |
|---|---|
| `contracts` | the domain types with zero IO: `RunSpec`, `Plan`/`WorkUnit`/`attack_id`, `Trace`, `Manifest`/`Coverage`, `ContractSpec`, `TransportFailure`, `KnowledgeBase` protocol, the run id rule, `ServingPath` |
| `settings` | `REDTEAM_*` settings: the three seams (store, dispatch, secrets) and the cluster's knobs |
| `secrets` | `SecretResolver`: `env` and `file` backends |
| `store` | the append-only `ObjectStore` (memory, S3), the key layout, codecs, versioned assets, the resume difference, manifests |
| `dispatch` | one runner per run: docker, Kubernetes Job, subprocess; `launch` and `status` |
| `delivery` | the bounded, idempotent webhook |
| `knowledge` | the read-only Boltzmann brain client: pull by digest, enumerate completely, prove membership |
| `judges` | chat-model providers (`openrouter`, `openai_compatible`), the logprob grader with retries, the stand-in grader, embeddings |
| `target` | the assistant under test: the Alquimia runtime adapter, replay, typed failures by status name, the safe-mode gate |
| `catalogue` | schema-v2 documents: loading, the transform registry, semantic validation, publishing, the contract binding, an in-memory knowledge base |
| `probes` | one run's probe set: engines per entity kind, the brain enumerator and verifier, content identity, the generation record |
| `engine` | conduction: the governed door, planned deliveries and the attacker, recording, resume, control artifacts, the dataset, `attack` |

Two invariants fall out of the graph rather than out of discipline: generation never reaches the
assistant (`probes` cannot import `target`), and conduction never reads the knowledge base (`engine`
cannot import `knowledge`). The runner is where the two meet, and the API imports neither.
