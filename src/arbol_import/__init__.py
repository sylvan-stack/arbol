"""`arbol import` (IMP-0, IMP-1): import the sessions of Claude Code, Codex, Kimi Code, Pi and Mimo as archived,
read-only chats.

`readers` holds each tool's reader, which only reads: it never writes to a tool's home (IMP-0.2), and gives the
importer every session in the reader form of IMP-1.
"""
