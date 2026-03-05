# Mission Control — Isometric Office Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reemplazar el canvas 2D plano del Mission Control con una oficina isométrica animada en Phaser 3 donde los 6 agentes aparecen como personajes pixel art que se mueven y reaccionan al estado del runtime API.

**Architecture:** Phaser 3 cargado via CDN maneja la escena isométrica en `scene-office.js`. El entorno (piso, paredes, muebles) se dibuja proceduralmente con Phaser.Graphics usando bloques isométricos de 3 caras. Los personajes usan el spritesheet CC0 de Kenney. `office.js` sigue haciendo el fetch al API y escribe en `window.agentState`; la escena Phaser lo lee en `update()`.

**Tech Stack:** Phaser 3.60 (CDN), Vanilla JS, Canvas 2D, Kenney "Tiny Town" spritesheet (CC0), HTML/CSS sin bundler.

---

## Prerequisito: Descargar el spritesheet de personajes

Antes de empezar, descarga el asset de personajes:

1. Ve a `https://kenney.nl/assets/tiny-town` → Download
2. Descomprime → copia `Spritesheet/tilemap_packed.png` a `control-plane/mission-control-ui/assets/characters.png`
3. Tamaño de cada tile: **16×16px**, 12 columnas × 11 filas

> Alternativa si no encuentras ese pack: usa `https://kenney.nl/assets/micro-roguelike` → `tilemap.png`. Tiles de 8×8px, ajustar frameWidth/frameHeight en Task 4.

---

## Task 1: Agregar Phaser 3 y estructura de archivos

**Files:**
- Modify: `control-plane/mission-control-ui/index.html`
- Create: `control-plane/mission-control-ui/scene-office.js`
- Create: `control-plane/mission-control-ui/assets/` (directorio)

**Step 1: Agregar Phaser 3 CDN y nuevo script en index.html**

Antes de `<script src="./office.js"></script>`, agregar:

```html
<script src="https://cdn.jsdelivr.net/npm/phaser@3.60.0/dist/phaser.min.js"></script>
<script src="./scene-office.js"></script>
```

**Step 2: Crear scene-office.js vacío**

```js
// scene-office.js — Phaser 3 isometric office scene
// Se inicializa desde office.js después de que el DOM esté listo
```

**Step 3: Crear directorio assets/**

```bash
mkdir -p control-plane/mission-control-ui/assets
```

**Step 4: Verificar que el archivo carga sin errores**

Abre `index.html` en el browser. En la consola debe aparecer Phaser sin errores (puede haber warnings de canvas existente — normal por ahora).

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/
git commit -m "feat: add Phaser 3 CDN and scene-office.js scaffold"
```

---

## Task 2: Inicializar el juego Phaser en el canvas existente

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js`
- Modify: `control-plane/mission-control-ui/office.js`

**Step 1: Escribir la clase OfficeScene base en scene-office.js**

```js
class OfficeScene extends Phaser.Scene {
  constructor() {
    super({ key: 'OfficeScene' });
    this.agentSprites = {};   // { agent_id: { sprite, label, dot } }
    this.gfx = null;
  }

  preload() {
    this.load.spritesheet('chars', './assets/characters.png', {
      frameWidth: 16,
      frameHeight: 16,
    });
  }

  create() {
    this.gfx = this.add.graphics();
    this.drawOffice();
    this.spawnAgents();
  }

  update() {
    const agents = (window.agentState && window.agentState.agents) || [];
    this.syncAgents(agents);
  }

  drawOffice()  { /* Task 3 */ }
  spawnAgents() { /* Task 4 */ }
  syncAgents()  { /* Task 6 */ }
}
```

**Step 2: Inicializar Phaser reemplazando el canvas en office.js**

Al final de office.js (antes de `initRouting()`), agregar la función `initPhaser()`:

```js
function initPhaser() {
  // Inicializa solo si el canvas existe
  const canvasEl = document.getElementById('office');
  if (!canvasEl || typeof Phaser === 'undefined') return;

  new Phaser.Game({
    type: Phaser.CANVAS,
    canvas: canvasEl,
    width: canvasEl.parentElement.offsetWidth || 900,
    height: 540,
    backgroundColor: '#0a1228',
    scene: [OfficeScene],
    scale: {
      mode: Phaser.Scale.RESIZE,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    // Desactivar el loop de canvas manual que ya existía
  });
}
```

Reemplazar la llamada a `draw()` por `initPhaser()`. Eliminar las funciones antiguas `draw()`, `drawFloor()`, `drawRooms()`, `drawAgents()`.

**Step 3: Agregar window.agentState al fetchRuntimeState existente**

En la función `fetchRuntimeState()` de office.js, después de `state.agents = ...`:

```js
window.agentState = {
  agents: state.agents,
  stats: state.permissionStats,
};
```

**Step 4: Verificar**

Abre el browser → pestaña Agents. El canvas debe estar negro (sin errores). En consola: `Phaser v3.60.0 - ...`.

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/office.js \
        control-plane/mission-control-ui/scene-office.js
git commit -m "feat: initialize Phaser 3 game on existing canvas"
```

---

## Task 3: Dibujar el piso y paredes isométricas

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js` → método `drawOffice()`

**Step 1: Agregar la función de conversión de coordenadas y dibujo de bloque**

Al inicio de `OfficeScene` (antes del constructor), agregar constantes:

```js
const ISO = {
  TW: 64,   // tile width (ancho del diamante)
  TH: 32,   // tile height (alto del diamante)
  ORIGIN_X: 420,  // offset X de la escena
  ORIGIN_Y: 80,   // offset Y de la escena
};

function tileToScreen(tx, ty) {
  return {
    x: ISO.ORIGIN_X + (tx - ty) * (ISO.TW / 2),
    y: ISO.ORIGIN_Y + (tx + ty) * (ISO.TH / 2),
  };
}

function drawIsoBlock(gfx, tx, ty, h, colors) {
  const { x, y } = tileToScreen(tx, ty);
  const hw = ISO.TW / 2;
  const hh = ISO.TH / 2;

  // Cara top (diamante)
  gfx.fillStyle(colors.top);
  gfx.fillPoints([
    { x: x,      y: y - h },
    { x: x + hw, y: y - hh - h },
    { x: x + ISO.TW, y: y - h },
    { x: x + hw, y: y + hh - h },
  ], true);

  // Cara left
  gfx.fillStyle(colors.left);
  gfx.fillPoints([
    { x: x,      y: y - h },
    { x: x + hw, y: y + hh - h },
    { x: x + hw, y: y + hh },
    { x: x,      y: y },
  ], true);

  // Cara right
  gfx.fillStyle(colors.right);
  gfx.fillPoints([
    { x: x + hw, y: y + hh - h },
    { x: x + ISO.TW, y: y - h },
    { x: x + ISO.TW, y: y },
    { x: x + hw, y: y + hh },
  ], true);
}
```

**Step 2: Implementar `drawOffice()`**

```js
drawOffice() {
  const g = this.gfx;
  const FLOOR = { top: 0x1e3a6e, left: 0x122444, right: 0x0e1c38 };
  const WALL  = { top: 0x2a4f8c, left: 0x1a3060, right: 0x142448 };
  const DESK  = { top: 0xd4a96a, left: 0x8a6a3e, right: 0x6e5030 };
  const PLANT = { top: 0x4caf50, left: 0x2e7d32, right: 0x1b5e20 };

  // Piso: grid 10×8
  for (let tx = 0; tx < 10; tx++) {
    for (let ty = 0; ty < 8; ty++) {
      drawIsoBlock(g, tx, ty, 0, FLOOR);
    }
  }

  // Paredes traseras (borde superior)
  for (let tx = 0; tx < 10; tx++) {
    drawIsoBlock(g, tx, -1, 24, WALL);
  }
  for (let ty = 0; ty < 8; ty++) {
    drawIsoBlock(g, -1, ty, 24, WALL);
  }

  // Plantas en esquinas
  drawIsoBlock(g, 0, 0, 28, PLANT);
  drawIsoBlock(g, 9, 0, 28, PLANT);
  drawIsoBlock(g, 0, 7, 28, PLANT);

  // Desks para los 6 agentes
  // Fila superior
  this.drawDesk(g, 1, 1, DESK);  // chief_of_staff
  this.drawDesk(g, 4, 1, DESK);  // fullstack_builder
  this.drawDesk(g, 7, 1, DESK);  // code_reviewer
  // Fila inferior
  this.drawDesk(g, 1, 5, DESK);  // security_auditor
  this.drawDesk(g, 4, 5, DESK);  // finance_specialist
  this.drawDesk(g, 7, 5, DESK);  // finops_guard

  // Área de reunión central (mesa)
  drawIsoBlock(g, 4, 3, 16, { top: 0x37474f, left: 0x263238, right: 0x1c2629 });
  drawIsoBlock(g, 5, 3, 16, { top: 0x37474f, left: 0x263238, right: 0x1c2629 });
}

drawDesk(g, tx, ty, color) {
  // Superficie del escritorio
  drawIsoBlock(g, tx, ty, 20, color);
  // Monitor encima
  const MON = { top: 0x546e7a, left: 0x37474f, right: 0x263238 };
  drawIsoBlock(g, tx, ty, 36, MON);
}
```

**Step 3: Verificar visualmente**

Abre browser. La pestaña Agents debe mostrar una oficina isométrica con:
- Piso azul oscuro en grid
- Paredes grises en los bordes
- 6 escritorios con monitores
- Mesa central
- Plantas en esquinas

**Step 4: Commit**

```bash
git add control-plane/mission-control-ui/scene-office.js
git commit -m "feat: draw isometric office floor, walls, and desks"
```

---

## Task 4: Agregar personajes pixel art

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js` → método `spawnAgents()`

**Step 1: Definir posiciones y colores de agentes**

Al inicio de `OfficeScene`, agregar:

```js
const AGENT_CONFIG = {
  chief_of_staff:     { tx: 1, ty: 1, color: 0xff6b6b, frame: 0 },
  fullstack_builder:  { tx: 4, ty: 1, color: 0x64c7ff, frame: 1 },
  code_reviewer:      { tx: 7, ty: 1, color: 0x98ff92, frame: 2 },
  security_auditor:   { tx: 1, ty: 5, color: 0xffd166, frame: 3 },
  finance_specialist: { tx: 4, ty: 5, color: 0xd88cff, frame: 4 },
  finops_guard:       { tx: 7, ty: 5, color: 0x76f1d4, frame: 5 },
};
```

**Step 2: Implementar `spawnAgents()`**

```js
spawnAgents() {
  Object.entries(AGENT_CONFIG).forEach(([agentId, cfg]) => {
    const pos = tileToScreen(cfg.tx, cfg.ty);
    const px = pos.x + ISO.TW / 2;
    const py = pos.y - 20;  // encima del desk

    // Sprite del personaje (tintado con color del agente)
    const sprite = this.add.sprite(px, py, 'chars', cfg.frame);
    sprite.setScale(2.5);
    sprite.setTint(cfg.color);
    sprite.setDepth(py);

    // Label con nombre
    const label = this.add.text(px, py - 22, agentId.replace(/_/g, ' '), {
      fontSize: '10px',
      color: '#ffffff',
      stroke: '#000000',
      strokeThickness: 3,
      align: 'center',
    }).setOrigin(0.5, 1).setDepth(py + 1);

    // Dot de estado (círculo pequeño)
    const dot = this.add.circle(px + 14, py - 14, 4, 0x888888);
    dot.setDepth(py + 2);

    this.agentSprites[agentId] = { sprite, label, dot, state: 'offline', tx: cfg.tx, ty: cfg.ty };
  });
}
```

**Step 3: Verificar**

Recarga browser. Deben aparecer 6 personajes pequeños sobre los escritorios con sus nombres flotantes y dots grises.

Si el spritesheet no carga (no descargaste el PNG aún), los sprites aparecen como cuadrados blancos — normal, agrega el PNG a `assets/characters.png` y recarga.

**Step 4: Commit**

```bash
git add control-plane/mission-control-ui/scene-office.js \
        control-plane/mission-control-ui/assets/
git commit -m "feat: spawn agent character sprites on desks"
```

---

## Task 5: Crear animaciones de los personajes

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js` → método `create()`

**Step 1: Definir animaciones en `create()`, antes de `spawnAgents()`**

```js
// Animación idle: frames 0-1 (ajustar según el spritesheet descargado)
this.anims.create({
  key: 'idle',
  frames: this.anims.generateFrameNumbers('chars', { start: 0, end: 1 }),
  frameRate: 2,
  repeat: -1,
});

// Animación working (typing): frames 2-4
this.anims.create({
  key: 'working',
  frames: this.anims.generateFrameNumbers('chars', { start: 2, end: 4 }),
  frameRate: 8,
  repeat: -1,
});

// Animación walking: frames 5-8
this.anims.create({
  key: 'walking',
  frames: this.anims.generateFrameNumbers('chars', { start: 5, end: 8 }),
  frameRate: 10,
  repeat: -1,
});

// Animación HITL_WAIT (parado mirando): frames 9-10
this.anims.create({
  key: 'hitl_wait',
  frames: this.anims.generateFrameNumbers('chars', { start: 9, end: 10 }),
  frameRate: 3,
  repeat: -1,
});
```

> Nota: los frame numbers exactos dependen del spritesheet descargado. Ajustar después de verificar visualmente qué frames corresponden a qué animación.

**Step 2: Aplicar animación idle a todos los sprites en `spawnAgents()`**

Después de crear el sprite, agregar:

```js
sprite.play('idle');
```

**Step 3: Verificar**

Los personajes deben parpadear/animarse suavemente en estado idle.

**Step 4: Commit**

```bash
git add control-plane/mission-control-ui/scene-office.js
git commit -m "feat: add sprite animations (idle, working, walking, hitl_wait)"
```

---

## Task 6: Sincronizar agentes con estado del API

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js` → método `syncAgents()`

**Step 1: Implementar `syncAgents(agents)`**

```js
syncAgents(agents) {
  // Poner todos offline primero
  Object.values(this.agentSprites).forEach(a => {
    if (a.state !== 'offline') {
      a.dot.setFillStyle(0x888888);
    }
  });

  agents.forEach(apiAgent => {
    const entry = this.agentSprites[apiAgent.agent_id];
    if (!entry) return;

    const prevState = entry.state;
    const newState  = apiAgent.state; // 'idle' | 'working' | 'HITL_WAIT'

    if (prevState === newState) return;  // sin cambio

    entry.state = newState;

    if (newState === 'working') {
      entry.dot.setFillStyle(0x2ecc71);
      entry.sprite.play('working');
      this.tweenToDesk(entry);
    } else if (newState === 'HITL_WAIT') {
      entry.dot.setFillStyle(0xf1c40f);
      entry.sprite.play('hitl_wait');
    } else {
      entry.dot.setFillStyle(0x888888);
      entry.sprite.play('idle');
    }
  });
}

tweenToDesk(entry) {
  // El agente "se levanta" y va al monitor
  const cfg = AGENT_CONFIG[Object.keys(this.agentSprites).find(k => this.agentSprites[k] === entry)];
  if (!cfg) return;

  const dest = tileToScreen(cfg.tx, cfg.ty);
  const destX = dest.x + ISO.TW / 2;
  const destY = dest.y - 30;  // un poco más arriba = frente al monitor

  entry.sprite.play('walking');
  this.tweens.add({
    targets: [entry.sprite, entry.label, entry.dot],
    x: `+=${(Math.random() - 0.5) * 20}`,  // pequeño movimiento
    y: `-=10`,
    duration: 400,
    ease: 'Power2',
    yoyo: true,
    onComplete: () => entry.sprite.play('working'),
  });
}
```

**Step 2: Pulsar el dot verde cuando está working**

Agregar en `update()` (después de `syncAgents`):

```js
// Pulsar dot de agentes working
Object.values(this.agentSprites).forEach(a => {
  if (a.state === 'working') {
    const pulse = 0.85 + 0.15 * Math.sin(this.time.now / 300);
    a.dot.setScale(pulse);
  }
});
```

**Step 3: Verificar con el API real**

Con el runtime corriendo en el servidor (o tunel SSH), lanza una ejecución:
```bash
curl -X POST http://127.0.0.1:8000/runtime/execute \
  -H "Content-Type: application/json" \
  -d '{"task":"test visual","agent_id":"finance_specialist","budget_key":"bk-test","domain":"mem_finance"}'
```

El agente `finance_specialist` debe cambiar su dot a verde y animarse.

**Step 4: Commit**

```bash
git add control-plane/mission-control-ui/scene-office.js
git commit -m "feat: sync agent states from API to Phaser scene"
```

---

## Task 7: Speech bubble para agentes working

**Files:**
- Modify: `control-plane/mission-control-ui/scene-office.js`

**Step 1: Agregar speech bubble en `spawnAgents()`**

Después de crear el dot, agregar:

```js
const bubble = this.add.text(px, py - 34, '...', {
  fontSize: '11px',
  color: '#ffffff',
  backgroundColor: '#1a2a4a',
  padding: { x: 5, y: 3 },
  borderRadius: 4,
}).setOrigin(0.5, 1).setDepth(py + 3).setVisible(false);

this.agentSprites[agentId].bubble = bubble;
```

**Step 2: Mostrar/ocultar bubble en `syncAgents()`**

En el bloque `if (newState === 'working')`:
```js
entry.bubble.setVisible(true);
```

En el bloque `else`:
```js
entry.bubble.setVisible(false);
```

**Step 3: Animar el texto `...` en `update()`**

```js
const dots = ['.', '..', '...'];
const dotFrame = Math.floor(this.time.now / 500) % 3;
Object.values(this.agentSprites).forEach(a => {
  if (a.state === 'working' && a.bubble) {
    a.bubble.setText(dots[dotFrame]);
  }
});
```

**Step 4: Verificar**

Agentes en `working` muestran una burbuja `...` animada sobre su cabeza.

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/scene-office.js
git commit -m "feat: add animated speech bubble for working agents"
```

---

## Task 8: Mejorar Home — KPI cards con datos reales

**Files:**
- Modify: `control-plane/mission-control-ui/office.js`
- Modify: `control-plane/mission-control-ui/index.html`

**Step 1: Agregar 2 KPI cards faltantes en index.html**

En `#page-home .grid`, agregar después de las 2 cards existentes:

```html
<div class="card">
  <div class="card-hd">
    <div class="title">Active Agents</div>
    <div class="muted">Working now</div>
  </div>
  <div class="kpi" id="kpiActive">-</div>
</div>
<div class="card">
  <div class="card-hd">
    <div class="title">Budget Used</div>
    <div class="muted">This session</div>
  </div>
  <div class="kpi" id="kpiBudget">-</div>
</div>
```

**Step 2: Función countUp en office.js**

```js
function countUp(el, target, suffix = '') {
  const start = 0;
  const duration = 800;
  const startTime = performance.now();
  function tick(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    el.textContent = Math.floor(progress * target) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
```

**Step 3: Actualizar KPIs en `fetchRuntimeState()`**

```js
const kpiEvents   = document.getElementById('kpiEvents');
const kpiMemories = document.getElementById('kpiMemories');
const kpiActive   = document.getElementById('kpiActive');
const kpiBudget   = document.getElementById('kpiBudget');

if (kpiEvents)   countUp(kpiEvents,   state.permissionStats.active_tokens || 0);
if (kpiActive)   countUp(kpiActive,   state.agents.filter(a => a.state === 'working').length);
if (kpiMemories) kpiMemories.textContent = state.agents.length;  // placeholder
if (kpiBudget) {
  const total = state.agents.reduce((s, a) => s + (a.cost_usd || 0), 0);
  kpiBudget.textContent = `$${total.toFixed(3)}`;
}
```

**Step 4: Verificar**

Navega a Home. Los 4 KPIs deben mostrar números reales (o 0 si no hay actividad), con animación count-up.

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/index.html \
        control-plane/mission-control-ui/office.js
git commit -m "feat: wire KPI cards to real API data with count-up animation"
```

---

## Task 9: Events page — log en tiempo real

**Files:**
- Modify: `control-plane/mission-control-ui/index.html`
- Modify: `control-plane/mission-control-ui/office.js`
- Modify: `control-plane/mission-control-ui/styles.css`

**Step 1: Reemplazar el placeholder de Events en index.html**

```html
<section id="page-events" class="page hidden">
  <div class="card">
    <div class="card-hd">
      <div class="title">Events</div>
      <div class="muted">Runtime log</div>
    </div>
    <div id="eventLog" class="event-log"></div>
  </div>
</section>
```

**Step 2: Estilos para el log en styles.css**

```css
.event-log {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  max-height: 500px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.event-row {
  display: flex;
  gap: 14px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  align-items: center;
}
.event-row.done     { background: rgba(46,204,113,.08); }
.event-row.wait     { background: rgba(241,196,15,.08); }
.event-row.rejected { background: rgba(231,76,60,.08); }
.event-row.running  { background: rgba(100,199,255,.08); }
.event-time  { color: var(--muted); min-width: 75px; }
.event-agent { font-weight: 700; min-width: 160px; }
.event-state { min-width: 100px; }
.event-id    { color: var(--muted); font-size: 11px; }
```

**Step 3: Renderizar events en office.js**

En `fetchRuntimeState()`, después de poblar `state.permissionRecent`:

```js
function renderEvents() {
  const el = document.getElementById('eventLog');
  if (!el) return;
  const rows = (state.permissionRecent || []).map(ev => {
    const ts  = new Date(ev.created_at || Date.now()).toLocaleTimeString();
    const cls = ev.status === 'DONE'      ? 'done'
              : ev.status === 'HITL_WAIT' ? 'wait'
              : ev.status === 'REJECTED'  ? 'rejected'
              : 'running';
    return `<div class="event-row ${cls}">
      <span class="event-time">${esc(ts)}</span>
      <span class="event-agent">${esc(ev.agent_id || '-')}</span>
      <span class="event-state">${esc(ev.status || '-')}</span>
      <span class="event-id">${esc(ev.execution_id || '')}</span>
    </div>`;
  });
  el.innerHTML = rows.join('') || '<div class="muted" style="padding:12px">Sin eventos recientes</div>';
  el.scrollTop = el.scrollHeight;
}
```

Llamar `renderEvents()` al final de `fetchRuntimeState()`.

**Step 4: Verificar**

Navega a Events. Deben aparecer filas coloreadas con timestamps. Si no hay eventos, muestra el mensaje vacío.

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/index.html \
        control-plane/mission-control-ui/office.js \
        control-plane/mission-control-ui/styles.css
git commit -m "feat: events page with real-time colored log"
```

---

## Task 10: Missions page — Kanban con Approve/Reject

**Files:**
- Modify: `control-plane/mission-control-ui/office.js`
- Modify: `control-plane/mission-control-ui/styles.css`

**Step 1: Agregar fetch de executions en `fetchRuntimeState()`**

```js
try {
  // Obtener lista de ejecuciones activas del runtime
  // El endpoint /runtime/executions puede no existir aún; si falla, usar permissionRecent
  const execs = await fetchJson(api('/runtime/executions'));
  state.executions = execs.items || [];
} catch {
  // Derivar del permissionRecent como fallback
  state.executions = (state.permissionRecent || []).reduce((acc, ev) => {
    if (!acc.find(e => e.execution_id === ev.execution_id)) acc.push(ev);
    return acc;
  }, []);
}
```

**Step 2: Implementar `renderKanban()` con datos reales**

Reemplazar la función existente:

```js
function renderKanban() {
  if (!kanbanEl) return;

  const proposed = state.executions.filter(e => e.status === 'VALIDATION' || e.status === 'DECOMPOSITION');
  const running  = state.executions.filter(e => ['EXECUTION','AUDIT','SECURITY_GATE','CONSOLIDATION','EXEC_SUMMARY','HITL_WAIT'].includes(e.status));
  const done     = state.executions.filter(e => e.status === 'DONE' || e.status === 'REJECTED');

  function card(e) {
    const isWait = e.status === 'HITL_WAIT';
    return `<div class="mcard">
      <div class="mcard-title">${esc(e.task || e.execution_id || '-')}</div>
      <div class="mcard-desc">${esc(e.agent_id || '')} · $${(e.cost_usd || 0).toFixed(4)}</div>
      <div class="mcard-foot">
        <span class="chip">${esc(e.status)}</span>
        ${isWait ? `
          <div class="btns">
            <button class="btn ok" onclick="approveExec('${esc(e.execution_id)}')">Approve</button>
            <button class="btn bad" onclick="rejectExec('${esc(e.execution_id)}')">Reject</button>
          </div>` : ''}
      </div>
    </div>`;
  }

  const cols = [
    { name: 'Proposed', items: proposed },
    { name: 'Running',  items: running },
    { name: 'Done',     items: done },
  ];

  kanbanEl.innerHTML = cols.map(c => `
    <div class="kcol">
      <div class="khd">
        <div class="name">${c.name}</div>
        <div class="count">${c.items.length}</div>
      </div>
      ${c.items.map(card).join('')}
    </div>
  `).join('');
}
```

**Step 3: Agregar funciones approve/reject en office.js**

```js
window.approveExec = async function(execId) {
  try {
    await fetch(api(`/runtime/approve`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ execution_id: execId }),
    });
    fetchRuntimeState();
  } catch (e) {
    alert('Error: ' + e.message);
  }
};

window.rejectExec = async function(execId) {
  try {
    await fetch(api(`/runtime/reject`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ execution_id: execId }),
    });
    fetchRuntimeState();
  } catch (e) {
    alert('Error: ' + e.message);
  }
};
```

**Step 4: Verificar**

Navega a Missions. Las 3 columnas Kanban deben aparecer. Si hay una ejecución en HITL_WAIT, deben aparecer los botones Approve/Reject funcionales.

**Step 5: Commit**

```bash
git add control-plane/mission-control-ui/office.js \
        control-plane/mission-control-ui/styles.css
git commit -m "feat: missions kanban with real data and approve/reject buttons"
```

---

## Task 11: Settings page + polish visual

**Files:**
- Modify: `control-plane/mission-control-ui/index.html`
- Modify: `control-plane/mission-control-ui/office.js`
- Modify: `control-plane/mission-control-ui/styles.css`

**Step 1: Settings page en index.html**

```html
<section id="page-settings" class="page hidden">
  <div class="card">
    <div class="card-hd">
      <div class="title">Settings</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:14px;max-width:400px">
      <label>
        <div class="muted" style="margin-bottom:6px">API Base URL</div>
        <input id="apiBase2" type="text" style="width:100%"/>
      </label>
      <label>
        <div class="muted" style="margin-bottom:6px">Polling interval (segundos)</div>
        <input id="pollInterval" type="number" value="5" min="2" max="60" style="width:100px"/>
      </label>
      <button id="saveSettings" class="btn">Guardar</button>
    </div>
  </div>
</section>
```

**Step 2: Sincronizar apiBase2 con el input de la topbar**

```js
const apiBase2 = document.getElementById('apiBase2');
const pollIntervalEl = document.getElementById('pollInterval');
const saveSettingsBtn = document.getElementById('saveSettings');

if (apiBase2) apiBase2.value = state.base;

if (saveSettingsBtn) {
  saveSettingsBtn.addEventListener('click', () => {
    state.base = (apiBase2 && apiBase2.value.trim()) || state.base;
    apiBaseInput.value = state.base;
    localStorage.setItem('apiBase', state.base);

    const interval = parseInt((pollIntervalEl && pollIntervalEl.value) || '5', 10);
    localStorage.setItem('pollInterval', String(interval));

    clearInterval(window._pollTimer);
    window._pollTimer = setInterval(fetchRuntimeState, interval * 1000);
    fetchRuntimeState();
  });
}
```

Reemplazar el `setInterval` fijo al final de office.js:

```js
const pollMs = parseInt(localStorage.getItem('pollInterval') || '5', 10) * 1000;
window._pollTimer = setInterval(fetchRuntimeState, pollMs);
```

**Step 3: Agregar íconos SVG al sidebar en index.html**

Reemplazar los links de texto plano del sidebar con íconos inline:

```html
<a href="#home" data-route="home" class="active">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
  Home
</a>
<a href="#missions" data-route="missions">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
  Missions
</a>
<a href="#agents" data-route="agents">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>
  Agents
</a>
<a href="#events" data-route="events">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
  Events
</a>
<a href="#analytics" data-route="analytics">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
  Analytics
</a>
<a href="#settings" data-route="settings">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 0-14.14 0M4.93 19.07a10 10 0 0 0 14.14 0"/></svg>
  Settings
</a>
```

Actualizar CSS del nav para mostrar íconos + texto:

```css
.nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  /* resto igual */
}
```

**Step 4: Verificar**

Navega por todas las páginas. El sidebar debe tener íconos, Settings debe guardar el intervalo de polling.

**Step 5: Commit final**

```bash
git add control-plane/mission-control-ui/
git commit -m "feat: settings page, sidebar icons, configurable polling interval"
```

---

## Verificación final (criterios de éxito)

```
[ ] La oficina isométrica renderiza con tiles 3D y depth sorting correcto
[ ] Los 6 agentes aparecen como sprites sobre sus desks con nombres flotantes
[ ] Al cambiar estado en el API, el personaje anima en ≤1s
[ ] Speech bubble "..." aparece en agentes working
[ ] Home muestra 4 KPIs reales con animación count-up
[ ] Events muestra log coloreado y auto-scroll
[ ] Missions muestra Kanban con botones Approve/Reject funcionales
[ ] Settings guarda URL y polling interval en localStorage
[ ] Todo funciona abriendo index.html directamente (file:// o servidor estático)
```

---

## Notas de ajuste post-implementación

- **Frames del spritesheet:** Los números de frame exactos en Task 5 dependen del PNG descargado. Usar las DevTools del browser con `scene.textures.get('chars').getFrameNames()` para ver los frames disponibles.
- **Escala del canvas:** Si la oficina se ve muy pequeña o grande, ajustar `ISO.TW`, `ISO.TH` y `ISO.ORIGIN_X/Y` en scene-office.js.
- **Depth sorting dinámico:** Si los personajes se solapan mal con los muebles, agregar `sprite.setDepth(sprite.y)` en `update()`.
