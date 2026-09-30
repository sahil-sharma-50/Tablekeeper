# Delivery ownership

Workspace: C:\Users\sahil\Desktop\BAND - Dark Factory\submission\tablekeeper-v4

Read-only input: C:\Users\sahil\Desktop\BAND - Dark Factory\factory\tablekeeper-v4
Pinned challenge: C:\Users\sahil\Desktop\BAND - Dark Factory\challenge at 803560d2a678ace1414465c098eb0ab5380ffade.

The full assignment is preserved in requirements.md. All four embedded specifications match the pinned originals after CRLF normalization. TASK.md has raw SHA256 44c1a170d7beab5f26d0c2bc683edce0b992a5500d33c8f7efa5d3c02255ce42; normalizing CRLF to LF produces the dispatched SHA256 370f2b750a2e221f064f9452d0de6b716a50fc00f2bfea98f290e6abefd8489b. Inputs remain untouched.

| Seat | Exclusive writable paths |
| --- | --- |
| Lead | Root integration documents, .gitattributes, .gitignore, mandates/, requirements.md; stage copy orchestration |
| Backend | stage-N/server/** and stage-N/checks/backend/** |
| Frontend | stage-N/web/**, stage-N/Dockerfile, stage-N/.dockerignore, stage-N/requirements.txt, stage-N/RUN.md, stage-N/demo/**, stage-N/DESIGN.md |
| QA | checks/**, evidence/**, COVERAGE.md |

N is the current authorized stage only. Each stage is accepted at an exact committed revision before copying it forward. No later features enter earlier snapshots. The lead performs copies only with all writers idle; engineers then extend their respective paths.

Server entry point: server.app:app. Container working directory: /app. Python 3.12, one Uvicorn worker, PORT default 8080. Compiled UI is /app/static and server owns same-origin static/SPA routing beginning with stage 2. Dependency pins are frontend-owned after agreement with backend. Backend reports required pins before container implementation.

Commit protocol: request lead token before staging or committing; stage explicit completed owned files only; report full SHA, checks and remaining gaps; explicitly release token. No amend, rebase or squash. Lead bootstrap token is released before engineering commits. QA checks integrated committed source and records its SHA; documentation-only commits reuse unchanged-source evidence.

Acceptance requires official isolated stage suites plus independent uncovered-contract checks. QA preserves real failures and routes defects to owner and lead; only committed fixes can pass review. Final fresh clone runs --all. No source/test copying from old results or other products, no nested agents, no secrets or populated exports in logs.

Human-authored README.md, FACTORY.md, authentic room download and publication remain participant gates. Mandates are copied unchanged as requested; their missing Harness/Model header lines must be reported honestly rather than silently altering official inputs.
