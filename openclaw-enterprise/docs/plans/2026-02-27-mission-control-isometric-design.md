# Mission Control — Isometric Office Redesign
**Date:** 2026-02-27
**Status:** Approved
**Scope:** `control-plane/mission-control-ui/`

---

## Objetivo

Reemplazar el canvas 2D plano actual por una oficina isométrica animada con Phaser 3, donde cada agente del runtime aparece como un personaje pixel art que se mueve, trabaja y reacciona en tiempo real al estado del API.

## Stack

- **Motor:** Phaser 3 (CDN, sin bundler)
- **Assets:** Kenney.nl packs (CC0) — isometric blocks, furniture, tiny characters
- **Lenguaje:** Vanilla JS (sin frameworks, sin npm)
- **API:** polling cada 5s al runtime en `http://127.0.0.1:8000`

---

## Arquitectura de archivos

```
control-plane/mission-control-ui/
├── index.html           ← sin cambios estructurales
├── styles.css           ← ajustes menores de layout
├── office.js            ← routing + fetch API + shared state
├── scene-office.js      ← NUEVO: Phaser 3 GameScene
└── assets/
    ├── tileset.png      ← Kenney isometric blocks (CC0)
    ├── furniture.png    ← Kenney isometric furniture (CC0)
    └── characters.png   ← Kenney tiny characters spritesheet (CC0)
```

### Shared state (window.agentState)

`office.js` escribe en `window.agentState` después de cada fetch. `scene-office.js` lo lee en su loop `update()`.

```js
window.agentState = {
  agents: [],        // array from /runtime/agents/state
  stats: {},         // from /runtime/permission/stats
  executions: [],    // from /runtime/executions (si existe)
}
```

---

## La Oficina Isométrica

### Layout (grid 12×10 tiles)

```
┌─────────────────────────────────────────┐
│  🌿        SALA PRINCIPAL         🌿   │
│                                         │
│  [CoS]desk  [Builder]desk  [Review]desk │
│                                         │
│         [ MEETING AREA ]               │
│                                         │
│  [Sec]desk  [Finance]desk  [FinOps]desk │
│                                         │
│  🛋️  lounge area              📚 shelf  │
└─────────────────────────────────────────┘
```

Cada agente tiene un **desk asignado fijo**. El layout se define como array 2D en `scene-office.js`.

### Proyección isométrica

Sin plugin. Matemática inline:

```js
function tileToScreen(tx, ty) {
  return {
    x: (tx - ty) * 32,
    y: (tx + ty) * 16,
  };
}
```

Los bloques tienen 3 caras visibles (top, left, right) para dar profundidad 3D.
**Depth sorting:** cada objeto se ordena por `y` en pantalla — los más cercanos renderizan encima.

### Assets Kenney

| Asset | Pack Kenney | Uso |
|---|---|---|
| `tileset.png` | Isometric Blocks | Piso, paredes, divisores |
| `furniture.png` | Isometric Top-Down Roguelike | Desks, sillas, plants, monitors |
| `characters.png` | Tiny Town / Micro Chars | Personajes 16×16px |

---

## Personajes y Animaciones

### Colores por agente

```js
const AGENT_COLORS = {
  chief_of_staff:     '#ff6b6b',
  fullstack_builder:  '#64c7ff',
  code_reviewer:      '#98ff92',
  security_auditor:   '#ffd166',
  finance_specialist: '#d88cff',
  finops_guard:       '#76f1d4',
};
```

### Estados y animaciones

| Estado API | Animación sprite | Indicador |
|---|---|---|
| `idle` | sitting + breathing (2 frames, loop lento) | dot gris |
| `working` | typing (3 frames, loop rápido) | dot verde pulsante |
| `HITL_WAIT` | standing mirando pantalla (2 frames) | dot amarillo |
| `offline` | ausente (desk vacío) | — |

### Movimiento

- `idle → working`: tween del personaje desde silla hasta monitor (0.8s ease-in-out)
- `working → idle`: tween de regreso a la silla
- Cada agente se mueve de forma independiente

### Floating UI por personaje

- Nombre en texto blanco con sombra negra
- Dot de estado (verde pulsante / gris / amarillo)
- Speech bubble `"..."` animado cuando está en `working`

---

## Páginas

### Home — KPI Cards

4 cards conectadas a la API real con animación count-up al cargar:

| Card | Fuente |
|---|---|
| Events Today | `/runtime/permission/stats` |
| Total Memories | `mem_finance + mem_tech` count |
| Active Agents | agentes con `state === 'working'` |
| Budget Used | suma `cost_usd` de ejecuciones |

### Events — Log en tiempo real

Tabla auto-scroll con filas coloreadas por estado:

```
[14:32:01]  finance_specialist  HITL_WAIT  exec-680dc7c319
[14:31:58]  finops_guard        DONE       exec-680dc7c319
```

Colores: verde=DONE, amarillo=HITL_WAIT, rojo=REJECTED.

### Missions — Kanban

3 columnas: **PROPOSED / RUNNING / DONE**
Cada card muestra: task, agente, costo USD.
Si está en `HITL_WAIT`: botones **Approve** / **Reject** que hacen POST al API.

### Settings

- URL del API (ya existe)
- Intervalo de polling en segundos (default 5s)

---

## Flujo de datos

```
[Runtime API :8000]
       │  fetch cada 5s
       ▼
  office.js
  fetchRuntimeState()
       │  escribe
       ▼
  window.agentState
       │  lee en update()
       ▼
  scene-office.js
  Phaser GameScene
       │  mueve/anima
       ▼
  Canvas (Phaser renderer)
```

---

## No incluido (YAGNI)

- Pathfinding complejo (A*) — tweens simples son suficientes
- Multiplayer / WebSocket — polling HTTP es suficiente
- Editor de mapa — layout fijo en código
- Sonido / música

---

## Criterios de éxito

1. La oficina isométrica se renderiza con tiles 3D y muebles con profundidad
2. Los 6 agentes aparecen como personajes pixel art en sus desks
3. Al cambiar estado en la API, el personaje anima y se mueve en ≤1s
4. Las 4 páginas (Home, Events, Missions, Settings) muestran datos reales
5. El botón Approve/Reject en Missions hace POST correcto al API
6. Todo funciona abriendo `index.html` directamente (no requiere servidor)
