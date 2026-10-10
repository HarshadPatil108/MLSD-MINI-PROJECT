# Rule: Guardrails & Defensive Boundaries

1. **Advisory Invariant:** The system strictly produces advisory guidance and **never executes remediation**. Any output containing executable shell scripts or unauthorized system instructions is blocked.
2. **Prompt-Injection Defense:** Every free-text field reaching a model (e.g., `on_call_note`, raw alert messages) must pass through prompt-injection detection before invocation. Injected instructions embedded in alert text must be quarantined and never executed.
3. **Untrusted Data Boundary:** All incoming alerts, on-call notes, and retrieved tool outputs are treated strictly as **untrusted data**, never as system prompts or instructions.
4. **Toxicity Detection:** Real-time toxicity filtering must run on both incoming requests and generated assistant outputs to prevent harmful, abusive, or malicious content.
5. **Output Authorization Filter:** The system must not issue determinations it is not authorized to make. Cause class must strictly belong to the allowed categorical enum (`saturation`, `contention`, `configuration`, `dependency failure`, `data-volume`), and routing must strictly follow authorized targets (`self-serve runbook`, `page-secondary`, `incident-commander`).
