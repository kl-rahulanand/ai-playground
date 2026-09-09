"""Week 3 — Sentinel's tool layer.

Sub-modules, in dependency order:

  registry  -> tool DEFINITIONS (schemas sent to Claude) + mocked fictional data
               and the raw execute functions. Knows nothing about permissions.
  policy    -> the application's authority: allow-list, allowed services /
               dependencies, per-identity permissions, and destructive-action
               blocks. This is the "wall" the model cannot move.
  guards    -> pure validation/authorization/limit functions layered in front of
               the registry.
  loop      -> the bounded tool-execution loop that wires Claude <-> guards <->
               registry, enforcing max calls and wall-clock time.

Mental model: registry is a vending machine (dispenses fictional goods); policy
+ guards are the security guard standing in front of it; the loop is the escort
that walks Claude up to the guard and counts how many times it may ask.
"""
