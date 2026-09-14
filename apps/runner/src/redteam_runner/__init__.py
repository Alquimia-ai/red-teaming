"""Execute one run per process, composing generation and conduction.

Durable progress lives in the object store; a relaunched process resumes from that evidence.
The runner is the only application where generation and target conduction meet."""
