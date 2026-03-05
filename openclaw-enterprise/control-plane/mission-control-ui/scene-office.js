(() => {
  /* ── Isometric config ─────────────────────────────────────── */
  const TW = 64;   // tile width (diamond full width)
  const TH = 32;   // tile height (= TW/2)
  const OX = 420;  // origin X (north-tip of tile 0,0)
  const OY = 100;  // origin Y

  /* ── Agent definitions ───────────────────────────────────── */
  const AGENTS = {
    chief_of_staff:   { tile: [2, 1], color: 0xff7d5f, label: "🧠 Chief" },
    developer:        { tile: [5, 1], color: 0x3cc9ff, label: "🛠️ Dev" },
    code_reviewer:    { tile: [8, 1], color: 0x9cfa6b, label: "🧪 Review" },
    security_agent:   { tile: [2, 5], color: 0xffc857, label: "🛡️ Security" },
    financial_analyst:{ tile: [5, 5], color: 0xc59dff, label: "💸 Analyst" },
    financial_parser: { tile: [8, 5], color: 0x49e1b8, label: "📊 Parser" },
  };

  const AGENT_ALIASES = {
    chief_of_staff: ["chief_of_staff"],
    developer: ["developer", "fullstack_builder"],
    code_reviewer: ["code_reviewer"],
    security_agent: ["security_agent", "security_auditor"],
    financial_analyst: ["financial_analyst", "finance_specialist"],
    financial_parser: ["financial_parser", "devops_engineer"],
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

      // Background with warm dusk gradient
      const bg = this.add.graphics();
      bg.fillGradientStyle(0x2e1a10, 0x2e1a10, 0x150d08, 0x150d08, 1);
      bg.fillRect(0, 0, W, H);
      bg.fillStyle(0xffb36b, 0.12);
      bg.fillCircle(W * 0.18, H * 0.1, 180);
      bg.fillStyle(0xffa65a, 0.08);
      bg.fillCircle(W * 0.78, H * 0.15, 220);
      bg.setDepth(-200);

      /* ── FLOOR ──────────────────────────────────────────── */
      const floor = this.add.graphics();
      floor.lineStyle(1, 0x51311d, 0.32);
      for (let ty = 0; ty < 9; ty++) {
        for (let tx = 0; tx < 11; tx++) {
          const even = (tx + ty) % 2 === 0;
          this._tile(floor, tx, ty, even ? 0x72472b : 0x66402a, 1);
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

      // Central rug for extra depth cue
      const rug = this.add.graphics();
      [[3, 2], [4, 2], [5, 2], [6, 2], [7, 2], [3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [3, 4], [4, 4], [5, 4], [6, 4], [7, 4]].forEach(([tx, ty]) => {
        this._tile(rug, tx, ty, 0x8b5230, 0.42);
      });
      rug.setDepth(2);

      /* ── BACK WALLS + WINDOWS ───────────────────────────── */
      const walls = this.add.graphics();
      walls.lineStyle(1, 0x3a2315, 0.55);
      // North wall (ty = 0 row)
      for (let tx = 0; tx < 11; tx++) {
        this._box(walls, tx, 0, 44, 0xaf7350, 0x7b4b32, 0x925939);
      }
      // West wall (tx = 0 col, excluding corner already drawn)
      for (let ty = 1; ty < 9; ty++) {
        this._box(walls, 0, ty, 44, 0xaf7350, 0x7b4b32, 0x925939);
      }
      walls.setDepth(4);

      const windows = this.add.graphics();
      windows.fillStyle(0xffd8a7, 0.2);
      windows.fillRect(iso(4, 0).x - 100, iso(4, 0).y - 30, 210, 22);
      windows.fillStyle(0xffcb8d, 0.12);
      windows.fillRect(iso(4, 0).x - 95, iso(4, 0).y - 18, 200, 16);
      windows.setDepth(40);

      /* ── DESKS (6 agent workstations) ───────────────────── */
      const DESK_TILES = [
        [2, 1], [5, 1], [8, 1],
        [2, 5], [5, 5], [8, 5],
      ];
      const DESK_H = 20;

      DESK_TILES.forEach(([tx, ty]) => {
        const { x, y } = iso(tx, ty);
        const depth = y + TH;

        // Desk shadow
        const sg = this.add.graphics();
        sg.fillStyle(0x000000, 0.18);
        sg.fillEllipse(x + 4, y + TH + 6, 50, 16);
        sg.setDepth(depth - 0.5);

        // Desk body — walnut wood
        const dg = this.add.graphics();
        this._box(dg, tx, ty, DESK_H, 0xc57a43, 0x7f4a23, 0x9d5e2e);
        // Wood grain line on top face
        dg.lineStyle(1, 0xe7b47a, 0.35);
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
        mg.fillStyle(0x160f0e, 1);
        mg.fillRect(mx - 12, my - 13, 24, 18);
        // Screen glow
        mg.fillStyle(0xffb560, 0.85);
        mg.fillRect(mx - 10, my - 11, 20, 14);
        // Scanlines
        mg.fillStyle(0x000000, 0.18);
        for (let i = 0; i < 7; i++) {
          mg.fillRect(mx - 10, my - 11 + i * 2, 20, 1);
        }
        // Code lines on screen
        mg.fillStyle(0xfff1cb, 0.65);
        mg.fillRect(mx - 8, my - 9, 14, 1);
        mg.fillRect(mx - 8, my - 6, 10, 1);
        mg.fillRect(mx - 8, my - 3, 12, 1);
        mg.fillStyle(0xffdf9e, 0.5);
        mg.fillRect(mx - 8, my,     7,  1);
        // Stand
        mg.fillStyle(0x2f2623, 1);
        mg.fillRect(mx - 2, my + 5, 4, 4);
        mg.fillRect(mx - 6, my + 8, 12, 2);
        // Keyboard
        mg.fillStyle(0x4f2f1f, 1);
        mg.fillRect(mx - 13, my + 10, 15, 4);
        // Mug
        mg.fillStyle(0xffd6ab, 1);
        mg.fillCircle(mx + 9, my + 9, 3);
        mg.lineStyle(1, 0x915938, 1);
        mg.strokeCircle(mx + 12, my + 9, 1.8);
        mg.setDepth(depth + 4);

        // Desk lamp beam
        const lg = this.add.graphics();
        lg.fillStyle(0xffd18f, 0.14);
        lg.beginPath();
        lg.moveTo(mx - 18, my - 4);
        lg.lineTo(mx - 2, my + 24);
        lg.lineTo(mx - 30, my + 24);
        lg.closePath();
        lg.fillPath();
        lg.setDepth(depth + 2);
      });

      /* ── MEETING TABLE (centre of room) ─────────────────── */
      const mtG = this.add.graphics();
      const TABLE_H = 16;
      // Four-tile wide conference table
      [[4, 3], [5, 3], [6, 3], [7, 3]].forEach(([tx, ty]) => {
        this._box(mtG, tx, ty, TABLE_H, 0x9a5d35, 0x5f351d, 0x7c4728);
      });
      const { y: tY } = iso(5, 3);
      mtG.setDepth(tY + TH + 1);

      /* ── CHAIRS around meeting table ─────────────────────── */
      [[3, 2], [5, 2], [7, 2], [3, 4], [5, 4], [7, 4], [8, 3]].forEach(([tx, ty]) => {
        // skip positions occupied by agent desks
        if (DESK_TILES.some(([dx, dy]) => dx === tx && dy === ty)) return;
        const cg = this.add.graphics();
        const { y: cy } = iso(tx, ty);
        this._box(cg, tx, ty, 12, 0xcd834a, 0x7f4a2b, 0x9a5c34);
        this._box(cg, tx, ty, 22, 0xb26b3d, 0x6e3f23, 0x894f2e);
        cg.setDepth(cy + TH);
      });

      /* ── BOOKSHELVES + SERVER UNIT ─────────────────────── */
      [[10, 2], [10, 3], [10, 4]].forEach(([tx, ty]) => {
        const sh = this.add.graphics();
        const { x, y } = iso(tx, ty);
        this._box(sh, tx, ty, 46, 0x8b5633, 0x5d381f, 0x734526);
        sh.fillStyle(0xffd7ac, 0.7);
        sh.fillRect(x - 12, y - 40, 24, 2);
        sh.fillRect(x - 12, y - 33, 24, 2);
        sh.fillRect(x - 12, y - 26, 24, 2);
        sh.setDepth(y + 70);
      });
      const server = this.add.graphics();
      const sPos = iso(9, 7);
      this._box(server, 9, 7, 40, 0x4b3529, 0x2e221b, 0x3a2a21);
      server.fillStyle(0x6efdb3, 0.8);
      server.fillRect(sPos.x - 10, sPos.y - 34, 20, 3);
      server.fillRect(sPos.x - 10, sPos.y - 26, 16, 2);
      server.fillStyle(0xffbf6a, 0.8);
      server.fillRect(sPos.x - 10, sPos.y - 20, 10, 2);
      server.setDepth(sPos.y + 70);

      /* ── LOUNGE SOFA ─────────────────────────────────────── */
      const sofa = this.add.graphics();
      [[1, 7], [2, 7], [3, 7]].forEach(([tx, ty]) => this._box(sofa, tx, ty, 14, 0xa75f37, 0x6b3a22, 0x844b2a));
      [[1, 8], [2, 8], [3, 8]].forEach(([tx, ty]) => this._box(sofa, tx, ty, 24, 0x8f5030, 0x5a311d, 0x713f25));
      sofa.setDepth(iso(2, 8).y + 68);

      /* ── PLANTS ─────────────────────────────────────────── */
      [[1, 0], [9, 0], [0, 8], [10, 8]].forEach(([tx, ty]) => {
        const pg = this.add.graphics();
        const { x: px, y: py } = iso(tx, ty);
        const POT_H = 12;
        // Terracotta pot
        this._box(pg, tx, ty, POT_H, 0x7a3412, 0x4e2009, 0x622a10);
        // Foliage
        pg.fillStyle(0x2e8f50, 1);
        pg.fillCircle(px, py - POT_H - 6, 13);
        pg.fillStyle(0x39aa5d, 1);
        pg.fillCircle(px - 9,  py - POT_H - 2,  9);
        pg.fillCircle(px + 9,  py - POT_H - 2,  9);
        pg.fillStyle(0x55c978, 0.8);
        pg.fillCircle(px,      py - POT_H - 16, 8);
        pg.setDepth(py + TH + 20);
      });

      /* ── PENDANT LIGHTS + AMBIENT GLOW ───────────────────── */
      const pendants = this.add.graphics();
      [[4, 1], [7, 1], [5, 4]].forEach(([tx, ty]) => {
        const p = iso(tx, ty);
        pendants.lineStyle(1, 0x3c2718, 0.8);
        pendants.beginPath();
        pendants.moveTo(p.x, p.y - 80);
        pendants.lineTo(p.x, p.y - 28);
        pendants.strokePath();
        pendants.fillStyle(0xffce96, 0.95);
        pendants.fillCircle(p.x, p.y - 24, 5);
        pendants.fillStyle(0xffcb7a, 0.13);
        pendants.beginPath();
        pendants.moveTo(p.x, p.y - 20);
        pendants.lineTo(p.x + 50, p.y + 30);
        pendants.lineTo(p.x - 50, p.y + 30);
        pendants.closePath();
        pendants.fillPath();
      });
      pendants.setDepth(90);

      const glow = this.add.graphics();
      glow.fillStyle(0xffb46b, 0.08);
      glow.fillCircle(iso(5, 3).x, iso(5, 3).y + TH + 40, 160);
      glow.fillStyle(0xffcc88, 0.06);
      glow.fillCircle(iso(7, 4).x, iso(7, 4).y + TH + 30, 110);
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
        g.fillStyle(0xffd39a, 0.28);
        g.fillRect(-4, -35, 8, 12);
        // Laptop / tablet in hands
        g.fillStyle(0x20140f, 1);
        g.fillRect(-6, -24, 12, 9);
        g.fillStyle(0xffb56b, 0.85);
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
          fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
          fontSize:   "12px",
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
          color:      "#ffd39a",
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
        const aliases = AGENT_ALIASES[id] || [id];
        const st = aliases.map((alias) => map.get(alias)).find(Boolean);
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
