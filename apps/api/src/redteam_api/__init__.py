"""Validate and freeze runs, dispatch runners, publish assets and derive status.

Identical submissions reuse the accepted specification; conflicting requests return 409.
The API never contacts the target or constructs a model."""
