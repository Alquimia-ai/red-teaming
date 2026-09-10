"""Probe generation for one run.

The only package that sees the knowledge base and the generator model together, and the one the
runner calls first. It never reaches the assistant: what it produces is a probe set written by
digest, and the run's `probes.json` pointing at it.
"""
