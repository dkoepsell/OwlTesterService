/* Coverage Coherence Checker — page behavior.
 *
 * One button runs the coherence check for every snippet on the page, then the
 * verdict areas, taxonomy, and portfolio panels reveal in the run-of-show order.
 * The diagram is a fixed-layout SVG (no physics): definition top, grant left,
 * exclusion right, carveback bottom; only the contradiction wears color.
 */
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("demo-data").textContent);
  const SVGNS = "http://www.w3.org/2000/svg";
  const tooltip = document.getElementById("viz-tooltip");

  // ---- clause-structure diagram --------------------------------------------

  const NODE_POS = { definition: [210, 42], grant: [82, 152], exclusion: [338, 152], carveback: [210, 262] };
  const NODE_W = 132, NODE_H = 46;

  function svgEl(tag, attrs, text) {
    const el = document.createElementNS(SVGNS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text) el.textContent = text;
    return el;
  }

  function edgePath(a, b, shrink) {
    // Straight edge between node centers, shortened so it meets the boxes.
    const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
    const ux = dx / len, uy = dy / len;
    return { x1: a[0] + ux * shrink, y1: a[1] + uy * shrink,
             x2: b[0] - ux * shrink, y2: b[1] - uy * shrink };
  }

  function nodePos(clause) {
    return clause.pos || NODE_POS[clause.role] || [210, 152];
  }

  function buildDiagram(fix) {
    const svg = document.querySelector(`#verdict-${fix.id} .clause-diagram`);
    if (!svg) return;
    const byRole = {}, byId = {};
    fix.clauses.forEach((c) => { byRole[c.role] = c; byId[c.id] = c; });

    // A fixture may declare its own structure edges (needed when a role occurs
    // more than once); otherwise fall back to role logic: the exclusion limits
    // the grant, the carveback restores from the exclusion, the definition
    // feeds both.
    let edges;
    if (fix.edges) {
      edges = fix.edges.map((e) => [byId[e.from], byId[e.to], e.label])
                       .filter(([a, b]) => a && b);
    } else {
      edges = [];
      if (byRole.exclusion && byRole.grant) edges.push([byRole.exclusion, byRole.grant, "limits"]);
      if (byRole.carveback && byRole.exclusion) edges.push([byRole.carveback, byRole.exclusion, "restores from"]);
      if (byRole.definition && byRole.exclusion) edges.push([byRole.definition, byRole.exclusion, "defines term in"]);
      if (byRole.definition && byRole.carveback) edges.push([byRole.definition, byRole.carveback, "defines term in"]);
    }

    edges.forEach(([from, to, label]) => {
      const p = edgePath(nodePos(from), nodePos(to), 44);
      const line = svgEl("line", { class: "diag-edge", x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2,
                                   "data-edge": `${from.id}-${to.id}` });
      svg.appendChild(line);
      const tx = (p.x1 + p.x2) / 2, ty = (p.y1 + p.y2) / 2 - 5;
      svg.appendChild(svgEl("text", { class: "diag-edge-label", x: tx, y: ty,
                                      "text-anchor": "middle" }, label));
    });

    fix.clauses.forEach((c) => {
      const [cx, cy] = nodePos(c);
      const g = svgEl("g", { class: "diag-node", "data-node-id": c.id, cursor: "pointer" });
      g.appendChild(svgEl("rect", { x: cx - NODE_W / 2, y: cy - NODE_H / 2,
                                    width: NODE_W, height: NODE_H, rx: 6 }));
      g.appendChild(svgEl("text", { x: cx, y: cy - 3, "text-anchor": "middle" },
                          `${c.id} · ${c.heading.split("—")[0].trim()}`));
      g.appendChild(svgEl("text", { class: "role", x: cx, y: cy + 13, "text-anchor": "middle" },
                          c.role.toUpperCase()));
      g.addEventListener("click", () => pulseClause(fix.id, c.id));
      svg.appendChild(g);
    });
  }

  function pulseClause(fixtureId, clauseId) {
    const card = document.getElementById(`card-${fixtureId}`);
    const block = card.querySelector(`.clause[data-clause-id="${clauseId}"]`);
    const node = card.querySelector(`.diag-node[data-node-id="${clauseId}"]`);
    [block, node].forEach((el) => {
      if (!el) return;
      el.classList.remove("pulse");
      void el.getBoundingClientRect(); // restart the animation
      el.classList.add("pulse");
    });
  }

  // ---- verdict rendering ----------------------------------------------------

  function chipify(text, clauseIds) {
    // Wrap clause ids mentioned in prose with highlight chips.
    let safe = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    clauseIds.forEach((id) => {
      safe = safe.replace(new RegExp(`\\b${id}\\b`, "g"), `<span class="chip-inline">${id}</span>`);
    });
    return safe;
  }

  function renderVerdict(fix, verdict) {
    const area = document.getElementById(`verdict-${fix.id}`);
    const banner = area.querySelector(".verdict-banner");
    const why = area.querySelector(".why-text");
    const card = document.getElementById(`card-${fix.id}`);
    const contra = (verdict.checked_positions[0] || {}).contradicting_clauses || [];

    if (verdict.coherent) {
      banner.innerHTML =
        `<div class="alert alert-success py-2 mb-0">
           <i class="fa-solid fa-circle-check icon me-2"></i>
           <strong>COHERENT</strong> — ${verdict.headline}
           ${verdict.scenario ? `<div class="small mt-1">${verdict.scenario}</div>` : ""}
         </div>`;
    } else {
      banner.innerHTML =
        `<div class="alert alert-danger py-2 mb-0">
           <i class="fa-solid fa-triangle-exclamation icon me-2"></i>
           <strong>INCOHERENT</strong> — ${verdict.headline}
         </div>`;
    }
    why.innerHTML = chipify(verdict.plain_english_why || "", contra);

    contra.forEach((id) => {
      const block = card.querySelector(`.clause[data-clause-id="${id}"]`);
      if (block) block.classList.add("contra");
      const node = card.querySelector(`.diag-node[data-node-id="${id}"]`);
      if (node) node.classList.add("contra");
    });
    // An edge is part of the finding when both of its ends are.
    card.querySelectorAll(".diag-edge").forEach((edge) => {
      const [a, b] = edge.getAttribute("data-edge").split("-");
      if (contra.includes(a) && contra.includes(b)) edge.classList.add("contra");
    });

    const dbg = area.querySelector(".debug-panel pre");
    if (dbg) dbg.textContent = JSON.stringify(verdict, null, 2);
    area.classList.remove("reveal-hidden");
  }

  async function checkAll() {
    const btn = document.getElementById("check-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Checking…';
    const qs = DATA.debug ? "?debug=1" : "";
    for (const fix of DATA.fixtures) {
      try {
        const res = await fetch(`/api/coverage/check/${fix.id}${qs}`, { method: "POST" });
        if (res.ok) renderVerdict(fix, await res.json());
      } catch (e) { /* one failed card must not kill the demo */ }
    }
    btn.innerHTML = '<i class="fa-solid fa-scale-balanced me-2"></i>Checked';
    document.getElementById("panel-taxonomy").classList.remove("reveal-hidden");
    const portfolio = document.getElementById("panel-portfolio");
    if (portfolio) portfolio.classList.remove("reveal-hidden");
  }

  // ---- paste box ------------------------------------------------------------

  function wirePasteBox() {
    const input = document.getElementById("paste-input");
    input.addEventListener("input", () => {
      document.getElementById("paste-note").classList.toggle("reveal-hidden", !input.value.trim());
    });
    const select = document.getElementById("preset-select");
    fetch("/api/coverage/fixtures").then((r) => r.json()).then((d) => {
      d.fixtures.forEach((f) => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.textContent = `${f.title} (${f.line_of_business})`;
        select.appendChild(opt);
      });
    });
    select.addEventListener("change", () => {
      const card = document.getElementById(`card-${select.value}`);
      if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.querySelectorAll(".clause").forEach((c) => c.classList.add("pulse"));
        setTimeout(() => card.querySelectorAll(".clause.pulse")
          .forEach((c) => c.classList.remove("pulse")), 3000);
      }
    });
  }

  // ---- portfolio scatter ----------------------------------------------------

  const TAIL_THRESHOLD = 35;

  function showTooltip(evt, html) {
    tooltip.innerHTML = html;
    tooltip.style.display = "block";
    tooltip.style.left = `${evt.clientX + 14}px`;
    tooltip.style.top = `${evt.clientY - 10}px`;
  }
  function hideTooltip() { tooltip.style.display = "none"; }

  function renderPortfolio() {
    if (!DATA.portfolio) return;
    const svg = document.getElementById("portfolio-chart");
    if (!svg) return;
    const W = 960, H = 360, m = { top: 34, right: 24, bottom: 44, left: 56 };
    const points = DATA.portfolio.points.slice().sort((a, b) => a.cd - b.cd);
    const yMax = Math.ceil(Math.max(...points.map((p) => p.cd)) / 10) * 10;
    const x = (i) => m.left + (i / (points.length - 1)) * (W - m.left - m.right);
    const y = (v) => H - m.bottom - (v / yMax) * (H - m.top - m.bottom);

    // Horizontal hairline grid + y ticks.
    for (let v = 0; v <= yMax; v += 20) {
      svg.appendChild(svgEl("line", { class: "grid", x1: m.left, y1: y(v), x2: W - m.right, y2: y(v) }));
      svg.appendChild(svgEl("text", { class: "tick-label", x: m.left - 8, y: y(v) + 4,
                                      "text-anchor": "end" }, String(v)));
    }
    svg.appendChild(svgEl("text", { class: "axis-label", x: m.left, y: 16 },
                          DATA.portfolio.metric || "Contradiction Debt"));
    svg.appendChild(svgEl("text", { class: "axis-label", x: (m.left + W - m.right) / 2,
                                    y: H - 10, "text-anchor": "middle" },
                          "Policies, ranked by Contradiction Debt"));
    // Honesty label, on the chart itself.
    svg.appendChild(svgEl("text", { class: "synthetic-label", x: W - m.right, y: 16,
                                    "text-anchor": "end" },
                          DATA.portfolio.label || "Illustrative portfolio — synthetic data"));

    // The exception register: dashed ring around the high-CD tail, annotated.
    const tail = points.filter((p) => p.cd > TAIL_THRESHOLD);
    if (tail.length) {
      const firstIdx = points.length - tail.length;
      const cx = (x(firstIdx) + x(points.length - 1)) / 2;
      const minY = y(Math.max(...tail.map((p) => p.cd))), maxY = y(TAIL_THRESHOLD);
      const cy = (minY + maxY) / 2;
      svg.appendChild(svgEl("ellipse", { cx, cy, rx: (x(points.length - 1) - x(firstIdx)) / 2 + 18,
                                         ry: (maxY - minY) / 2 + 16, fill: "none",
                                         stroke: "var(--demo-critical)", "stroke-width": 1.5,
                                         "stroke-dasharray": "5 4" }));
      const ax = cx - (x(points.length - 1) - x(firstIdx)) / 2 - 30;
      svg.appendChild(svgEl("text", { class: "annotation", x: ax, y: cy - 6, "text-anchor": "end" },
                            "the exception register —"));
      svg.appendChild(svgEl("text", { class: "annotation", x: ax, y: cy + 10, "text-anchor": "end" },
                            "litigation exposure concentrates here"));
    }

    points.forEach((p, i) => {
      const inTail = p.cd > TAIL_THRESHOLD;
      const dot = svgEl("circle", { cx: x(i), cy: y(p.cd), r: 4,
                                    fill: inTail ? "var(--demo-critical)" : "var(--demo-series)",
                                    "fill-opacity": inTail ? "0.95" : "0.65" });
      // Oversized invisible hit target for the hover layer.
      const hit = svgEl("circle", { cx: x(i), cy: y(p.cd), r: 10, fill: "transparent" });
      hit.addEventListener("mousemove", (evt) =>
        showTooltip(evt, `<strong>${p.id}</strong> · ${p.lob}<br>Contradiction Debt: ${p.cd}`));
      hit.addEventListener("mouseleave", hideTooltip);
      svg.appendChild(dot);
      svg.appendChild(hit);
    });
  }

  // ---- boot -------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", () => {
    DATA.fixtures.forEach(buildDiagram);
    DATA.fixtures.forEach((fix) => {
      document.querySelectorAll(`#card-${fix.id} .clause`).forEach((block) => {
        block.addEventListener("click", () => pulseClause(fix.id, block.dataset.clauseId));
      });
    });
    document.getElementById("check-btn").addEventListener("click", checkAll);
    wirePasteBox();
    renderPortfolio();
  });
})();
