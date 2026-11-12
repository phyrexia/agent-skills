---
base_sha: 09e2a5d
head_sha: 5e2461a
verdict: approved
auditor: "DeepSeek V4 Pro (deepseek-v4-pro-0813) por el Token Plan de Alibaba vía omp, sin herramientas, material inline, razonamiento apagado"
auditor_substitute_reason: "agy (Gemini 3.8 Flash) con la cuota semanal en 0 % hasta el 14-11; MiMo con 429; DeepInfra con 402. Respaldo por defecto del Owner (DeepSeek V4 Pro, 2026-10-31); los implementadores fueron Claude Haiku 5.5 y Codex gpt-6.1-sol, otras familias"
scope: diff
kind: auditor
profile: feature
date: 2026-11-12
findings: {critical: 0, important: 0, minor: 5}
---

# Recibo de revisión: autoreview guarda las sesiones de sus motores

Directiva del Owner (2026-11-12): todo arnés guarda su sesión para que claude-usage la mida. En noviembre, 374 revisiones con DeepSeek V4 Pro vía `pi --no-session` costaron ~US$111 en DeepInfra sin dejar transcript.

Qué cambia:
- **Marcas sin persistencia:** se quitan `--no-session` (pi), `--no-session-persistence` (claude) y `--ephemeral` (codex).
- **Codex:** corre con un `CODEX_HOME` temporal que se borra con la corrida. Al terminar se copian solo los `rollout-*.jsonl` al `CODEX_HOME` de origen o a `~/.codex/sessions`, con la misma ruta relativa. La copia no sigue symlinks, no sobrescribe, es atómica (temporal + enlace exclusivo) y deja modo 0600. Una falla solo genera un aviso y no cambia el veredicto.
- **Claude y Pi:** ya usan el home real del usuario, así que guardan su sesión de forma nativa.
- **Amp y Kimi:** siguen con almacén temporal; queda documentado como limitación.

| Ronda | HEAD | Veredicto |
|---|---|---|
| 1 | `5e2461a` | APROBADO en spec y calidad, con 0 Critical y 0 Important. El auditor descartó con análisis tres candidatos a Important: rutas no absolutas, orden del `ExitStack` respecto de `TemporaryDirectory` y descriptores en `fwalk`. Los 5 Minor se aceptaron: asunción documentable de ruta absoluta, imports (verificados: `stat`, `secrets`, `contextlib` y `shutil` están importados), constantes repetidas, un comentario sobre el ancla `/` y el alcance de una aserción de prueba |

## Evidencia

Las pruebas del skill (`skills/autoreview/tests`) se corrieron en qf-test, en qaw-p3-01 sobre `5e2461a`: 363 passed, 4 skipped y 0 failed.

## Qué este recibo NO garantiza

Garantiza integridad, no autenticidad. Falta verificar una revisión real después de instalar el cambio: el rollout debe aparecer en `~/.codex/sessions` y la sesión de pi en `~/.pi/agent/sessions`.
