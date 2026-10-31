"""DecRack: evidence-first decision memory for coding agents.

DecRack reads a public discussion, asks a small open-weight model running in
local Ollama to label the alternatives and acts it contains, checks every
citation in code, and stores the resulting decision records in SQLite.
"""

__version__ = "0.1.0"
