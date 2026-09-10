# Documentation

Every subdirectory answers exactly one question.

| Folder | Question |
|---|---|
| [`adr/`](adr/) | Why is the system this way? Architecture Decision Records, immutable once accepted. |
| [`architecture/`](architecture/) | What does the system look like today? Components, boundaries, storage layout, the flow of a run. |
| `components/` | How does each app work? One folder per app, written as the code lands. |
| `deploy/` | How is it operated? Local stack, Kubernetes, appliance, cloud, model serving. |

Conventions: folder READMEs are short indexes; diagrams are Mermaid inline so GitHub renders them;
a cross-component decision is an ADR, a per-component behaviour is documented in `components/`.
