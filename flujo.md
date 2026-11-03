Ya tengo el panorama completo. Te respondo en dos partes: primero el flujo completo con todas sus variantes, y después el plan de limpieza que necesito que apruebes (borrar es destructivo, así que no toco nada sin tu confirmación).
1. El flujo del harness, de punta a punta
1.1 Flujo principal (una tarea ejecutada)
REQUEST → TASK → ROUTE → RISK → CONTEXT → IMPLEMENT → CHECKS → REVIEW → VERIFY → CLOSE
 1. REQUEST: me das una solicitud. Se preserva el original; si no está en inglés, se genera una versión canónica en inglés con attestación EXACT_INTENT (testeada con scripts/request_normalizer.py) antes de delegar. Nada se traduce "a ciegas".
 2. TASK: la solicitud debe existir como JSON durable en tasks/ con criterios de aceptación, risk_factors y procedencia. Si la idea es amplia/vaga/multi-feature → primero discovery de producto (ver 1.3). Si es un cambio acotado → intake normal de tarea.
 3. ROUTE (task_router.py): clasifica tipo, riesgo, capacidades, agentes y skills de forma determinista. Genera route.json.
 4. RISK: el router asigna el nivel (ver 1.4). Los gates de riesgo son autoritativos: no se debilitan para "hacer pasar" una tarea.
 5. CONTEXT (context_compiler.py): se compila un paquete mínimo de contexto. Tareas pequeñas → archivos directos; tareas amplias/incierto/R2+ → CodeGraph si hay índice, o el grafo léxico + repo map como fallback. Los agentes corrigen detalles con las herramientas ACI (búsqueda acotada, lecturas por rango).
 6. IMPLEMENT: se crea un worktree Git aislado con writer lock; se activa la tarea para el proveedor (opencode_activate_task.py / codex_activate_task.py, que regenera los adaptadores desde .agents/roles/). El implementer es el único escritor de código de aplicación por unidad de trabajo. Nadie más edita el candidato.
 7. CHECKS (task_checks.py): checks deterministas (tests, lint, schema, diff) desde el worktree. Si fallan → iterar. No se registra PASS si sale non-zero.
 8. REVIEW: un reviewer independiente del escritor (idealmente otro modelo/familia/vendor) intenta falsificar el candidato y devuelve un handoff JSON tipado (schema en harness/schema/handoffs/). Prosa libre no cuenta.
 9. VERIFY: un verifier independiente confirma criterio por criterio desde el límite observable (no leyendo el código, sino el comportamiento). R2/R3 lo exigen; a veces el test-auditor revisa los tests.
10. CLOSE (orchestrator.py + worktree.py publish): publish es el único mecanismo de entrega — crea el commit de la tarea, fast-forward a la rama canónica, escribe publish.json y elimina el worktree. The finish gate es la autoridad final: no hay DONE sin allow: true. Todo queda como evidencia durable en .harness/runs/<task>/ (ledger con hash-chain).
1.2 Cuándo se aplican SDD, RDD-SDD y Receipt-RDD (¡son dos RDD distintos!)
RDD (Research-Driven Discovery) — antes de la tarea, pre-implementación
Se consulta harness/research-policy.json. Se activa cuando la incertidumbre es alta o la decisión es cara de revertir: API mutable, migración, producto nuevo, arquitectura irreversible. Se resuelve con python scripts/research_discovery.py assess <disco>. Solo si el modo resuelto es research o full se usan los skills research-driven-discovery y domain-modeling:
1. Research: fuentes primarias (fuente, afirmación, incertidumbre, qué decisión cambia).
2. Discovery: resultado deseado, interesados, supuestos, tensiones, preguntas bloqueantes.
3. Domain modeling (solo full): vocabulario, relaciones, invariantes.
4. Decision / Architecture / Scenarios → artefactos en planning/.
Regla dura: los artefactos de investigación nunca autorizan implementar. Hay que pasar discovery de producto + aprobación humana antes de materializar tareas.
SDD (Spec-Driven Development) — dentro de cada tarea, antes de escribir código
No es un script; es el contrato de la unidad de trabajo en el JSON de la tarea: objetivo y alcance excluido, criterios de aceptación observables, superficie de archivos probable, riesgo/rollback, escenarios feliz/negativo/límite/fallo parcial, y decisiones que requieren humano. El implementador no puede redefinir el contrato para acomodar su parche: la tarea es la fuente de verdad de TDD.
TDD adaptativo — el router decide el modo en route.json.tdd
Modo	Secuencia
tdd_required	RED (prueba que falla por la razón conductual correcta, no por import/setup) → GREEN (cambio mínimo) → REFACTOR
characterization_then_tdd	Primero capturar el comportamiento legado con tests que pasan, después RED→GREEN
spike_then_tdd	Primero resolver y registrar el contrato técnico/externo desconocido, recién después TDD
tdd_preferred	Test-first si el contrato es estable; excepciones documentadas
test_after_allowed / not_applicable	Validación normal, sin simular evidencia RED
El finish gate valida la evidencia TDD obligatoria; no se puede fabricar.
Receipt-RDD — después de implementar, capa de integridad de review (opt-in, clone-local)
Se marca con python scripts/receipt_review.py mode status. Cuando está ON, en VERIFY_ASSESS (post-CHECKS) se hace receipt_review.py prepare <TASK> --apply, que congela el candidato: el review se ata por recibo al byte exacto del sujeto. Si cambia un byte después del freeze, el recibo se invalida y hay re-review. Si la ruta exige REVIEW_CONSENT, se te pregunta una vez por sesión de proveedor y vos otorgás el consentimiento (nunca se otorga en tu nombre).
1.3 Discovery de producto (cuando la idea no es una tarea)
Idea vaga / producto nuevo / multi-feature
  → idea-to-work (research-RDD si requiere investigación)
  → preguntas de producto (máx 3 por turno, máx 2 rondas, solo vacíos materiales)
  → dossier en planning/discovery/ → validate → status "approved"
  → materialize → épica/feature/spike/task en tasks/ con procedencia
  → sprint-planning (lote acotado de ejecución)
  → recién ahí empezamos el flujo principal
Si solo pedís "explorar/mejorar la idea", paramos en el plan refinado sin implementar.
1.4 Niveles de riesgo y qué exige cada uno
Riesgo	Alcance típico	Exige para cerrar
R0 trivial	docs, formato, rename	check focalizado
R1 normal	feature/bugfix/refactor ordinario	tests pertinentes + checks + review independiente
R2 alto riesgo	datos externos, persistencia/esquema, concurrencia, cálculos, integraciones	+ plan explícito, verificación independiente, revisión especialista si aplica
R3 crítico	secretos, auth, destructivo, producción irreversible	+ security-review adversarial, aprobación humana explícita, gates extra (para editores OpenCode: attestación de procedencia firmada)
Gates humanos: siempre paramos antes de producción irreversible, credenciales reales, debilitar seguridad, costo recurrente, arquitectura irreversible o borrado destructivo de datos. Los detalles de implementación reversibles se resuelven con evidencia del repo, sin molestarte.
1.5 Cuándo se invoca cada subagente
Agente	Fase	Rol
explorer	CONTEXT (opcional)	mapear repo/evidencia sin escribir
planner	PLAN (R2+/incierto)	plan acotado, criterios, rollback
test-designer	TEST_DESIGN (si route.tdd lo pide)	deriva independientemente oráculos, casos negativos/límite, antes de tocar producción
implementer	IMPLEMENT	único escritor de código, en su worktree
reviewer	REVIEW	intenta falsificar; independiente del escritor
test-auditor	REVIEW/VERIFY (riesgo alto o tests críticos)	audita si los testsdetectan fallos realistas
verifier	VERIFY (R2+, o cuando riesgo/verificación lo exige)	confirma aceptación observable por criterio
security-reviewer	R3	audita fronteras de confianza, secretos, auth
debugger	cuando algo falla repetidamente	aislar causa raíz sin editar
El presupuesto de agentes es progresivo (agent_budget.py): arranca con el equipo mínimo seguro (implementer + review/verify según riesgo) y solo escala con evidencia de riesgo/impacto/replanificación fallida. No se agregan agentes por ceremonial. Los gate obligatorios del riesgo siguen siendo obligatorios.
1.6 Ruteo de modelos
- Selección por agente, no uno por tarea. Acción inherit = usa el modelo de la sesión actual.
- Inventario scored local + intersección con los modelos disponibles en el host (OpenCode). Lo desconocido queda "desconocido": jamás se inventan benchmarks/precios/reliability.
- Refresh de OpenRouter: solo manual (openrouter_sync.py --provider all); las tareas nunca tocan la red ni mutan el inventario.
- Reviewer/verifier/auditor: preferir modelo distinto → familia distinta → vendor distinto del del implementador. Si no se logra, se registra la debilidad de independencia.
1.7 Variantes/rutas alternativas
- Check falla → diagnosticar → corregir en worktree → re-check (en bucle pequeño).
- Conflicto → comparar contratos/tests → resolver sin perder garantías → commits separados.
- Decisión humana pendiente → registrar bloqueo, esperar; nunca se asume.
- skills como guía de proceso: harness-task, task-intake, task-router, adaptive-tdd, implementation-loop, weighted-review, verification, task-close, etc.
2. Plan de limpieza del repo (tu pedido)
Mapeé todo. El inventario propuesto:
Mantener — el motor del harness (lo que te sirve para el proyecto nuevo)
- harness/, scripts/, .agents/ (roles y skills canónicos), tests/ (tests del propio harness), docs/ (incluye FLUJO_OPERATIVO.md)
- Adaptadores generados: .codex/, .claude/, .cursor/, .gemini/, .opencode/, .github/, opencode.json, .mcp.json, AGENTS.md, AI_POLICY.md, CLAUDE.md, GEMINI.md, README.md
- benchmarks/, evals/, specs/, sprints/, harness-chat, harness.cmd, codegraph.md, .gitattributes
- Carpetas esqueleto: tasks/README.md, specs/README.md, sprints/README.md y los README.md de planning/
Eliminar — historia del proyecto/harness anterior (artefactos de ejecución ya consumidos)
- tasks/*.json — 9 tareas cerradas (CODEGRAPH-, HARNESS-INSTALL-, DESKTOP-ACI-, SHARED-RUNTIME-)
- planning/**/{epics,features,discovery,research,decisions,domain,scenario,sprints}/*.json — dossiers y sprints del install anterior (~15 JSON, conservando los READMEs)
- Estado runtime local selección si querés un reset total de memoria de ejecución: .harness/overlays/ (esto no está committeado; es estado local)
Hay una decisión humana aquí (gate: borrado irreversibles), y además asumo un dato: