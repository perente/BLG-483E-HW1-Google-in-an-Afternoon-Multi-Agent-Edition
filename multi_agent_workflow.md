# Multi-Agent Workflow

## Overview

This project was developed with a sequential multi-agent workflow rather than a
single monolithic implementation pass. Each agent had a bounded responsibility,
produced a concrete artifact, and passed that artifact to the next stage as input.
The workflow was designed to keep product definition, architecture, implementation,
review, testing, and documentation aligned while still allowing each step to focus
on a specific engineering concern.

The agent sequence was:

`PRD Agent -> Architecture Agent -> Backend Agent -> Frontend Agent -> Reviewer Agent -> Test Agent -> README Agent`

This sequence was intentional. The goal was not to use agents as isolated one-off
tools, but to create a document-and-implementation pipeline where decisions made in
earlier stages shaped later technical work.

The workflow was also human-guided rather than fully automatic. At each stage, the
student reviewed intermediate outputs, refined instructions, decided which
direction to keep, and used the resulting artifact as input to the next agent.
Agents therefore supported the engineering process, but they did not replace human
judgment or manual coordination between stages.

---

## 1. PRD Agent

### Role

The PRD Agent defined the product scope, core requirements, and user-facing goals
 of the system.

### Inputs

- homework requirements and assignment expectations
- the previous project/repository as reference material
- the need to redesign the system in a multi-agent workflow rather than repeat the
  old project structure directly

### Prompt / Instructions

The PRD Agent was instructed to use the assignment requirements and the previous
repository as reference input, but not to make a literal copy. Instead, it was
asked to define a new crawler and search system that preserved similar functional
goals while being reorganized into a clearer multi-agent-oriented project structure.

The prompt emphasized:

- localhost execution
- crawl and search functionality
- persistent storage
- controlled load and backpressure
- explainable behavior
- a system shape that could later support backend, frontend, testing, and
  documentation as separate workstreams

### Outputs

- `product_prd.md`

### Interactions

The PRD became the primary planning document for the next stage. It was used as
input by the Architecture Agent to turn product requirements into a concrete system
design.

### Key Decisions

- define the system as a localhost web crawler and search platform rather than a
  minimal command-line crawler
- include multiple crawl jobs with isolated state
- separate UI search from assignment-compatible search
- include pause/resume, persistent state, and visibility through CLI/API/frontend

---

## 2. Architecture Agent

### Role

The Architecture Agent translated the PRD into a technical design describing system
layers, data flow, concurrency model, persistence model, and search behavior.

### Inputs

- `product_prd.md`

### Prompt / Instructions

The Architecture Agent was instructed to derive the system design from the PRD and
produce a practical architecture document that could guide implementation. The
prompt asked for a design that stayed simple enough for an educational project, but
was still detailed enough to support real backend and frontend implementation work.

### Outputs

- `crawler_architecture.md`

### Interactions

The architecture document was used as input by both implementation-focused stages.
The Backend Agent used it to define server, crawler, storage, and search behavior.
The Frontend Agent used it to understand API boundaries, job state, search flow,
and monitoring behavior.

### Key Decisions

- use a layered structure: frontend, query/control layer, crawl engine, and
  persistence
- use SQLite in WAL mode for local persistence
- use per-job execution with isolated crawl state
- keep UI search and assignment search as separate paths
- design for pause/resume and bounded backpressure behavior

---

## 3. Backend Agent

### Role

The Backend Agent owned the crawler runtime, API behavior, persistence logic,
search logic, and backend-facing implementation details.

### Inputs

- `product_prd.md`
- `crawler_architecture.md`

### Prompt / Instructions

The Backend Agent was instructed to work in two steps. First, it produced a backend
implementation plan that mapped architecture decisions into files, modules, schema,
and execution steps. Then it implemented backend code based on the architecture and
that plan.

The prompt emphasized:

- preserving alignment with the PRD and architecture
- keeping the implementation local-first and inspectable
- making backend behavior concrete enough for frontend and testing stages to depend
  on

### Outputs

- `agents/backend_implementation_plan.md`
- backend code under `crawler/`

### Interactions

The backend implementation plan became a reference for the backend coding pass. The
implemented backend then became an input surface for the Frontend Agent, Reviewer
Agent, Test Agent, and README Agent.

### Key Decisions

- expose crawl control and search through both CLI and HTTP API
- keep multi-job orchestration explicit in the backend
- preserve assignment-compatible exports through per-job `p_<job_id>.data` files
- implement durable frontier and seen-state persistence to support pause/resume

---

## 4. Frontend Agent

### Role

The Frontend Agent owned the user-facing interface for creating crawl jobs,
monitoring progress, and running UI search.

### Inputs

- `crawler_architecture.md`
- `agents/backend_implementation_plan.md`
- implemented backend/API behavior

### Prompt / Instructions

The Frontend Agent was instructed to use the architecture and backend behavior as
the contract for the UI. It first produced a frontend implementation plan, then
implemented frontend code around the actual API behavior, job states, and search
responses exposed by the backend.

The prompt emphasized:

- staying consistent with backend behavior rather than inventing a disconnected UI
- keeping the component structure small and understandable
- supporting crawl submission, status visibility, and scoped UI search

### Outputs

- `agents/frontend_implementation_plan.md`
- frontend code under `frontend/`

### Interactions

The Frontend Agent depended on the backend contract produced earlier. Its outputs
were later checked by the Reviewer Agent for consistency and by the Test Agent for
verification coverage.

### Key Decisions

- organize the frontend around crawl and search views
- use polling for job state visibility
- support search across all jobs or within a selected job
- reflect backend lifecycle states in the UI instead of creating a separate frontend-only model

---

## 5. Reviewer Agent

### Role

The Reviewer Agent acted as a validation and consistency layer across the project.
It was not used as a redesign agent.

### Inputs

- repository state after backend and frontend implementation
- generated documents including PRD, architecture, implementation plans, and README drafts

### Prompt / Instructions

The Reviewer Agent was instructed to inspect both the repository and the generated
documents, check consistency between implementation and documentation, identify
issues, and apply or suggest only minimal fixes. Its purpose was to reduce drift
between planned behavior and actual behavior without reopening major design choices.

### Outputs

- review notes
- consistency corrections
- small documentation or implementation fixes where necessary

### Interactions

The Reviewer Agent looked both backward and forward in the workflow. It validated
artifacts already produced, then helped stabilize the inputs used by the Test Agent
and README Agent.

### Key Decisions

- preserve the architecture and implementation direction rather than redesigning it
- prefer narrow corrections over broad rewrites
- check terminology, API behavior, field naming, state naming, and document/code alignment

---

## 6. Test Agent

### Role

The Test Agent defined and implemented the project verification layer.

### Inputs

- `crawler_architecture.md`
- backend and frontend implementation outputs
- reviewed repository state

### Prompt / Instructions

The Test Agent was instructed to work in two phases. First, it produced a test
implementation plan describing the intended test surface and verification strategy.
Then it implemented tests based on the final codebase and the planned system
behavior.

The prompt emphasized:

- verifying actual implemented behavior
- covering both unit and integration concerns
- checking crawl lifecycle, search behavior, API behavior, and key frontend flows

### Outputs

- `agents/test_implementation_plan.md`
- test code under `crawler/tests/`

### Interactions

The Test Agent used the architecture, implementation outputs, and reviewed codebase
as input. Its work helped validate that the system behavior documented in earlier
stages was actually reflected in the code.

### Key Decisions

- split testing into backend unit checks, backend integration checks, API checks,
  and frontend smoke verification
- verify multi-job behavior, pause/resume, search behavior, and backpressure
- keep tests aligned with the final repository structure rather than an earlier draft design

---

## 7. README Agent

### Role

The README Agent prepared the final user-facing project documentation.

### Inputs

- repository structure and final codebase behavior
- PRD, architecture, implementation plans, review outcomes, and test planning outputs

### Prompt / Instructions

The README Agent was instructed to review both the repository and the generated
documents, then write the final README and recommendation material in a way that
matched the implemented system. The goal was to produce documentation that was
practical for running the project and consistent with the final state of the code.

### Outputs

- `README.md`
- `recommendation.md`

### Interactions

This agent sat at the end of the sequence and consolidated outputs from earlier
stages into the final presentation layer. It depended on the implementation,
review, and testing stages being sufficiently stable before documenting the system.

### Key Decisions

- explain both quick-start usage and system behavior
- document CLI, API, persistence, and search modes consistently
- separate local project documentation from production-oriented recommendations

---

## Workflow Integration

The important characteristic of this process was continuity between stages. The PRD
did not end as an isolated document; it was used as input to architecture work. The
architecture was then used to guide backend and frontend planning. The implemented
repository and generated documents were reviewed for consistency before test
planning and test implementation were finalized. Finally, the README stage
consolidated the validated system into end-user documentation.

In practice, this meant each stage both consumed prior decisions and constrained the
next stage. The workflow therefore behaved more like an engineering pipeline than a
collection of independent prompts.

Human review remained part of that pipeline. Intermediate documents, implementation
outputs, and corrections were checked between stages so that later agents worked
from approved artifacts rather than from an unattended automatic chain.

---

## Conclusion

This multi-agent workflow was useful because it separated concerns without fully
separating context. Product definition, architecture, implementation, review,
testing, and documentation were handled in distinct passes, but each pass reused
the outputs of earlier work. That made it easier to keep the project coherent,
improve consistency between documents and code, and make incremental decisions
without relying on a single all-purpose generation step.
