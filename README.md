# Enterprise AI Copilot

A multi-tenant, source-grounded AI assistant for enterprises.

Employees upload approved internal documents (policies, contracts, manuals,
technical documentation) and ask questions in natural language. The assistant
answers using only the tenant's authorized documents, always with verifiable
citations to the source sections — and explicitly abstains when the retrieved
evidence is insufficient.

## Example

**Q:** "What is our refund policy for enterprise customers?"

**A:** An answer grounded in the tenant's authorized documents, with references
such as `Refund Policy — Section 4.2` and links to the cited sections. When the
retrieved evidence is insufficient, the assistant says so instead of guessing.

**Controlled actions:** a user may request, for example, "create a support
ticket". The application validates permissions and requires explicit
confirmation before executing any state-changing tool call.

> **Status:** in active development. The architecture below is the target
> design, not the deployed reality. Storage, compute and RAG backend choices
> are finalized after comparing cost, complexity and requirements.

## Target architecture (AWS)

| Layer | Technology (proposed) |
|---|---|
| Frontend | React / Next.js — chat, documents, sources, admin |
| Auth & entry | Amazon Cognito + API Gateway |
| Backend | Python + FastAPI — orchestration, authorization, tools |
| LLM | Amazon Bedrock |
| RAG | Retrieval with citations (Bedrock Knowledge Bases candidate; compare vs. custom RAG) |
| Storage | Amazon S3 |
| Observability | CloudWatch — logs, metrics, cost per operation |
| IaC / CI-CD | Terraform or CDK (to be decided) |

## Differentiators

- **Multi-tenant security** — two companies can use the platform without
  accessing each other's documents. Isolation is enforced by the backend and
  the retrieval layer — never by instructing the LLM — and verified with
  automated isolation tests.
- **Verifiable answers** — every answer shows the document and section it came
  from; the system abstains when evidence is insufficient.
- **Controlled actions** — permission-checked, human-confirmed tool execution.
- **Automatic evaluation** — a curated question set with expected answers
  measures retrieval quality, answer fidelity to sources, and regressions
  after every change.
- **Observability & cost control** — latency, errors, token usage and cost per
  operation, with usage limits (AWS Well-Architected Agentic AI Lens).

## Development

*(To be added with the first milestone: setup, environment variables, run and
test instructions.)*
