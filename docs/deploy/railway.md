# Railway

The single-service Railway installation runs the API and launches one subprocess per run.
Use `Dockerfile.railway` with the repository root as the build context. The standalone
`apps/api/Dockerfile` intentionally excludes the runner and cannot serve this topology.

Connect the Railway service to `Alquimia-ai/red-teaming`, branch `main`, with automatic
deployments enabled. Set the Dockerfile path to `Dockerfile.railway`, leave the root directory
at the repository root, and use the image's default start command on port 8080.

Keep the service's existing variables and S3-compatible object store configuration in Railway,
not in Git. Keep `REDTEAM_DISPATCH_BACKEND=local_subprocess`. Connecting a repository does not
copy catalogues or run artifacts; those remain in the configured object store.

This Dockerfile does not change the separate API/runner images or the Kubernetes deployment.
