from __future__ import annotations

from importlib import import_module


def import_mini_eq_module(name: str):
    return import_module(f"mini_eq.{name}")


core = import_mini_eq_module("core")
filter_chain = import_mini_eq_module("filter_chain")
routing = import_mini_eq_module("routing")
instance = import_mini_eq_module("instance")
wireplumber_backend = import_mini_eq_module("wireplumber_backend")
wireplumber_stream_router = import_mini_eq_module("wireplumber_stream_router")
