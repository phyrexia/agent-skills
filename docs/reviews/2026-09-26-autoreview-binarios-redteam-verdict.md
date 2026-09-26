---
base_sha: dccd3f86950eb90a9311f5701a3ab84903058d3e
head_sha: 6ab4725fca0df7e3288e88081035fcdfe6bb29e4
verdict: approved
auditor: "Gemini vía agy (Antigravity), --mode plan --model gemini-3.1-pro-high, headless, todo el material inline"
scope: diff
kind: auditor
profile: feature
date: 2026-09-26
pr: 1
findings: {critical: 0, important: 0, minor: 0}
---

# Recibo de revisión — PR #1, autoreview excluye binarios de recursos

Vigente mientras sea el último commit del PR. El alcance es el diff completo contra `fork/main`: el cambio de binarios
(`6ab4725`) y los cuatro commits previos del Owner del 2026-08-17 (endurecimiento del escaneo de secretos) que se publican
en este PR.

## Evidencia

- Suite en qf-datos (`python:3.12-slim`, `--network none`): `Ran 407 tests — OK (skipped=4)`.
- Corrida real sobre olavanza `2cd4cda` con `--exclude-resource-binaries`: TruffleHog limpio, `services-loop.mp4`
  declarado no revisado, `patch is correct (0.72)`; el status `autoreview` del commit quedó en `success`.
- Decisión del Coordinador: la lista cerrada incluye `mp4`, `webm` y `mov`, porque el caso que motivó el cambio
  (pedido #8498 del bus) es un video de recurso.

## Rondas

1. **APROBADO**, sin hallazgos.

## Transcripción

**Auditoría de Seguridad y Calidad - PR #1 (agent-skills / autoreview)**

**1. CUMPLIMIENTO (Seguridad y Lógica de Exclusión)**
* **Falsificación de extensiones y binarios maliciosos:** La lógica es segura y "falla en modo cerrado" (*fail-closed*). La función `require_no_binary_diff` filtra basándose en lo que Git ya considera binario (`numstat` devolviendo `- -`). Si un atacante renombra un ejecutable a `.png`, este será excluido de la revisión del LLM, **pero** TruffleHog lo escaneará de todos modos buscando secretos, y el sistema forzará a que aparezca en el veredicto como `no revisado (recurso binario)`, delegando la responsabilidad visual al humano. Un archivo de texto con extensión `.png` no será marcado como binario por Git y pasará por la revisión del LLM. Los enlaces simbólicos se consideran texto.
* **Archivos borrados, renombrados o cambios de modo:** Al usar `--no-renames`, los renombrados se tratan como un borrado y una adición. `raw_diff_blob_sizes` maneja correctamente las adiciones y borrados al saltar el `mode == "000000"`, evitando errores al intentar medir algo que ya no existe (o no existía), y validando ambos lados del árbol.
* **Supervivencia de la declaración:** La función `annotate_excluded_resource_binaries` inyecta la advertencia explícitamente al **inicio** del campo (`f"{resource_binary_declaration(excluded)}\n\n{report['overall_explanation']}"`) antes de pasar por `bounded_field`. Si el veredicto excede los 3000 caracteres, el truncamiento ocurrirá en la cola del mensaje, asegurando que la alerta de "no revisado" jamás se pierda.
* **Endurecimiento de escaneo de secretos (Commits previos):** Las expresiones regulares implementadas (ej. `computed_credential_secret_expression_risk`, manejo de scopes, templates y escapes Unicode/Hex en JS/TS) son extraordinariamente robustas, previniendo ofuscaciones complejas y concatenaciones engañosas para inyectar contraseñas o tokens.

**2. CALIDAD (Código y Pruebas)**
* **Cobertura de Tests:** La suite de pruebas introducida en `test_autoreview_hardening.py` es exhaustiva. Cubre específicamente el comportamiento por defecto (`off`), el rechazo de binarios fuera de la lista y sobre tamaño (`oversized.png`, `.exe`), la inclusión en la declaración, y crucialmente `test_excluded_resource_binaries_are_still_secret_scanned` garantiza que la exclusión visual del LLM no afecte al escaneo de TruffleHog.
* **Manejo de errores al medir:** Brillante. En `raw_diff_blob_sizes`, cualquier excepción (`OSError` en `os.stat`, salida no-cero en `cat-file`, o fallo de `int()`) resulta en un arreglo `measured` vacío. Esto hace que `size = sizes.get(path)` sea `None`, provocando que el archivo caiga instantáneamente en la lista `refused` (bloqueando el PR).
* **Coherencia Flag / Env:** Implementación de CLI estándar y robusta. Utiliza `store_true` para `--exclude-resource-binaries` y `store_false` para `--no-exclude-resource-binaries` con valor por defecto `None`, resolviéndose limpiamente al entorno (`AUTOREVIEW_EXCLUDE_RESOURCE_BINARIES`) solo si el usuario no pasó el flag explícito.

VEREDICTO FINAL: APROBADO
