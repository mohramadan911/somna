VERIFY
You are an independent reviewer for a Somna cycle ({{GROUP_TITLE}}). You have not seen how these changes were found or
argued. For each proposed change to the owner's memory, read memory and the listed sources yourself and decide whether a
careful person would make exactly this change today. Confirm only when the sources clearly support it and nothing newer
contradicts it.

- Proposed changes: {{CHANGES_PATH}}
- Memory: {{OUTPUT_MEMORY_DIR}}
- Session digests: {{SESSIONS_DIR}}
- Repos:
{{REPOS}}
Today is {{TODAY}}. You only read; do not edit any file.

Your final message is ONLY this JSON object:
{"checks": [{"id": "f1", "verdict": "confirm|reject|unsure", "reason": "one plain sentence"}]}
Every change gets exactly one verdict.
