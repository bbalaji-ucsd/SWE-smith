"""
Contract-violation bug generation.

This module generates bugs by analyzing inter-function dependencies within a file
and asking an LLM to introduce subtle contract violations — bugs that break the
implicit agreements between caller and callee (return value semantics, side effects,
precondition handling, etc.).

Unlike procedural modifiers (which apply syntactic transforms) or single-function
LLM modification (which mutates code in isolation), this approach produces bugs
that are realistic, hard to detect, and exercise cross-function reasoning.
"""
