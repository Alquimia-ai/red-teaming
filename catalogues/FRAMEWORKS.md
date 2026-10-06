# Framework coverage

How the families here map onto the recognised red-team frameworks. Nothing in this file is a
catalogue or a probe: it translates between what we measure and what each framework names, so a
report can state coverage honestly and so the gaps are visible in one place.

A row is marked **covered** when a family measures it black box, **partial** when we measure part of
it, **out of scope** when it is infrastructure, training-time or model-internal and so cannot be
probed by talking to a deployed agent, and **not yet** when it is probeable but we have not built
it.

## OWASP AI Agent Security Cheat Sheet

The taxonomy the `security-owasp` family is built from, so coverage is by construction.

| Item | State | Where |
|---|---|---|
| Prompt Injection (direct and indirect) | covered | `security-owasp/prompt-injection` |
| Goal Hijacking | covered | `security-owasp/goal-hijacking` |
| Sensitive Data Exposure | covered | `security-owasp/configuration-disclosure`, `third-party-data` |
| Data Exfiltration | covered | `security-owasp/data-exfiltration` |
| Tool Abuse & Privilege Escalation | covered | `security-owasp/tool-abuse` |
| Excessive Autonomy, High-Impact Action Abuse | covered | `security-owasp/high-impact-actions` |
| Decision and Approval Manipulation | covered | `security-owasp/approval-manipulation` |
| Memory Poisoning | out of scope | fails in a store the probe cannot see; needs a second session and a backend read |
| Denial of Wallet | out of scope | fails in the bill; needs a cost meter on the side that spends |
| Cascading Failures, Console Misconfiguration, Supply Chain | out of scope | multi-agent topology and infrastructure |

## OWASP LLM Top 10 (2025)

A different OWASP list, about the model and the app rather than the agent. Seven of ten land on
families we already have.

| # | Item | State | Where |
|---|---|---|---|
| 01 | Prompt Injection | covered | `security-owasp/prompt-injection` |
| 02 | Sensitive Information Disclosure | covered | `privacy`, `security-owasp/configuration-disclosure`, `third-party-data` |
| 03 | Supply Chain | out of scope | foundation models, APIs, RAG sources: infrastructure |
| 04 | Data and Model Poisoning | out of scope | training-time; not reachable by prompting a deployed agent |
| 05 | Improper Output Handling | partial | the rendering-triggered leak is `security-owasp/data-exfiltration`; the rest is app-side sanitisation |
| 06 | Excessive Agency | covered | `security-owasp/tool-abuse`, `high-impact-actions` |
| 07 | System Prompt Leakage | covered | `security-owasp/configuration-disclosure` |
| 08 | Vector and Embedding Weaknesses | out of scope | RAG store and access control: infrastructure, needs the knowledge base |
| 09 | Misinformation | covered | the grounded RoastMe path (knowledge base) |
| 10 | Unbounded Consumption | out of scope | same as Denial of Wallet: fails in cost, not in text |

## NIST AI 600-1 (Generative AI Profile, 12 risks)

Half are our families under another name. The genuine additions are harmful content and
intellectual property.

| Risk | State | Where / why |
|---|---|---|
| Confabulation | covered | the grounded RoastMe path (knowledge base) |
| Data Privacy | covered | `privacy`, `security-owasp/third-party-data` |
| Harmful Bias and Homogenization | partial | `bias` covers explicit bias; implicit bias needs paired probes we do not run yet |
| Information Security | covered | `security-owasp` |
| Human-AI Configuration | covered | `human-ai-configuration` |
| Information Integrity | partial | fabrication is the grounded RoastMe path (knowledge base); producing persuasive disinformation on demand is not yet |
| Dangerous Content | covered | `harmful-content/dangerous-instructions`, `harm-under-framing` |
| CBRN Information or Capabilities | covered | `harmful-content/dangerous-instructions` |
| Obscene Content | covered | `harmful-content/hateful-or-degrading` |
| Intellectual Property | not yet | reproducing copyrighted or proprietary text; probeable, not built |
| Value Chain, Environmental Impact | out of scope | governance and operational, not a probe |

## NIST AI 100-2 (Adversarial ML taxonomy)

Attack-centric and mostly model-level. Its generative-AI attacks are ours; the rest is not
probeable by talking to a deployed agent.

| Group | State | Where / why |
|---|---|---|
| Direct and indirect prompt injection | covered | `security-owasp/prompt-injection` |
| Agent security, misuse | covered | `security-owasp` |
| Supply chain | out of scope | infrastructure |
| Evasion, poisoning, privacy attacks on the model | out of scope | training and model-internal; a threat-modelling frame, not a prompt catalogue |

## What the gaps add up to

Only two probeable things are missing, and both are known:

- **harmful-content** (NIST: dangerous, CBRN, obscene; promptfoo's harmful datasets). A real
  family, planned. Its attacks are the hardest to author and it is less central for a bank
  pre-sales agent than for a general assistant.
- **implicit bias** and **on-demand disinformation**, both of which need a comparison or a
  generation step the per-response judge does not do yet.

Everything else a framework lists is either already measured by a family above, or is
infrastructure and training-time work that cannot be reached by probing a deployed agent.
