(() => {
  /* ── Isometric config ─────────────────────────────────────── */
  const TW = 64;   // tile width (diamond full width)
  const TH = 32;   // tile height (= TW/2)
  const OX = 420;  // origin X (north-tip of tile 0,0)
  const OY = 100;  // origin Y

  /* ── Agent definitions ───────────────────────────────────── */
  const AGENTS = {
    chief_of_staff:     { tile: [2, 1], color: 0xff6b6b, label: "Chief"    },
    fullstack_builder:  { tile: [5, 1], color: 0x64c7ff, label: "Builder"  },
    code_reviewer:      { tile: [8, 1], color: 0x98ff92, label: "Reviewer" },
    security_auditor:   { tile: [2, 5], color: 0xffd166, label: "Security" },
    finance_specialist: { tile: [5, 5], color: 0xd88cff, label: "Finance"  },
    devops_engineer:    { tile: [8, 5], color: 0x76f1d4, label: "DevOps"   },
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

      // Background
      const bg = this.add.graphics();
      bg.fillGradientStyle(0x040c1c, 0x040c1c, 0x091428, 0x091428, 1);
      bg.fillRect(0, 0, W, H);
      bg.setDepth(-200);

      /* ── FLOOR ──────────────────────────────────────────── */
      const floor = this.add.graphics();
      floor.lineStyle(1, 0x0c1e3a, 0.7);
      for (let ty = 0; ty < 9; ty++) {
        for (let tx = 0; tx < 11; tx++) {
          const even = (tx + ty) % 2 === 0;
          this._tile(floor, tx, ty, even ? 0x0e1c38 : 0x132240, 1);
          // tile edge lines
          const { x, y } = iso(tx, ty);
          const hw = TW / 2;
          floor.strokePoints([
            { x,        y       },
            { x: x + hw, y: y + TH / 2 },
            { x,        y: y + TH },
            { x: x - hw, y: y + TH / 2 },
          ], true);
        }
      }
      floor.setDepth(1);

      /* ── BACK WALLS ─────────────────────────────────────── */
      const walls = this.add.graphics();
      walls.lineStyle(1, 0x0a1830, 0.5);
      // North wall (ty = 0 row)
      for (let tx = 0; tx < 11; tx++) {
        this._box(walls, tx, 0, 40, 0x1a2e58, 0x0e1e3c, 0x152244);
      }
      // West wall (tx = 0 col, excluding corner already drawn)
      for (let ty = 1; ty < 9; ty++) {
        this._box(walls, 0, ty, 40, 0x1a2e58, 0x0e1e3c, 0x152244);
      }
      walls.setDepth(4);

      /* ── DESKS (6 agent workstations) ───────────────────── */
      const DESK_TILES = [
        [2, 1], [5, 1], [8, 1],
        [2, 5], [5, 5], [8, 5],
      ];
      const DESK_H = 18;

      DESK_TILES.forEach(([tx, ty]) => {
        const { x, y } = iso(tx, ty);
        const depth = y + TH;

        // Desk body — warm walnut wood
        const dg = this.add.graphics();
        this._box(dg, tx, ty, DESK_H, 0xba7230, 0x7a4618, 0x985c22);
        // Wood grain line on top face
        dg.lineStyle(1, 0xd49848, 0.35);
        dg.beginPath();
        dg.moveTo(x - 6, y - DESK_H + 4);
        dg.lineTo(x + 22, y - DESK_H + 16);
        dg.strokePath();
        dg.setDepth(depth);

        // Monitor
        const mg = this.add.graphics();
        const mx = x + 10;
        const my = y - DESK_H - 16;
        // Bezel
        mg.fillStyle(0x080e1e, 1);
        mg.fillRect(mx - 12, my - 13, 24, 18);
        // Screen glow
        mg.fillStyle(0x0080c8, 0.85);
        mg.fillRect(mx - 10, my - 11, 20, 14);
        // Scanlines
        mg.fillStyle(0x000000, 0.18);
        for (let i = 0; i < 7; i++) {
          mg.fillRect(mx - 10, my - 11 + i * 2, 20, 1);
        }
        // Code lines on screen
        mg.fillStyle(0x00d4ff, 0.65);
        mg.fillRect(mx - 8, my - 9, 14, 1);
        mg.fillRect(mx - 8, my - 6, 10, 1);
        mg.fillRect(mx - 8, my - 3, 12, 1);
        mg.fillStyle(0x44ffaa, 0.5);
        mg.fillRect(mx - 8, my,     7,  1);
        // Stand
        mg.fillStyle(0x222222, 1);
        mg.fillRect(mx - 2, my + 5, 4, 4);
        mg.fillRect(mx - 6, my + 8, 12, 2);
        mg.setDepth(depth + 4);
      });

      /* ── MEETING TABLE (centre of room) ─────────────────── */
      const mtG = this.add.graphics();
      const TABLE_H = 16;
      // Three-tile wide mahogany table
      [[4, 3], [5, 3], [6, 3]].forEach(([tx, ty]) => {
        this._box(mtG, tx, ty, TABLE_H, 0x6e4020, 0x3e2210, 0x562e18);
      });
      const { y: tY } = iso(5, 3);
      mtG.setDepth(tY + TH + 1);

      /* ── CHAIRS around meeting table ─────────────────────── */
      [[3, 2], [5, 2], [7, 2], [3, 4], [5, 4], [7, 4]].forEach(([tx, ty]) => {
        // skip positions occupied by agent desks
        if (DESK_TILES.some(([dx, dy]) => dx === tx && dy === ty)) return;
        const cg = this.add.graphics();
        const { y: cy } = iso(tx, ty);
        this._box(cg, tx, ty, 10, 0x1e3870, 0x12254a, 0x182e5c);
        cg.setDepth(cy + TH);
      });

      /* ── PLANTS ─────────────────────────────────────────── */
      [[1, 0], [9, 0], [0, 8], [10, 8]].forEach(([tx, ty]) => {
        const pg = this.add.graphics();
        const { x: px, y: py } = iso(tx, ty);
        const POT_H = 12;
        // Terracotta pot
        this._box(pg, tx, ty, POT_H, 0x7a3412, 0x4e2009, 0x622a10);
        // Foliage
        pg.fillStyle(0x1e8040, 1);
        pg.fillCircle(px, py - POT_H - 6, 13);
        pg.fillStyle(0x28a050, 1);
        pg.fillCircle(px - 9,  py - POT_H - 2,  9);
        pg.fillCircle(px + 9,  py - POT_H - 2,  9);
        pg.fillStyle(0x34c060, 0.8);
        pg.fillCircle(px,      py - POT_H - 16, 8);
        pg.setDepth(py + TH + 20);
      });

      /* ── AMBIENT GLOW SPOTS ──────────────────────────────── */
      const glow = this.add.graphics();
      // Soft spotlight under meeting table area
      glow.fillStyle(0x2040a0, 0.06);
      glow.fillCircle(iso(5, 3).x, iso(5, 3).y + TH + 40, 120);
      glow.setDepth(2);
    }

    /* ── Procedural pixel-art character ─────────────────────
       Local (0, 0) = feet/shadow centre.
       Draws upward: shadow at y≈0, head at y≈-34.              */
    _drawChar(g, color, state) {
      g.clear();
      const body = dk(color, 42);
      const dark = dk(color, 62);

      // Drop shadow
      g.fillStyle(0x000000, 0.22);
      g.fillEllipse(0, 2, 20, 7);

      // Shoes
      g.fillStyle(0x1a1a1a, 1);
      g.fillRect(-6, -6,  5, 5);
      g.fillRect( 1, -6,  5, 5);

      // Legs / trousers
      g.fillStyle(dark, 1);
      g.fillRect(-5, -15, 4, 9);
      g.fillRect( 1, -15, 4, 9);

      // Body
      g.fillStyle(body, 1);
      g.fillRect(-6, -25, 12, 12);

      // Collar highlight
      g.fillStyle(color, 0.35);
      g.fillRect(-5, -25, 10, 2);

      // Head (skin)
      g.fillStyle(0xf5c89a, 1);
      g.fillRect(-4, -35, 8, 12);

      // Hair / hat band in agent colour
      g.fillStyle(color, 1);
      g.fillRect(-4, -35, 8,  4);
      g.fillRect(-5, -33, 2,  3);
      g.fillRect( 3, -33, 2,  3);

      // Eyes
      g.fillStyle(0x000000, 1);
      g.fillRect(-3, -29, 2, 2);
      g.fillRect( 1, -29, 2, 2);

      // Mouth
      g.fillStyle(0xb07060, 1);
      g.fillRect(-1, -25, 3, 1);

      // Arms / hands
      g.fillStyle(body, 1);
      g.fillRect(-10, -23, 4, 9);
      g.fillRect(  6, -23, 4, 9);
      g.fillStyle(0xf5c89a, 1);
      g.fillRect(-10, -15, 4, 4);
      g.fillRect(  6, -15, 4, 4);

      /* ── State-specific overlays ───────────────────────── */
      if (state === "working") {
        // Screen glow reflected on face
        g.fillStyle(0x7de8ff, 0.28);
        g.fillRect(-4, -35, 8, 12);
        // Laptop / tablet in hands
        g.fillStyle(0x0a1522, 1);
        g.fillRect(-6, -24, 12, 9);
        g.fillStyle(0x28b8f0, 0.85);
        g.fillRect(-5, -23, 10, 7);
        // Scanlines on tablet
        g.fillStyle(0x000000, 0.12);
        for (let i = 0; i < 3; i++) {
          g.fillRect(-5, -23 + i * 2, 10, 1);
        }
      }

      if (state === "hitl_wait") {
        // Exclamation bubble above head
        g.fillStyle(0xffd166, 1);
        g.fillRect(5, -44, 3, 7);
        g.fillRect(5, -34, 3, 3);
        // Slight blush
        g.fillStyle(0xff8080, 0.3);
        g.fillRect(-4, -28, 3, 3);
        g.fillRect( 1, -28, 3, 3);
      }
    }

    /* ── Spawn one container per agent ───────────────────── */
    _spawnAgents() {
      Object.entries(AGENTS).forEach(([id, cfg]) => {
        const [tx, ty] = cfg.tile;
        const { x: px, y: py } = iso(tx, ty);
        const DESK_H = 18;

        // Container sits at desk level
        const cx = px;
        const cy = py - DESK_H;

        const container = this.add.container(cx, cy);
        container.setDepth(py + TH + 10);

        // Character (local origin = feet at 0,0)
        const charG = this.add.graphics();
        this._drawChar(charG, cfg.color, "idle");
        container.add(charG);

        // Status dot (top-right of character)
        const dot = this.add.circle(13, -42, 5, 0x667280);
        container.add(dot);

        // Name label
        const hexCol = "#" + cfg.color.toString(16).padStart(6, "0");
        const label = this.add.text(0, -50, cfg.label, {
          fontFamily: "'Courier New', Courier, monospace",
          fontSize:   "13px",
          fontStyle:  "bold",
          color:       hexCol,
          stroke:      "#000000",
          strokeThickness: 4,
          shadow: { blur: 6, color: "#000000", fill: true },
        }).setOrigin(0.5, 1);
        container.add(label);

        // Thought bubble (hidden until working)
        const bubbleBg = this.add.rectangle(0, -66, 40, 20, 0x0c1a34, 0.95)
          .setStrokeStyle(1, 0x2a4878, 1)
          .setVisible(false);
        container.add(bubbleBg);

        const bubbleTxt = this.add.text(0, -66, "...", {
          fontFamily: "monospace",
          fontSize:   "11px",
          color:      "#8ab8ff",
        }).setOrigin(0.5).setVisible(false);
        container.add(bubbleTxt);

        this.agentViews.set(id, {
          id, tx, ty, cfg,
          container, charG, dot, label,
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
          y:        view.baseY - 5,
          duration: 500,
          ease:     "Sine.InOut",
          yoyo:     true,
          repeat:   -1,
        });
      } else if (mode === "hitl_wait") {
        // brief shake
        view.bobTween = this.tweens.add({
          targets:  view.container,
          x:        view.baseX + 3,
          duration: 70,
          ease:     "Linear",
          yoyo:     true,
          repeat:   3,
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
          const pulse = 0.55 + Math.sin(time / 300) * 0.45;
          view.dot.setFillStyle(0x44df7c, pulse);
          view.bubbleBg.setVisible(true);
          view.bubbleTxt.setVisible(true);
        } else if (mode === "hitl_wait") {
          view.dot.setFillStyle(0xffd166, 1);
          view.bubbleBg.setVisible(false);
          view.bubbleTxt.setVisible(false);
        } else {
          view.dot.setFillStyle(0x667280, 1);
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
