"""Alquimia red-teaming app.

Probes deployed Alquimia agents as black boxes and emits findings. This package is the
deployable unit (k8s / OpenShift / Railway). It knows nothing about the Boltzmann brain:
it reads knowledge and writes findings through data-artifact ports (``redteam.ports``),
never through vitruvio or any brain API.

Modules:
- ``redteam.ports``   — KnowledgeSource / FindingsSink + file adapters (the boundary).
- ``redteam.targets`` — TargetAssistant HTTP adapter for the agent under test.
- ``redteam.config``  — settings (agent endpoint, knowledge/findings paths).
- ``redteam.cli``     — the ``redteam`` entry point.
"""

__version__ = "0.1.0"
