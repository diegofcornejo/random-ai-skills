<!-- Example plan built from synthetic data (fictional org acme-telco), written in Spanish to show the language rule: the plan follows the language the developer speaks. Alert numbers, severities, priorities, coverage and the Dependabot PR come from that data; installed versions and code details are illustrative. The Angular major-upgrade appendix at the end is hypothetical. -->
# Plan de remediación de seguridad — acme-telco/portal-web

**Fecha:** 2026-11-10 · **Host:** github.com · **Visibilidad:** privado · **Rama por defecto:** main
**Stack:** Angular 11.0.0 · npm · PHP ninguno
**Cobertura:** Dependabot ok · code scanning ok · secret scanning ok
**Generado por:** github-security-remediation (cifras de la API de GitHub vía `analyze_repo.py`)

## Resumen

| Fuente | Abiertas | Críticas | Altas | Medias | Bajas |
|--------|----------|----------|-------|--------|-------|
| Dependabot | 3 | 1 | 1 | 1 | 0 |
| Code scanning | 1 | 0 | 1 | 0 | 0 |
| Secret scanning | 0 | 0 | 0 | 0 | 0 |
| **Total** | 4 | | | | |

Por prioridad: P1 2 · P2 1 · P3 1. Ya cerradas en GitHub: 1.

## Bloques

| # | Bloque | Cierra | Prioridad | Riesgo del fix | Esfuerzo | Quién actúa |
|---|--------|--------|-----------|----------------|----------|-------------|
| 1 | Incorporar el PR #7 de Dependabot (lodash 4.17.21) | 1 alerta | P1 | bajo | S | Agente |
| 2 | Parche del framework Angular 11.0.0 → 11.0.5 | 1 alerta | P1 | bajo | S | Agente |
| 3 | Corregir el XSS del lado del cliente en `src/app/render.ts` | 1 alerta | P2 | bajo | S | El agente prepara, el desarrollador aprueba |
| 4 | karma 5.1 → 6.3.16 (actualización mayor del ejecutor de tests) | 1 alerta | P3 | alto | M | Agente, desarrollador |
| 5 | Candidata a descarte: karma (alternativa al bloque 4) | 1 alerta | P3 | bajo | S | El desarrollador confirma, el agente lo ejecuta |

### Bloque 1 — Incorporar el PR #7 de Dependabot (lodash 4.17.21)

- **Objetivo:** lodash resuelve a 4.17.21 en la rama de trabajo, con el mismo cambio que propuso Dependabot en el PR #7.
- **Cierra:** [dependabot#2](https://github.com/acme-telco/portal-web/security/dependabot/2), GHSA-35jh-r3h4-6jhm, CVE-2021-23337
- **Prioridad:** P1 (puntuación máxima 75)
- **Pasos:**
  1. Volver a comprobar el PR: `gh pr view 7 --json state,mergeable,statusCheckRollup,headRefName`.
  2. `git fetch origin dependabot/npm_and_yarn/lodash-4.17.21`
  3. `git log --oneline "$(git merge-base HEAD FETCH_HEAD)"..FETCH_HEAD` (solo debe aparecer el commit de Dependabot).
  4. `git cherry-pick --no-commit <sha>` y un único commit para el bloque, con la nota "supersedes Dependabot PR #7". El PR nunca se fusiona con `gh pr merge`. GitHub lo cierra como reemplazado cuando integres la rama.
- **Riesgo del fix:** bajo
  - salto de parche 4.17.20 → 4.17.21
  - dependencia transitiva, cambio solo en el lockfile (`package-lock.json`)
  - el PR #7 de Dependabot está sano: MERGEABLE, checks SUCCESS
- **Esfuerzo:** S (menos de una hora)
- **Verificación:** `npm ci && npm test -- --watch=false && npm run build`
- **Quién actúa:** agente (mecánico)
- **Depende de:** —

### Bloque 2 — Parche del framework Angular 11.0.0 → 11.0.5

- **Objetivo:** todos los paquetes `@angular/*` del framework quedan en 11.0.5, la primera versión corregida.
- **Cierra:** [dependabot#1](https://github.com/acme-telco/portal-web/security/dependabot/1), GHSA-c75v-2vq8-873c, CVE-2021-4231
- **Prioridad:** P1 (puntuación máxima 70)
- **Pasos:**
  1. `npx --no-install ng update @angular/core@11.0.5 @angular/cli@11.0.5` (los paquetes del framework se mueven juntos; se pregunta antes de ejecutarlo, porque instala paquetes).
  2. `git diff --stat` (solo deben cambiar `package.json` y `package-lock.json`).
- **Riesgo del fix:** bajo
  - parche dentro de la misma versión mayor (11.0.0 → 11.0.5)
  - dependencia directa; `@angular/common`, `@angular/compiler`, `@angular/forms`, `@angular/router` y el resto de paquetes del framework se mueven con `@angular/core`, nunca `@angular/core` solo
  - solo cambian los manifiestos y el lockfile
  - hay suite de Karma (`npm test`); la línea base se registra antes del bloque 1
- **Esfuerzo:** S (menos de una hora)
- **Verificación:** `npm ci && npx --no-install ng build && npx --no-install ng test --watch=false --browsers=ChromeHeadless`
- **Quién actúa:** agente (mecánico)
- **Depende de:** —

### Bloque 3 — Corregir el XSS del lado del cliente en `src/app/render.ts`

- **Objetivo:** el valor que se escribe en `src/app/render.ts:42` pasa por la sanitización de Angular, y CodeQL deja de reportar `js/xss` ahí.
- **Cierra:** [code-scanning#1](https://github.com/acme-telco/portal-web/security/code-scanning/1) (`js/xss`, Client-side cross-site scripting)
- **Prioridad:** P2 (puntuación máxima 40)
- **Pasos:**
  1. Leer `src/app/render.ts` alrededor de la línea 42 y rastrear de dónde viene el valor que se renderiza.
  2. Proponer el cambio como diff (por ejemplo, enlazarlo con la sanitización de plantillas de Angular, o `DomSanitizer.sanitize(SecurityContext.HTML, …)`, en lugar de escribir HTML crudo). Solo se aplica después de que lo apruebes.
  3. Añadir o ampliar un test unitario que fije la salida escapada.
- **Riesgo del fix:** bajo
  - cambio local en una función de un archivo de la aplicación
  - el comportamiento se mantiene para entradas seguras; un test unitario puede fijarlo
  - Copilot Autofix no está disponible para esta alerta, así que el fix se escribe a mano
- **Esfuerzo:** S (menos de una hora)
- **Verificación:** `npx --no-install ng test --watch=false --browsers=ChromeHeadless && npx --no-install ng build`. CodeQL cierra la alerta tras el siguiente análisis de `main`.
- **Quién actúa:** agente (prepara el cambio y lo aplica una vez aprobado), desarrollador (lo aprueba)
- **Depende de:** —

### Bloque 4 — karma 5.1 → 6.3.16 (actualización mayor del ejecutor de tests)

- **Objetivo:** karma queda en 6.3.16, la primera versión corregida, y la suite de tests sigue ejecutándose.
- **Cierra:** [dependabot#3](https://github.com/acme-telco/portal-web/security/dependabot/3) (karma), GHSA-7x7c-qm48-pq9c, CVE-2022-0437
- **Prioridad:** P3 (puntuación máxima 25)
- **Pasos:**
  1. `npm ls karma` y luego leer `peerDependencies.karma` en `node_modules/@angular-devkit/build-angular/package.json` para confirmar que el builder de Angular instalado acepta karma 6. Si no lo acepta, se detiene y te lo dice: la alerta pasa a "No se corregirá ahora", o eliges el bloque 5.
  2. `npm install --save-dev karma@6.3.16` (se pregunta antes de ejecutarlo, porque instala paquetes).
  3. Alinear los plugins de karma (`karma-jasmine`, `karma-chrome-launcher`, `karma-coverage`) solo si sus rangos de peer lo exigen. Cambiar `karma.conf.js` solo si karma 6 lo rechaza, y mostrarte esa edición antes.
- **Riesgo del fix:** alto
  - salto mayor del propio karma, 5.1 → 6.3.16
  - dependencia directa de `development`: no cambia nada del build de producción
  - `karma.conf.js` puede necesitar cambios (un archivo de configuración)
  - la actualización cambia el propio ejecutor de tests, así que un fallo se ve como una suite que no arranca; la línea base se registra antes del bloque 1
- **Esfuerzo:** M (hasta media jornada)
- **Verificación:** `npm ci && npx --no-install ng test --watch=false --browsers=ChromeHeadless && npx --no-install ng build`
- **Quién actúa:** agente (actualización mecánica), desarrollador (aprueba cualquier edición de `karma.conf.js`)
- **Depende de:** —

### Bloque 5 — Candidata a descarte: karma (alternativa al bloque 4)

- **Objetivo:** si no apruebas el bloque 4 ahora, dependabot#3 sale de la cola con una justificación registrada en lugar de quedar abierta sin responsable.
- **Cierra:** [dependabot#3](https://github.com/acme-telco/portal-web/security/dependabot/3) (karma), GHSA-7x7c-qm48-pq9c
- **Prioridad:** P3 (puntuación máxima 25)
- **Pasos:**
  1. Confirmar la evidencia: `karma` es una dependencia de `development` que solo usa `ng test`, y no forma parte del build de producción.
  2. Motivo propuesto: `tolerable_risk`. Comentario borrador (135 caracteres): `Ejecutor de tests solo de desarrollo (karma), nunca llega a producción ni recibe entradas no confiables. Decidido por jdoe, 2026-11-10.`
  3. Después de que confirmes esta alerta concreta: `dismiss.py … --dry-run`, y luego la misma llamada sin `--dry-run`.
- **Riesgo del fix:** bajo
  - no cambia nada en el repo
  - el advisory sigue sin parchear en las herramientas de test locales hasta que se actualice karma (bloque 4)
- **Esfuerzo:** S (menos de una hora)
- **Verificación:** la alerta aparece como descartada en GitHub con tu usuario, el motivo y el comentario; el reporte diario la lista en su auditoría de descartes.
- **Quién actúa:** desarrollador (confirma el descarte), agente (ejecuta `dismiss.py`)
- **Depende de:** — (aprueba el bloque 4 o el bloque 5, no ambos)

## No se corregirá ahora

Nada. Cada alerta abierta está en un bloque de arriba; dependabot#3 lo cubre el bloque 4 o, como alternativa, el bloque 5.

## Cómo seguir

¿Qué bloques apruebas? Puedes decir "todos", "1 y 3", "cancelar", o pedir ajustes. Los bloques 4 y 5 son alternativos: elige uno de los dos.

---

## Ilustrativo: cómo se ve un bloque de actualización mayor de Angular (no deriva de las alertas de este repo)

La alerta de Angular abierta en este repo se corrige con un parche dentro de la versión mayor 11 (bloque 2), así que este plan no tiene un salto mayor de Angular. El bloque de abajo no forma parte del plan. Solo muestra el formato que usa el skill cuando la primera versión corregida de una alerta está en la siguiente versión mayor de Angular. La alerta, las versiones y los factores son hipotéticos. Cada salto mayor (11 → 12, 12 → 13, …) es su propio bloque y nunca se mezcla con actualizaciones rutinarias.

### Bloque N — Angular 11 → 12

- **Objetivo:** la aplicación compila y sus tests pasan en Angular 12, lo que cierra la alerta de `@angular/*` corregida en 12.x.
- **Cierra:** una alerta hipotética de `@angular/*` cuya primera versión corregida es 12.x (en un plan real: el enlace de la alerta y sus ids GHSA/CVE)
- **Prioridad:** copiada de los scripts para esa alerta (en un plan real: la banda y la puntuación máxima)
- **Pasos:**
  1. `git status --porcelain` (debe estar vacío) y luego `npx --no-install ng update` para ver qué se puede mover (no cambia nada).
  2. `npx --no-install ng update @angular/core@12 @angular/cli@12` (se pregunta antes de ejecutarlo; corre las migraciones 11 → 12).
  3. `npx --no-install ng update @angular/material@12 @angular/cdk@12` (si se usa Angular Material).
  4. Actualizar cada librería de Angular de terceros a su versión para Angular 12.
  5. Compilar y probar. Cada corrección de compilación en el código de la aplicación se te muestra como diff y necesita tu aprobación.
- **Riesgo del fix:** alto (siempre, en un salto mayor de Angular)
  - salto mayor 11 → 12, un solo salto (un fix en 13.x necesitaría un segundo bloque, 12 → 13)
  - TypeScript 4.0 → 4.2: `typescript` debe estar en el rango que soporta Angular 12 (`https://angular.dev/reference/versions`)
  - `@angular/material` y `@angular/cdk` pasan a 12 junto con `@angular/core` (misma versión mayor)
  - Node.js: `engines.node`, `.nvmrc` y la imagen de CI deben estar en el rango que soporta Angular 12; un cambio de imagen de CI ocurre fuera del repo
  - librerías de Angular de terceros (`ngx-*`, `@ngrx/*`, …): cada una necesita una versión para Angular 12, y una librería sin ella bloquea el salto
  - los cambios incompatibles de la guía de actualización 11.0 → 12.0 que aplican a este repo, cada uno con su evidencia (por ejemplo, `ng build` usa por defecto la configuración de producción desde la 12)
  - número de archivos de la aplicación a cambiar, y los tests disponibles para detectar regresiones
- **Esfuerzo:** L (un día o más); M para una aplicación pequeña con pocas librerías de terceros
- **Verificación:** `npm ci && npx --no-install ng build && npx --no-install ng test --watch=false --browsers=ChromeHeadless`
- **Quién actúa:** agente (ejecuta `ng update` tras la aprobación), desarrollador (aprueba cada edición de código), persona fuera del repo (si hay que cambiar el Node.js de la imagen de CI)
- **Depende de:** los bloques que deban ir antes, si los hay
