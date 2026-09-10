"""The HTTP gate. It validates, freezes, launches, publishes and reads -- and does no work.

The reason it is this thin is that the consumer already has the run's lifecycle in its own records.
Duplicating it here would create two accounts of one truth, which is exactly how they drift apart.
Every answer about a run is derived from the store and from the platform, at the moment it is asked.

It can be killed and replaced without consequence. If it dies between freezing the spec and
launching the runner, the consumer retries on the same run id, and the retry contract is exactly
this: **the same request answers 202 every time, a different request under a frozen id answers
409, and a runner already attacking is a 202 too.**

It never reaches the assistant and never builds a model. It does carry the catalogue package -- and
with it the probe library -- so a bundle can be validated and published synchronously, which is the
trade the design makes for a publishing path with a clear answer.
"""
