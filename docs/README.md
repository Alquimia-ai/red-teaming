# Documentation

Every subdirectory answers exactly one question.

| Folder | Question |
|---|---|
| [`adr/`](adr/) | Why is the system this way? Architecture Decision Records, immutable once accepted. |
| [`architecture/`](architecture/) | What does the system look like today? Components, boundaries, storage layout, the flow of a run. |
| [`components/`](components/) | How does each app work? The API's routes, the runner's pipeline, the command line. |
| [`deploy/`](deploy/) | How is it operated? Local stack, Kubernetes, appliance, cloud, model serving. |
| [`release.md`](release.md) | How does it ship? Images on `develop`, releases on `main`. |
| [`get-started.md`](get-started.md) | Where do I start? One machine, end to end: the command line, a judge, the platform, a run. |

Conventions: folder READMEs are short indexes; diagrams are Mermaid inline so GitHub renders them;
a cross-component decision is an ADR, a per-component behaviour is documented in `components/`.
