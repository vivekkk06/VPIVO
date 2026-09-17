"""Integration layer: the boundary between automation logic and a target system.

The automation service depends on the `HRApplication` protocol, never on a concrete
adapter. Three adapters satisfy it -- an in-memory mock, a real browser, and a REST
API client -- and none of them contains safety or policy logic.
"""
