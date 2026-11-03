# P integrity cache engineering phase

This engineering change preserves the scientific method, prompts, model/image
transform, task reachability, repair rules, exact payload equality, and request
slot namespace. It does not authorize paid calls or establish a new review gate.
The previous run, freeze, provider ledger, run artifacts, gates and changed source
snapshots must remain archived; a replacement engineering freeze and independent
scoped review are required before any continuation. Never patch a running gate.

## Preserved proof

R-PI-1 binds each Gate to an immutable canonical constructor-root string before
conversion. Noncanonical paths and root substitutions are rejected. If a context
exposes `root`, it must match that anchor at construction and on every check;
changing or removing that field is rejected. Current production `context_p.py`
does not expose `ctx.root`: its verifier closes over `_context(root)`, and
`frozen_gate` obtains it through the fixed-ROOT `runtime_context()` entry point
and checks the fixed production ledger directory. That production binding remains
unchanged; contexts without a root field retain their existing interface.

A Gate first runs the complete context source verifier, converts every frozen row
image with the existing `encode_image(..., 'square256')`, and reconstructs the
complete allowed-slot map. That map must equal the ledger slots and its digest
must equal the context's frozen `allowed_slots_sha256` in production. A second
complete source verification closes initialization against changes during this
work. The image fingerprints are retained as a tuple of string pairs, with a
separate digest; row and slot digests are also retained for this Gate's lifetime.

Each subsequent context verification still calls `ctx.verify_sources()` before
using the cache, then compares Gate/context roots to the constructor anchor. This checks full source bytes (including images, conversion code
and assets), the pinned Python/Pillow/other package environment, and live context
integrity. No stat, mtime, size, or filesystem-event shortcut replaces content
hashing. Verification additionally checks the conversion-cache digest, full rows
and their digest, ledger-slot digest, frozen allowed-slot digest, catalog, imports,
and embedding manifest. Duplicate or altered rows cannot disappear into the
sample-id map. Replacing this Gate or process builds the cache again.

For the same frozen input bytes, conversion implementation, Pillow/Python
environment and fixed transform, RGB conversion, bicubic resizing, PNG encoding
and base64 output are deterministic. Their initially verified fingerprints may
therefore be reused while those premises continue to verify. This relies on the
same installed-package/version and trusted-process assumptions as the existing
freeze; it does not claim protection against an attacker able to replace both
in-memory values and their validation anchors. Existing pathname races between
verification and later use are not expanded into an immutable-filesystem claim.

Machine task reconstruction still reads and transforms the actual current query
image normally, and still reconstructs messages from frozen prior answers.
Exact payload comparison and format-repair authorization remain unchanged.

## Performance and verification scope

Previously every Gate validation converted all N cohort images and rebuilt all
allowed slots. A fresh provider request has at least three such validations
(Trace request, ledger bind, provider admission), excluding replay/repair/retry
checks. With N=843 this was at least 2,529 cohort conversions per fresh request.
Now a Gate performs N cohort conversions and one full slot reconstruction during
initialization, and zero cohort conversion/reconstruction operations on repeated
context checks. Per-task query reconstruction still converts its own image.
Every validation still performs all frozen-source content hashing and slot digest
checking. These are operation-count claims, not measured wall-time or CPU savings.

`test_gate_p.py` uses generated synthetic images and local in-memory ledgers.
Operation-count spies observe real conversions during constructor tests; they do
not replace production gates. Tests cover repeated source verification, image,
source, environment, Gate/context root mutation, noncanonical roots, mismatched
constructor/context roots, row, duplicate-row, slot and cache drift, initial frozen-slot
digest mismatch, exact payload equality, and cached-parser-failure repair rules.
No corpus images, labels, paid transport, historical raw answers, or accuracy
outcomes are used for this engineering validation.
