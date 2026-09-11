"""The runner: one run, to completion, then exit.

Not a service, and the distinction is load-bearing. A run lasts hours, which no HTTP request
survives, and there must be **exactly one process per run** -- two runners on one run means
attacking the same assistant twice. An autoscaled service behind a load balancer fights that
invariant; a job execution gives it for free, because an execution *is* a process.

All the state here lives in memory and none of it is ours to keep. What is not in the store does
not exist, and a runner that dies and comes back walks the same path to the same place, because
nothing depends on memory of the previous attempt. This is the only process where generation and
conduction meet: it pulls the knowledge base, generates the probes, and then attacks -- and the
packages it composes cannot import each other, so the two halves meet here and nowhere else.
"""
