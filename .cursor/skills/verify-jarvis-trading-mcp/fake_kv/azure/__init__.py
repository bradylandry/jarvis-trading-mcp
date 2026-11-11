"""Verification scaffolding: a file-backed stand-in for the two Azure SDK modules
friend_mcp.server imports lazily (azure.identity, azure.keyvault.secrets).

Put this directory first on PYTHONPATH. It is a regular package, so it shadows the
real azure namespace package in site-packages. Nothing here opens a socket.
"""
FAKE = True
