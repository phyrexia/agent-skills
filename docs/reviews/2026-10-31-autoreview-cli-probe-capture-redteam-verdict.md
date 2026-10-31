---
base_sha: ad6d89faf0e2c4106669854cce4f1f3c3cb3f445
head_sha: 094887e7602b5f2eb44ef6d8edac2af8e5ae44a2
verdict: approved
auditor: "DeepSeek V4.1 Flash por DeepInfra (deepseek-ai/DeepSeek-V4.1-Flash-1017), API directa, sin reasoning_effort, sin herramientas, todo el material inline; respuesta chatcmpl-RYda6ZaTfBQ1AMc2kgTn8XeR"
scope: diff
kind: auditor
profile: feature
date: 2026-10-31
pr: 2
findings: {critical: 0, important: 0, minor: 6}
---

# Recibo de revisión — PR #2, sondas de CLI de autoreview capturadas en archivos

Auditor sustituto autorizado por el Owner el 31-10: DeepSeek V4.1 Flash (DeepInfra) en lugar de Gemini sin cuota.

Vigente mientras sea el último commit del PR. Alcance: el diff completo contra la rama base `fix/autoreview-binarios-y-motores`
(cabeza del PR #1, `ad6d89f`): `5bb39ee` (sondas `--help`/`--version` capturadas en archivos temporales) y `094887e` (los errores
largos conservan el final).

## Evidencia

- Worker remoto `qaw-p3-03`, run `094887e7602b-1793468990-a2af8b`, head `094887e`: suite equivalente a `validate.yml`
  con 410 tests OK (4 skipped), los 7 `--self-test-*` y las 3 regresiones nuevas.
- Rojo en el mismo run: sin `capture_dir`, las regresiones de sonda fallan con
  `pi engine requires Pi isolation flags missing from --help: --print, ... (--help exit 0, 512 chars captured)`.
- GitHub Actions `validate` en ubuntu-latest y windows-latest: success.
- CLIs reales en el Mac (claude 2.1.316, pi 1.4.0): los preflights del head pasan 15 de 15 veces.

## Rondas

1. **APROBADO**: 0 Critical, 0 Important, 6 Minor. Ninguno exige cambios antes del merge.

## Respuesta a las preguntas abiertas del Auditor

1. amp, kimi y cursor no están instalados en esta máquina, así que no se comparó su `--help` a archivo contra pipe. Para esos motores
   el cambio solo afecta el destino de la captura. La regla sigue igual: si falta una flag, el motor falla cerrado.
2. `safe_temp_root(repo)` es la misma raíz temporal donde autoreview ya crea sus espacios de trabajo y el escáner. Si no se pudiera
   escribir, la corrida fallaría antes de la sonda, también en modo cerrado.

Los Minor quedan anotados sin cambios: el mensaje ante un TMPDIR sin escritura, un tope para un `--help` enorme, la cola del error en
stderr, el origen stdout o stderr en el conteo y un comentario que no menciona kimi.

## Transcripción

**Spec-compliance**

El cambio ataca exactamente el diagnóstico declarado: la sonda de `--help`/`--version` deja de leer por pipe y pasa a leer desde un archivo regular (`tempfile.TemporaryFile`), lo que elimina el truncamiento a ~512 bytes de los CLIs Node/Bun en macOS. Verifico contra el diff:

- `run()` gana `capture_dir` opcional; sin él el comportamiento es idéntico (pipes). Correcto: no cambia la invocación real de la revisión, solo las sondas.
- `run_cli_probe()` se usa en claude, pi, amp, kimi y cursor. Las listas de flags exigidas, versiones mínimas y chequeo de `returncode != 0` **no cambian**. El preflight sigue exigiendo las mismas flags y sigue fallando cerrado si faltan o si `--help` falla.
- `missing_help_flags_detail` añade diagnóstico (exit code + chars capturados) sin relajar la condición de fallo.
- `bounded_exit_message` conserva cabeza y cola del mensaje; sigue pasando por `display_escape` y sigue acotado a 4000. No desactiva TruffleHog ni ningún control.
- Tests: las dos regresiones nuevas reproducen el truncamiento por pipe (fixture que corta a 512 si `S_ISFIFO`) y verifican que con la flag eliminada el preflight **sí** falla con el detalle nuevo. Eso es evidencia directa de que no hay falso positivo por el cambio de captura.

No veo en el diff ninguna relajación de la condición de aislamiento. La afirmación «nunca debilitar el aislamiento» se sostiene en lo que el diff muestra.

Perfil verificado: feature

**Code-quality / riesgo**

Critical: ninguno.

Important: ninguno que pueda confirmar con el material. Reviso los ejes explícitos:

- *¿Puede pasar el preflight con un CLI que no soporta una flag?* No por este cambio: la comprobación sigue siendo `flag not in help_text` sobre el texto completo, y ahora el texto es más completo (archivo regular), no menos. El único riesgo teórico sería que un CLI escriba distinto a archivo que a pipe (p.ej. detección de TTY/pipe que cambie el contenido de `--help`). No tengo evidencia de que claude/pi/amp/kimi/cursor hagan eso; lo dejo como **pregunta**, no como hallazgo: ¿se verificó que `--help` a archivo regular produce el mismo conjunto de flags que a pipe en los cinco CLIs, más allá de claude y pi?
- *Invocación real de la revisión:* no cambia (solo `run_cli_probe` usa `capture_dir`). Si el CLI rechaza una flag en la corrida real, el `run(..., check=True)` sigue lanzando `SystemExit` con el stderr — comportamiento previo intacto.
- *Disco lleno / TMPDIR no escribible:* `TemporaryFile` lanzaría `OSError` no capturado → el proceso muere con traceback en vez de un mensaje de preflight claro. Es un modo de falla **fail-closed** (no aprueba), pero el mensaje no es el «mensaje claro» que pide la spec. **Minor**: considerar envolver la creación del `TemporaryFile` en un `SystemExit` con contexto («no se pudo crear archivo de captura para la sonda de <engine>»).
- *`--help` enorme:* se lee entero a memoria; acotado por el tamaño real del help (decenas de KB). Aceptable. **Minor** si se quiere un tope defensivo, pero no es un riesgo real hoy.
- *`bounded_exit_message` y secretos:* antes se mostraban los primeros 4000 chars del mismo texto; ahora se muestran 1000 de cabeza + cola. La cola puede contener texto que antes quedaba fuera de los 4000 (p.ej. un token en el stderr del motor). Es una **ampliación marginal de superficie de exposición** del mismo canal (stderr del proceso, ya escapado). No es un secreto del repo revisado sino salida del CLI; riesgo bajo. **Minor**: documentar que la cola puede incluir output del motor y que el escape ya está aplicado (lo está).
- *Windows:* `TemporaryFile` como `stdout` de `subprocess` funciona en Windows (handle de archivo real, no pipe). CI `windows-latest` en verde lo respalda. Sin hallazgo.
- *Concurrencia:* cada sonda crea sus propios `TemporaryFile` sin nombre fijo; sin colisión. Sin hallazgo.
- *`capture_dir=cwd` en `run_cli_probe`:* el `cwd` es `safe_temp_root(repo)` o el tempdir privado de la sonda, fuera del repo revisado. Correcto. **Minor/pregunta**: en `ensure_claude_isolation_supported` el `capture_dir` es `temp_root` (compartido entre sondas de la misma corrida); como los `TemporaryFile` son anónimos, no hay colisión, pero conviene confirmar que `safe_temp_root` es escribible por el usuario en todos los perfiles (si no, cae en el caso «disco/TMPDIR» de arriba).

Minor adicionales:
- `missing_help_flags_detail` reporta `len(stdout)+len(stderr)`; si el CLI escribe el help a stderr, el conteo es correcto pero el mensaje no distingue de dónde vino. Cosmético.
- El comentario de `run_cli_probe` menciona «amp, cursor» pero no kimi; irrelevante funcionalmente.

**Preguntas abiertas (no verificables con el material):**
1. ¿Se comprobó que `--help` a archivo regular en amp, kimi y cursor devuelve el mismo contenido que a pipe (no solo claude y pi)?
2. ¿`safe_temp_root(repo)` es siempre escribible en los entornos donde corre el hook (incluido el worker remoto y Windows)?

Ninguno de los puntos anteriores es Critical ni Important confirmado; los Important potenciales dependen de las respuestas a las preguntas y no hay evidencia en el diff de que fallen.

VEREDICTO FINAL: APROBADO