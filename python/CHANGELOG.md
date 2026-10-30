# Changelog

## 0.8.0

- The SDK supports and requires CPython 3.15; 3.14 is no longer supported. The private binding's wheels are built
  for the CPython 3.15 stable ABI.
- One Action invocation imports only the invoked Action's module, after the whole project is still validated
  statically, so it runs no other Action's module code.
- An invocation loads the failure-redaction code only when the Action fails, and the build-time bridge commands no
  longer import the event loop or the Action runtime.
- The static catalog extraction walks each Creator file once instead of four times, with the same uses and refusals.
- Catalog and request text rules read printability and general categories from the Assistant protocol's pinned
  Unicode 16.0.0 table instead of the interpreter's, so text Team refuses is refused here too.
- Contract generation refuses a repetition count with a leading zero and a schema whose distinct patterns prepare
  beyond half of one payload's matching budget, exactly as Developers publication does.
