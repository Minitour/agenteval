"""agenteval: unit tests for agents.

Define an agent with capa's capabilities.yaml, write scenarios (prompt +
workspace assets + declarative MCP mocks), write declarative assertions plus
an optional LLM judge, then run the suite from one CI-friendly command.
"""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("agenteval-framework")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0"

