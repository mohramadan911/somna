---
name: security-audit
description: Run a checked security audit of the current repo with Somna and explain the results. Use when asked for a security audit, security review, vulnerability scan or "find security bugs" in a repo.
---

# Security audit with Somna

Somna runs the audit as a staged pipeline outside this session, so the findings are checked by code and by
agents that did not write them. Do not try to audit the code yourself first.

1. Make sure you are inside the repo the owner means. Ask before auditing a repo that belongs to a client:
   only audit code the owner is allowed to test.
2. Start it and wait for it to finish (5 to 20 minutes):
   `somna audit "$(git rev-parse --show-toplevel)"`
   To focus on specific attack classes, add `--classes http-auth,cloud` (run `somna audit --help` for the list).
3. The last line prints the report path. Read that report and the findings.json next to it.
4. Tell the owner, most severe first: the confirmed findings with file:line, what is wrong, and the fix.
   List "needs validation" findings separately and say what would confirm them. Mention how many were
   rejected and that the reasons are in the report.
5. Do not run exploit code or change files to prove a finding. The owner saves confirmed findings to memory
   from the Somna page (Review > Save to memory), so future sessions in this repo know about them.

If the repo is not known to Somna yet, tell the owner to open `somna ui`, confirm the repo's client under
Repos, and map it first.
