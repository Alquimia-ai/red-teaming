"""Catalogue documents and the transforms they name.

A catalogue is the client's own risk taxonomy: which families of failure to test (plugins), which
interaction patterns present them (strategies), what the assistant is held to (the contract), which
strategies need a brain and how each probe reaches the assistant.
gaussia ships no catalogue and says why -- a risk taxonomy *is* what the evaluation measures, so a
shipped one would quietly become a cross-user standard nobody chose.

The catalogue is data. A strategy names a construction by key and this package is what turns the
key into configured code: deterministic constructions close over the boundary the corpus attests,
the model-driven one closes over the run's declared context and generator. Everything here runs
without a brain and without a model provider, which is what lets the API validate and publish a
document synchronously.
"""
