# Learnings

Notes and concepts picked up while building this project.

---

## Spec vs Steering Doc

| | Steering Doc | Spec |
|---|---|---|
| **Scope** | The whole app — all decisions, all time | One feature or bugfix |
| **Purpose** | "What is this app and how does it work?" | "What are we building next and how?" |
| **Lifespan** | Permanent, evolves with the project | Created per feature, completed when done |
| **Content** | Schema, API contracts, UI behavior, design decisions | Requirements → Design → Task list |
| **Used by** | Kiro on every interaction (always loaded) | Kiro during implementation of that feature |

### Steering Doc (`.kiro/steering/`)

The source of truth for the entire application. It's always loaded into context so Kiro understands the project regardless of what you ask. Contains:

- Database schema
- API contracts
- UI behavior
- Architecture decisions
- Technology stack
- Validation rules

Think of it as the "what exists today" document.

### Spec (`.kiro/specs/<feature-name>/`)

A focused plan for a single piece of work. It has three documents:

1. **requirements.md** — What needs to happen (user stories + acceptance criteria). You review and approve before any code is written.
2. **design.md** — How it'll be built (architecture, data flow, component interactions, correctness properties). You review again.
3. **tasks.md** — Ordered implementation checklist. Kiro executes these one by one, marking them complete as it goes.

Think of it as the "what we're building next" document.

### Why use a spec?

- **Control** — You approve requirements and design before implementation starts. No surprises.
- **Trackable progress** — Tasks have checkboxes. You can see exactly what's done and what's left.
- **Resumable** — If context resets or you come back later, the spec files tell Kiro exactly where things left off.
- **Correctness** — Acceptance criteria become testable properties. You know when something is "done."
- **Scope management** — Requirements are explicit. Prevents scope creep or missed features.

### When to use which?

- **Steering doc**: Update when you make a permanent decision about the app (new API endpoint, schema change, architecture shift).
- **Spec**: Create when you're about to build something non-trivial that benefits from planning before coding.
