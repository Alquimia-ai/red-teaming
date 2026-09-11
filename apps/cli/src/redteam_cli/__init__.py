"""The `redteam` command line: what an operator types.

It governs runs through the API and never touches the store, the assistant or a model: every
question it asks is an HTTP request, and every answer it keeps lands in the workspace directory
(`.redteam/`) beside the operator's own catalogue bundles and run specs. The one thing it does
outside the API is bring the local stack up and down, through docker compose.

Deliberately small -- the contracts package and an HTTP client -- so it ships as a single file
nobody has to install a Python environment for.
"""
