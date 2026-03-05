(() => {
  /* ── Isometric config ─────────────────────────────────────── */
  const TW = 64;   // tile width (diamond full width)
  const TH = 32;   // tile height (= TW/2)
  const OX = 420;  // origin X (north-tip of tile 0,0)
  const OY = 100;  // origin Y

  /* ── Agent definitions ───────────────────────────────────── */
  const AGENTS = {
    chief_of_staff:     { tile: [2, 1], color: 0xff8cb8, label: "🧠 Chief"    },
    fullstack_builder:  { tile: [5, 1], color: 0x7fd6ff, label: "🛠️ Builder"  },
    code_reviewer:      { tile: [8, 1], color: 0x9bf59d, label: "🧪 Review"   },
    security_auditor:   { tile: [2, 5], color: 0xffc18a, label: "🛡️ Security" },
    finance_specialist: { tile: [5, 5], color: 0xd8b4ff, label: "💸 Finance"  },
    devops_engineer:    { tile: [8, 5], color: 0x7cefd7, label: "☁️ DevOps"   },
  };

  const PALETTE = {
    beige: 0xf5e6d3,
    pink: 0xffd4e5,
    lilac: 0xe8d5f5,
    mint: 0xd5f5e3,
    cream: 0xfff4e6,
    warmLight: 0xffd48f,
  };

  /* ── Helpers ─────────────────────────────────────────────── */
  function iso(tx, ty) {
    return {
      x: OX + (tx - ty) * (TW / 2),
      y: OY + (tx + ty) * (TH / 2),
    };
  }

  // Darken a hex color (pct 0-100)
  function dk(hex, pct) {
    const f = 1 - pct / 100;
    return (
      (Math.round(((hex >> 16) & 0xff) * f) << 16) |
      (Math.round(((hex >> 8) & 0xff) * f) << 8) |
       Math.round( (hex & 0xff)        * f)
    );
  }

  /* ── Scene ───────────────────────────────────────────────── */
  class OfficeScene extends Phaser.Scene {
    constructor() {
      super("OfficeScene");
      this.agentViews    = new Map();
      this.lastBubbleTick = 0;
      this.bubbleIndex   = 0;
      this.bubbleFrames  = [".", "..", "..."];
    }

    preload() { /* no external assets needed */ }

    create() {
      this._drawOffice();
      this._spawnAgents();
    }

    /* ── Primitive: flat diamond tile ─────────────────────── */
    _tile(g, tx, ty, color, alpha = 1) {
      const { x, y } = iso(tx, ty);
      const hw = TW / 2, hh = TH / 2;
      g.fillStyle(color, alpha);
      g.beginPath();
      g.moveTo(x,      y);
      g.lineTo(x + hw, y + hh);
      g.lineTo(x,      y + TH);
      g.lineTo(x - hw, y + hh);
      g.closePath();
      g.fillPath();
    }

    /* ── Primitive: 3-face isometric box ─────────────────── */
    // h = pixel height, topC / leftC / rightC = face colours
    _box(g, tx, ty, h, topC, leftC, rightC) {
      const { x, y } = iso(tx, ty);
      const hw = TW / 2, hh = TH / 2;

      // Top face
      g.fillStyle(topC, 1);
      g.beginPath();
      g.moveTo(x,      y - h);
      g.lineTo(x + hw, y - h + hh);
      g.lineTo(x,      y - h + TH);
      g.lineTo(x - hw, y - h + hh);
      g.closePath();
      g.fillPath();

      // Left / west face
      g.fillStyle(leftC, 1);
      g.beginPath();
      g.moveTo(x - hw, y - h + hh);
      g.lineTo(x,      y - h + TH);
      g.lineTo(x,      y + TH);
      g.lineTo(x - hw, y + hh);
      g.closePath();
      g.fillPath();

      // Right / east face
      g.fillStyle(rightC, 1);
      g.beginPath();
      g.moveTo(x + hw, y - h + hh);
      g.lineTo(x,      y - h + TH);
      g.lineTo(x,      y + TH);
      g.lineTo(x + hw, y + hh);
      g.closePath();
      g.fillPath();
    }

    /* ── Draw the static office geometry ─────────────────── */
    _drawOffice() {
      const { width: W, height: H } = this.scale;
      const floorColors = [0xf9eee1, 0xf5e6d3, 0xf8f1e7, 0xf2e7da];

      // Pastel ambient backdrop + warm spot gradients
      const bg = this.add.graphics();
      bg.fillGradientStyle(PALETTE.cream, PALETTE.cream, 0xefe8ff, 0xeaf9f1, 1);
      bg.fillRect(0, 0, W, H);
      bg.fillStyle(0xffd58f, 0.18);
      bg.fillCircle(W * 0.16, H * 0.12, 190);
      bg.fillStyle(0xffc27a, 0.13);
      bg.fillCircle(W * 0.84, H * 0.16, 220);
      bg.fillStyle(0xffedc3, 0.10);
      bg.fillCircle(W * 0.52, H * 0.04, 180);
      bg.setDepth(-220);

      /* ── FLOOR: light wood + decorative rugs ─────────────── */
      const floor = this.add.graphics();
      floor.lineStyle(1, 0xe2cfbb, 0.55);
      for (let ty = 0; ty < 9; ty++) {
        for (let tx = 0; tx < 11; tx++) {
          const c = floorColors[(tx + ty) % floorColors.length];
          this._tile(floor, tx, ty, c, 1);
          const { x, y } = iso(tx, ty);
          const hw = TW / 2;
          floor.strokePoints([
            { x, y },
            { x: x + hw, y: y + TH / 2 },
            { x, y: y + TH },
            { x: x - hw, y: y + TH / 2 },
          ], true);
          // subtle plank-like strokes
          floor.lineStyle(1, 0xeedecf, 0.35);
          floor.beginPath();
          floor.moveTo(x - 8, y + TH / 2 - 3);
          floor.lineTo(x + 8, y + TH / 2 + 3);
          floor.strokePath();
        }
      }
      floor.setDepth(1);

      const rugs = this.add.graphics();
      [[3, 2], [4, 2], [5, 2], [6, 2], [7, 2], [3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [3, 4], [4, 4], [5, 4], [6, 4], [7, 4]].forEach(([tx, ty]) => {
        this._tile(rugs, tx, ty, PALETTE.lilac, 0.55);
      });
      [[1, 7], [2, 7], [3, 7], [1, 8], [2, 8], [3, 8]].forEach(([tx, ty]) => {
        this._tile(rugs, tx, ty, PALETTE.pink, 0.45);
      });
      rugs.setDepth(2);

      /* ── WALLS: cream pastel ─────────────────────────────── */
      const walls = this.add.graphics();
      walls.lineStyle(1, 0xd7bea4, 0.65);
      for (let tx = 0; tx < 11; tx++) {
        this._box(walls, tx, 0, 44, PALETTE.cream, 0xf1dfcb, 0xead5bf);
      }
      for (let ty = 1; ty < 9; ty++) {
        this._box(walls, 0, ty, 44, PALETTE.cream, 0xf1dfcb, 0xead5bf);
      }
      walls.setDepth(4);

      const wallDecor = this.add.graphics();
      // Two large wall screens
      const ws1 = iso(4, 0);
      wallDecor.fillStyle(0xb89faa, 1);
      wallDecor.fillRoundedRect(ws1.x - 68, ws1.y - 36, 136, 52, 8);
      wallDecor.fillStyle(0x84d9ff, 0.95);
      wallDecor.fillRoundedRect(ws1.x - 62, ws1.y - 30, 124, 40, 6);
      const ws2 = iso(0, 4);
      wallDecor.fillStyle(0xb89faa, 1);
      wallDecor.fillRoundedRect(ws2.x - 28, ws2.y - 52, 90, 44, 8);
      wallDecor.fillStyle(0x9fe9ff, 0.95);
      wallDecor.fillRoundedRect(ws2.x - 22, ws2.y - 46, 78, 32, 6);

      // Frames / paintings
      [[2, 0, PALETTE.pink], [6, 0, PALETTE.mint], [0, 6, PALETTE.lilac]].forEach(([tx, ty, color]) => {
        const p = iso(tx, ty);
        wallDecor.fillStyle(0xceb295, 1);
        wallDecor.fillRoundedRect(p.x - 24, p.y - 30, 48, 26, 4);
        wallDecor.fillStyle(color, 0.95);
        wallDecor.fillRoundedRect(p.x - 20, p.y - 26, 40, 18, 3);
      });

      // Clock
      const clock = iso(5, 0);
      wallDecor.fillStyle(0xffffff, 0.92);
      wallDecor.fillCircle(clock.x + 86, clock.y - 18, 12);
      wallDecor.lineStyle(2, 0x8a7060, 1);
      wallDecor.strokeCircle(clock.x + 86, clock.y - 18, 12);
      wallDecor.beginPath();
      wallDecor.moveTo(clock.x + 86, clock.y - 18);
      wallDecor.lineTo(clock.x + 86, clock.y - 24);
      wallDecor.moveTo(clock.x + 86, clock.y - 18);
      wallDecor.lineTo(clock.x + 92, clock.y - 15);
      wallDecor.strokePath();

      // Whiteboard
      const board = iso(8, 0);
      wallDecor.fillStyle(0xffffff, 0.95);
      wallDecor.fillRoundedRect(board.x - 42, board.y - 34, 84, 36, 6);
      wallDecor.lineStyle(2, 0xc3a88d, 1);
      wallDecor.strokeRoundedRect(board.x - 42, board.y - 34, 84, 36, 6);
      wallDecor.lineStyle(2, 0x9ad0ff, 0.9);
      wallDecor.beginPath();
      wallDecor.moveTo(board.x - 30, board.y - 14);
      wallDecor.lineTo(board.x + 20, board.y - 22);
      wallDecor.moveTo(board.x - 30, board.y - 7);
      wallDecor.lineTo(board.x + 12, board.y - 11);
      wallDecor.strokePath();
      wallDecor.setDepth(80);

      /* ── DESKS (6 workstations) ──────────────────────────── */
      const DESK_TILES = [
        [2, 1], [5, 1], [8, 1],
        [2, 5], [5, 5], [8, 5],
      ];
      const DESK_H = 20;
      DESK_TILES.forEach(([tx, ty]) => {
        const { x, y } = iso(tx, ty);
        const depth = y + TH;

        const shadow = this.add.graphics();
        shadow.fillStyle(0x000000, 0.10);
        shadow.fillEllipse(x + 2, y + TH + 5, 52, 18);
        shadow.setDepth(depth - 0.5);

        const desk = this.add.graphics();
        this._box(desk, tx, ty, DESK_H, 0xf7d9b7, 0xe6c39f, 0xf0cfad);
        desk.lineStyle(1, 0xeed6bf, 0.6);
        desk.beginPath();
        desk.moveTo(x - 10, y - DESK_H + 5);
        desk.lineTo(x + 21, y - DESK_H + 16);
        desk.strokePath();
        desk.setDepth(depth);

        const setup = this.add.graphics();
        const mx = x + 10;
        const my = y - DESK_H - 16;
        setup.fillStyle(0x9f93ad, 1);
        setup.fillRoundedRect(mx - 13, my - 13, 26, 19, 3);
        setup.fillStyle(0xc9f0ff, 0.95);
        setup.fillRoundedRect(mx - 11, my - 11, 22, 15, 2);
        setup.fillStyle(0x7cefd7, 0.65);
        setup.fillRect(mx - 9, my - 9, 14, 2);
        setup.fillStyle(0x87b7ff, 0.55);
        setup.fillRect(mx - 9, my - 6, 10, 2);
        setup.fillStyle(0xaf89d8, 0.6);
        setup.fillRect(mx - 9, my - 3, 12, 2);
        setup.fillStyle(0x9f93ad, 1);
        setup.fillRect(mx - 2, my + 5, 4, 4);
        setup.fillRect(mx - 7, my + 8, 14, 2);
        setup.fillStyle(PALETTE.pink, 1);
        setup.fillCircle(mx + 10, my + 10, 3);
        setup.lineStyle(1, 0xb9889f, 0.9);
        setup.strokeCircle(mx + 13, my + 10, 2);
        setup.setDepth(depth + 4);
      });

      /* ── Lounge sofas + coffee table ─────────────────────── */
      const lounge = this.add.graphics();
      [[3, 5], [4, 5], [5, 5]].forEach(([tx, ty]) => this._box(lounge, tx, ty, 14, PALETTE.pink, 0xe9bfd0, 0xf3c9da));
      [[3, 6], [4, 6], [5, 6]].forEach(([tx, ty]) => this._box(lounge, tx, ty, 25, 0xf2bfd3, 0xe3aebf, 0xeeb8ca));
      [[6, 4], [7, 4]].forEach(([tx, ty]) => this._box(lounge, tx, ty, 14, PALETTE.mint, 0xbfead4, 0xcaf0dc));
      [[6, 5], [7, 5]].forEach(([tx, ty]) => this._box(lounge, tx, ty, 25, 0xc6f0da, 0xb2dfc7, 0xbde8d0));
      this._box(lounge, 5, 3, 12, PALETTE.beige, 0xe6cfb3, 0xefdac1);
      this._box(lounge, 6, 3, 12, PALETTE.beige, 0xe6cfb3, 0xefdac1);
      const coffee = iso(5, 3);
      lounge.fillStyle(0xfff7ed, 0.95);
      lounge.fillCircle(coffee.x + 10, coffee.y - 6, 5);
      lounge.fillStyle(0xffd4e5, 0.92);
      lounge.fillCircle(coffee.x - 6, coffee.y - 4, 4);
      lounge.setDepth(iso(5, 6).y + 70);

      /* ── Stands, bookshelf, and floor lamps ──────────────── */
      const furniture = this.add.graphics();
      // Bookshelf with colorful books
      [[10, 2], [10, 3], [10, 4]].forEach(([tx, ty]) => {
        const p = iso(tx, ty);
        this._box(furniture, tx, ty, 46, 0xf0d6b8, 0xdcbc9a, 0xe8cba9);
        [0xffb0c9, 0xc3a4f4, 0xa9f0cd, 0xb7d7ff, 0xffd8a6].forEach((c, i) => {
          furniture.fillStyle(c, 1);
          furniture.fillRect(p.x - 14 + i * 6, p.y - 39 + (i % 2), 4, 9);
        });
      });

      // Floor lamps
      [[1, 3], [9, 6]].forEach(([tx, ty]) => {
        const p = iso(tx, ty);
        furniture.fillStyle(0xb4a39a, 1);
        furniture.fillRect(p.x - 1, p.y - 52, 2, 35);
        furniture.fillStyle(0xffecce, 1);
        furniture.fillEllipse(p.x, p.y - 57, 18, 12);
        furniture.fillStyle(0xffd48f, 0.18);
        furniture.beginPath();
        furniture.moveTo(p.x, p.y - 52);
        furniture.lineTo(p.x + 38, p.y + 4);
        furniture.lineTo(p.x - 38, p.y + 4);
        furniture.closePath();
        furniture.fillPath();
      });
      furniture.setDepth(95);

      /* ── Plants with colorful pots ───────────────────────── */
      [[1, 0, 0xffd4e5], [9, 0, 0xe8d5f5], [0, 8, 0xd5f5e3], [10, 8, 0xffd7b8], [4, 8, 0xf2d0ff]].forEach(([tx, ty, potColor]) => {
        const pg = this.add.graphics();
        const { x: px, y: py } = iso(tx, ty);
        const POT_H = 13;
        this._box(pg, tx, ty, POT_H, Number(potColor), dk(Number(potColor), 22), dk(Number(potColor), 14));
        pg.fillStyle(0x65c889, 0.95);
        pg.fillCircle(px, py - POT_H - 7, 14);
        pg.fillStyle(0x80dba0, 0.95);
        pg.fillCircle(px - 9, py - POT_H - 1, 9);
        pg.fillCircle(px + 9, py - POT_H - 1, 9);
        pg.fillStyle(0x99e6b3, 0.9);
        pg.fillCircle(px, py - POT_H - 17, 8);
        pg.fillStyle(0xffffff, 0.45);
        pg.fillCircle(px - 4, py - POT_H - 11, 2);
        pg.setDepth(py + TH + 24);
      });

      // Warm ambient spots near center
      const glow = this.add.graphics();
      glow.fillStyle(0xffd48f, 0.16);
      glow.fillCircle(iso(5, 3).x, iso(5, 3).y + TH + 34, 170);
      glow.fillStyle(0xffc97d, 0.10);
      glow.fillCircle(iso(7, 5).x, iso(7, 5).y + TH + 22, 120);
      glow.fillStyle(0xffe2b4, 0.08);
      glow.fillCircle(iso(2, 6).x, iso(2, 6).y + TH + 16, 95);
      glow.setDepth(2);
    }

    /* ── Procedural pixel-art character ─────────────────────
       Local (0, 0) = feet/shadow centre.
       Draws upward: shadow at y≈0, head at y≈-34.              */
    _drawChar(g, color, state) {
      g.clear();
      const body = dk(color, 32);
      const dark = dk(color, 52);

      // Drop shadow
      g.fillStyle(0x000000, 0.18);
      g.fillEllipse(0, 3, 26, 9);

      // Shoes
      g.fillStyle(0x1a1a1a, 1);
      g.fillRect(-8, -8, 6, 6);
      g.fillRect(2, -8, 6, 6);

      // Legs / trousers
      g.fillStyle(dark, 1);
      g.fillRect(-7, -22, 5, 14);
      g.fillRect(2, -22, 5, 14);

      // Body
      g.fillStyle(body, 1);
      g.fillRect(-9, -38, 18, 18);
      g.fillStyle(color, 0.36);
      g.fillRect(-8, -37, 16, 4);

      // Head
      g.fillStyle(0xf5c89a, 1);
      g.fillRect(-6, -54, 12, 16);

      // Hair / top accent
      g.fillStyle(color, 1);
      g.fillRect(-6, -54, 12, 5);
      g.fillRect(-7, -51, 3, 4);
      g.fillRect(4, -51, 3, 4);

      // Eyes
      g.fillStyle(0x000000, 1);
      g.fillRect(-4, -45, 2, 2);
      g.fillRect(2, -45, 2, 2);

      // Mouth
      g.fillStyle(0xb07060, 1);
      g.fillRect(-2, -40, 4, 1);

      // Arms / hands
      g.fillStyle(body, 1);
      g.fillRect(-14, -35, 5, 12);
      g.fillRect(9, -35, 5, 12);
      g.fillStyle(0xf5c89a, 1);
      g.fillRect(-14, -24, 5, 5);
      g.fillRect(9, -24, 5, 5);

      /* ── State-specific overlays ───────────────────────── */
      if (state === "working") {
        g.fillStyle(0xffe6be, 0.30);
        g.fillRect(-6, -54, 12, 16);
        // Laptop / tablet in hands
        g.fillStyle(0x685d70, 1);
        g.fillRect(-9, -35, 18, 12);
        g.fillStyle(0xb9f0ff, 0.90);
        g.fillRect(-8, -34, 16, 10);
        // Scanlines on tablet
        g.fillStyle(0x000000, 0.12);
        for (let i = 0; i < 4; i++) {
          g.fillRect(-8, -34 + i * 2, 16, 1);
        }
      }

      if (state === "hitl_wait") {
        // Exclamation bubble above head
        g.fillStyle(0xffb14f, 1);
        g.fillRect(8, -62, 4, 11);
        g.fillRect(8, -48, 4, 4);
        // Slight blush
        g.fillStyle(0xff8080, 0.3);
        g.fillRect(-5, -44, 4, 3);
        g.fillRect(1, -44, 4, 3);
      }
    }

    /* ── Spawn one container per agent ───────────────────── */
    _spawnAgents() {
      Object.entries(AGENTS).forEach(([id, cfg]) => {
        const [tx, ty] = cfg.tile;
        const { x: px, y: py } = iso(tx, ty);
        const DESK_H = 20;

        // Container sits at desk level
        const cx = px;
        const cy = py - DESK_H;

        const container = this.add.container(cx, cy);
        container.setScale(1.12);
        container.setDepth(py + TH + 10);

        // Character (local origin = feet at 0,0)
        const charG = this.add.graphics();
        this._drawChar(charG, cfg.color, "idle");
        container.add(charG);

        // Status indicator (larger halo + dot)
        const halo = this.add.circle(20, -62, 11, 0xffffff, 0.18);
        container.add(halo);
        const dot = this.add.circle(20, -62, 7, 0x8ea1bc);
        container.add(dot);

        // Name label
        const hexCol = "#" + cfg.color.toString(16).padStart(6, "0");
        const label = this.add.text(0, -64, cfg.label, {
          fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
          fontSize:   "13px",
          fontStyle:  "bold",
          color:       hexCol,
          stroke:      "#000000",
          strokeThickness: 4,
          shadow: { blur: 6, color: "#000000", fill: true },
        }).setOrigin(0.5, 1);
        container.add(label);

        // Thought bubble (hidden until working)
        const bubbleBg = this.add.rectangle(0, -84, 48, 22, 0xfff3e5, 0.95)
          .setStrokeStyle(1, 0xdabf9d, 1)
          .setVisible(false);
        container.add(bubbleBg);

        const bubbleTxt = this.add.text(0, -84, "...", {
          fontFamily: "monospace",
          fontSize:   "12px",
          color:      "#8d769f",
        }).setOrigin(0.5).setVisible(false);
        container.add(bubbleTxt);

        this.agentViews.set(id, {
          id, tx, ty, cfg,
          container, charG, dot, halo, label,
          bubbleBg, bubbleTxt,
          baseX: cx, baseY: cy,
          state: "idle",
          bobTween: null,
        });
      });
    }

    /* ── State transitions ───────────────────────────────── */
    _stopBob(view) {
      if (view.bobTween) {
        view.bobTween.stop();
        view.bobTween = null;
      }
      view.container.x = view.baseX;
      view.container.y = view.baseY;
    }

    setAgentMode(view, mode) {
      if (view.state === mode) return;
      view.state = mode;

      // Redraw character
      this._drawChar(view.charG, view.cfg.color, mode);

      this._stopBob(view);

      if (mode === "working") {
        view.bobTween = this.tweens.add({
          targets:  view.container,
          y:        view.baseY - 7,
          duration: 500,
          ease:     "Sine.InOut",
          yoyo:     true,
          repeat:   -1,
        });
      } else if (mode === "hitl_wait") {
        // brief shake
        view.bobTween = this.tweens.add({
          targets:  view.container,
          x:        view.baseX + 4,
          duration: 70,
          ease:     "Linear",
          yoyo:     true,
          repeat:   4,
          onComplete: () => {
            if (view.container) view.container.x = view.baseX;
            view.bobTween = null;
          },
        });
      }
    }

    /* ── Sync from window.agentState ─────────────────────── */
    syncAgents(time) {
      const runtime = window.agentState || { agents: [] };
      const agents  = Array.isArray(runtime.agents) ? runtime.agents : [];
      const map     = new Map(agents.map((a) => [a.agent_id, a]));

      this.agentViews.forEach((view, id) => {
        const st  = map.get(id);
        const raw = (st && st.state ? String(st.state) : "idle").toLowerCase();
        const mode =
          raw === "working"   ? "working"   :
          (raw === "hitl_wait" || raw === "hitl" || raw === "waiting")
                              ? "hitl_wait" : "idle";

        this.setAgentMode(view, mode);

        if (mode === "working") {
          const pulse = 0.55 + Math.sin(time / 260) * 0.45;
          view.dot.setFillStyle(0x53e7a2, 1);
          view.halo.setFillStyle(0x53e7a2, 0.18 + pulse * 0.25);
          view.halo.setScale(1 + pulse * 0.22);
          view.bubbleBg.setVisible(true);
          view.bubbleTxt.setVisible(true);
        } else if (mode === "hitl_wait") {
          view.dot.setFillStyle(0xffaf4d, 1);
          view.halo.setFillStyle(0xffaf4d, 0.30);
          view.halo.setScale(1.08);
          view.bubbleBg.setVisible(false);
          view.bubbleTxt.setVisible(false);
        } else {
          view.dot.setFillStyle(0x8ea1bc, 1);
          view.halo.setFillStyle(0xb7c8e8, 0.16);
          view.halo.setScale(1);
          view.bubbleBg.setVisible(false);
          view.bubbleTxt.setVisible(false);
        }
      });
    }

    animateBubbles(time) {
      if (time - this.lastBubbleTick < 500) return;
      this.lastBubbleTick = time;
      this.bubbleIndex = (this.bubbleIndex + 1) % this.bubbleFrames.length;
      const frame = this.bubbleFrames[this.bubbleIndex];
      this.agentViews.forEach((view) => {
        if (view.bubbleTxt.visible) view.bubbleTxt.setText(frame);
      });
    }

    update(time) {
      this.syncAgents(time);
      this.animateBubbles(time);
    }
  }

  window.OfficeScene = OfficeScene;
})();
