# Bug Report: Analysis of 10 Generated Instances

This document walks through each of the 10 generated bugs, explains the
mechanism, and discusses what makes each one interesting from the perspective
of evaluating coding agents.

All bugs target [MonkeyType](https://github.com/Instagram/MonkeyType), a
Python library that collects runtime type information and generates type
annotations. The codebase has 368 tests and 299 code entities across modules
for encoding, stub generation, type analysis, tracing, and CLI tooling.

---

## Contract Violation Bugs

### Bug 1: `contract_violation__2opq6lvu`
**File:** `monkeytype/encoding.py` | **Tests broken:** 1 | **Diff:** +1/−1

```diff
-        except Exception:
+        except TypeError:
```

`serialize_traces` is a generator that yields serialized trace rows. The
original catches *any* exception during serialization, logs it, and continues
to the next trace. The bug narrows the catch to `TypeError` only.

**Why it's interesting.** The single failing test (`test_log_failure_and_continue`)
passes a trace that raises a non-TypeError exception. An agent sees one
failing test in `test_encoding.py` and must figure out that the issue is an
overly narrow exception handler — a pattern that looks perfectly reasonable
in isolation. The function still works for all traces that either succeed or
fail with TypeError. The agent must understand the *contract* that this
function promises to be resilient to all serialization failures, not just
type errors.

---

### Bug 2: `contract_violation__fu4p89oi`
**File:** `monkeytype/encoding.py` | **Tests broken:** 1 | **Diff:** +3/−1

```diff
-    if (encoded is None) or (encoded == "null"):
+    if encoded is None:
         return None
+    if encoded == "null":
+        return decode(encoded)
     return decode(encoded)
```

`maybe_decode_type` is supposed to treat both `None` and the string `"null"`
as "no type" and return `None`. The bug splits the condition and routes
`"null"` through the decoder instead of short-circuiting.

**Why it's interesting.** The code looks like a reasonable refactor — someone
might argue that `"null"` should be decoded rather than silently dropped.
The bug is in the *semantics* of the split, not the syntax. Only one test
catches this: it specifically passes `"null"` and expects `None` back. An
agent with minimal test signal must understand the function's role in the
serialization pipeline to know that `"null"` is a sentinel, not a valid
encoded type.

---

### Bug 3: `contract_violation__phv96u4q`
**File:** `monkeytype/stubs.py` | **Tests broken:** 12 | **Diff:** +1/−1

```diff
-        if not _is_optional(param.annotation) and param.default is None:
+        if not _is_optional(param.annotation) and param.default is not None:
```

`get_imports_for_signature` decides whether to add `Optional` to the import
map for each parameter. The original logic: if the parameter isn't already
Optional and its default is `None`, add the Optional import (because a
`None` default implies the parameter should be `Optional`). The bug inverts
the condition — now it adds Optional for parameters with non-None defaults
and skips it for None defaults.

**Why it's interesting.** This is a classic condition inversion — `is None`
→ `is not None`. It breaks 12 tests across two test files (`test_stubs.py`
and `test_cli.py`), which gives the agent plenty of signal. But the fix
requires understanding the *semantic meaning* of the condition: why `None`
defaults imply Optional. An agent that pattern-matches on "invert the
condition" would fix it, but an agent that tries to reason from first
principles must understand Python's parameter default semantics.

Notably, both the contract violation and refactoring drift strategies
independently produced this exact same bug — the `is None`/`is not None`
inversion is a natural attractor for both approaches. We kept only the
contract violation version to avoid duplication.

---

### Bug 4: `contract_violation__ssmtghz1`
**File:** `monkeytype/encoding.py` | **Tests broken:** 13 | **Diff:** +2/−0

```diff
     type_dict = json.loads(typ_json)
+    if "elem_types" in type_dict:
+        type_dict = {k: v for k, v in type_dict.items() if k != "elem_types"}
     return type_from_dict(type_dict)
```

`type_from_json` deserializes a JSON string back into a Python type. The bug
adds a filter that strips `elem_types` from the dictionary before passing it
to `type_from_dict`. This means generic types like `Dict[int, str]` lose
their element type information and become bare `Dict`.

**Why it's interesting.** The bug is an *addition*, not a modification — the
original code is still there, just with a new filter prepended. This makes
it harder to detect via simple diff analysis because there's no "changed
line" to focus on. The agent must understand that `elem_types` is the key
that carries generic type parameters and that stripping it silently degrades
the output rather than causing an error. 13 tests fail, all round-trip tests
for generic types.

---

## Refactoring Drift Bugs

### Bug 5: `refactor_drift__05o1fv9q`
**File:** `monkeytype/encoding.py` | **Tests broken:** 1 | **Diff:** +2/−1

```diff
-    type_dict = json.loads(typ_json)
+    import ast
+    type_dict = ast.literal_eval(typ_json)
```

The bug replaces `json.loads` with `ast.literal_eval` in `type_from_json`.
Both parse string representations of data structures, but they handle
different formats. JSON uses `null`, `true`, `false`; Python literals use
`None`, `True`, `False`.

**Why it's interesting.** This looks like a plausible "use stdlib instead of
json" cleanup. It works for simple types (integers, strings, plain dicts)
because their JSON and Python literal representations overlap. It only fails
for TypedDict round-trips where the serialized form contains JSON-specific
syntax. Only one test catches this — the TypedDict round-trip test. An agent
must understand the subtle format differences between JSON and Python
literals, which is exactly the kind of library-specific knowledge that agents
struggle with.

---

### Bug 6: `refactor_drift__teococyw`
**File:** `monkeytype/encoding.py` | **Tests broken:** 1 | **Diff:** +1/−1

```diff
-    if (encoded is None) or (encoded == "null"):
+    if not encoded:
```

This simplifies the None-or-null check to a truthiness check. It looks like
a standard Python cleanup — replacing an explicit disjunction with a more
Pythonic `not` check.

**Why it's interesting.** This is the hardest bug in the set. The diff is
one line, only one test fails, and the change looks like an improvement. The
behavioral drift: `not encoded` also catches empty strings, zero, empty
lists, and other falsy values. In this codebase, the only case that matters
is the string `"null"` — but the truthiness change means `"null"` (a truthy
string) is now *not* caught, so it falls through to the decoder. The agent
must understand Python truthiness semantics and realize that `"null"` is
truthy (non-empty string) while the original code explicitly checked for it.
This is a one-line fix with minimal signal — the kind of bug that tests
whether an agent can reason about language semantics rather than just
pattern-match on test output.

---

## Multi-Site Bugs

### Bug 7: `multi_site__jb2mkutw`
**Files:** `monkeytype/compat.py`, `monkeytype/encoding.py` | **Tests broken:** 9

```diff
 # compat.py: qualname_of_generic now returns (name, module) tuple instead of str
-def qualname_of_generic(typ: Any) -> str:
-    return str(...)
+def qualname_of_generic(typ: Any) -> tuple:
+    ...
+    return (name, module_override)

 # encoding.py: type_to_dict unpacks the tuple (coordinated caller)
-        qualname = qualname_of_generic(typ)
+        qualname, _ = qualname_of_generic(typ)
```

`qualname_of_generic` is changed to return a tuple instead of a string. The
coordinated caller in `encoding.py` is updated to unpack it. But
`get_imports_for_annotation` in `stubs.py` still calls `qualname_of_generic`
and expects a string — it passes the result to string operations that fail
on a tuple.

**Why it's interesting.** The agent sees 9 test failures in `test_stubs.py`.
The failing tests don't directly test `qualname_of_generic` — they test stub
rendering, which calls `get_imports_for_annotation`, which calls
`qualname_of_generic`. The agent must trace through three modules
(compat → stubs → test_stubs) to find the root cause. The coordinated
caller in `encoding.py` looks correct (it unpacks the tuple properly), which
could mislead an agent into thinking `encoding.py` is fine and the bug is
elsewhere.

---

### Bug 8: `multi_site__lyvaed11`
**Files:** `monkeytype/util.py`, `monkeytype/cli.py` | **Tests broken:** 44

```diff
 # util.py: get_name_in_module now returns (obj, module) tuple
-    return obj
+    return (obj, module)

 # cli.py: get_monkeytype_config unpacks the tuple (coordinated caller)
-        config = get_name_in_module(module, qualname)
+        config, _ = get_name_in_module(module, qualname)
```

`get_name_in_module` is a core utility used across the codebase — by
`encoding.py` (for type deserialization), `stubs.py` (for callable lookup),
and `cli.py` (for config loading). The bug changes its return type from a
single object to a tuple. Only `cli.py` is updated to handle the new return
type.

**Why it's interesting.** This breaks 44 tests — the most of any bug — across
5 test files. The sheer breadth of failures gives the agent lots of signal
but also lots of noise. The agent must identify that the root cause is in
`util.py` (a 2-line change) despite failures appearing in CLI tests,
encoding tests, stub tests, and database tests. The coordinated caller in
`cli.py` works correctly, which could lead an agent to focus on the wrong
file. This tests whether agents can identify a single root cause from a
cascade of cross-module failures.

---

### Bug 9: `multi_site__ugn4y34m`
**Files:** `monkeytype/util.py`, `monkeytype/stubs.py` | **Tests broken:** 5

```diff
 # util.py: pascal_case returns a list instead of a string
-    return "".join(
+    return [
         a[0].upper() + a[1:] for a in re.split("([^a-zA-Z0-9])", s) if a.isalnum()
-    )
+    ]

 # stubs.py: get_typed_dict_class_name joins the list (coordinated caller)
-    return f"{pascal_case(parameter_name)}TypedDict__RENAME_ME__"
+    return f"{''.join(pascal_case(parameter_name))}TypedDict__RENAME_ME__"
```

`pascal_case` is changed from returning a joined string to returning a list
of capitalized segments. The coordinated caller in `stubs.py` wraps it with
`''.join()` to compensate. But direct callers of `pascal_case` in tests
expect a string.

**Why it's interesting.** The coordinated caller's fix is subtle — wrapping
with `''.join()` inside an f-string. The f-string still works with a list
(it calls `str()` on it), but the `''.join()` makes it produce the correct
string. An agent must notice that `pascal_case` itself is the problem, not
the callers. The 5 failing tests are all in `test_util.py` testing
`pascal_case` directly, which gives a clear signal — but the agent still
needs to fix `pascal_case` in `util.py` AND revert the compensating change
in `stubs.py` to fully resolve the issue.

---

### Bug 10: `multi_site__x0jlc96y`
**Files:** `monkeytype/typing.py`, `monkeytype/stubs.py` | **Tests broken:** 31

```diff
 # typing.py: field_annotations returns a dict instead of a tuple
-    return (
-        typed_dict.__annotations__["required_fields"].__annotations__,
-        typed_dict.__annotations__["optional_fields"].__annotations__,
-    )
+    return {
+        "required": typed_dict.__annotations__["required_fields"].__annotations__,
+        "optional": typed_dict.__annotations__["optional_fields"].__annotations__,
+    }

 # stubs.py: rewrite_anonymous_TypedDict uses dict keys (coordinated caller)
-        required_fields, optional_fields = field_annotations(typed_dict)
+        annotations = field_annotations(typed_dict)
+        required_fields = annotations["required"]
+        optional_fields = annotations["optional"]
```

`field_annotations` is changed from returning a 2-tuple to returning a dict
with `"required"` and `"optional"` keys. The coordinated caller in `stubs.py`
is updated to use dict access. But other callers that unpack the tuple
(`required, optional = field_annotations(td)`) break.

**Why it's interesting.** This is the largest multi-site diff (+7/−5 lines)
and breaks 31 tests. The return type change from tuple to dict is a common
real-world refactoring pattern — dicts are more readable than positional
tuples. The coordinated caller's update looks like good code (named access
instead of positional unpacking). An agent must recognize that the "old"
tuple interface is the correct one and revert both changes. This tests
whether agents can identify the migration direction — which version of the
API is canonical — when both versions look reasonable.

---

## Summary

| Category | Count | Avg F2P | Key challenge for agents |
|---|---|---|---|
| Contract Violation | 4 | 6.8 | Trace indirect failures to contract breach |
| Refactoring Drift | 2 | 1.0 | Distinguish cosmetic from semantic changes |
| Multi-Site | 4 | 22.2 | Fix coordinated changes across 2 files |

The bugs span a range of difficulty. The easiest (`multi_site__lyvaed11`,
44 tests broken) gives abundant signal. The hardest (`refactor_drift__teococyw`,
1 test broken, 1-line diff) requires understanding Python truthiness
semantics with almost no signal. The multi-site bugs are structurally the
most complex — they require cross-module reasoning that single-file
benchmarks don't test.
