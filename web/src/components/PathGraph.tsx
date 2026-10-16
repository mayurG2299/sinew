import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";

cytoscape.use(dagre);

const KIND: [RegExp, string, string][] = [
  [/^cu-/, "customer", "#0f766e"], [/^pf-/, "profile", "#5eead4"], [/^o-/, "order", "#78716c"],
  [/^sh-/, "shipment", "#a8a29e"], [/^hub-/, "hub", "#b45309"], [/^t-/, "ticket", "#be123c"],
  [/^dec-/, "decision", "#4338ca"], [/^as-/, "assumption", "#7c3aed"], [/^u-/, "person", "#57534e"],
  [/^team-/, "team", "#57534e"], [/^(fest|winter)/, "campaign", "#c2410c"], [/^courier-/, "courier", "#b45309"],
];

function style(id: string): [string, string] {
  for (const [re, kind, color] of KIND) if (re.test(id)) return [kind, color];
  return ["", "#a8a29e"];
}

export function PathGraph({ paths, height = 320, highlight = [] }: { paths: string[][]; height?: number; highlight?: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const nodes = new Map<string, any>();
    const edges = new Map<string, any>();
    for (const p of paths) {
      const clean = p.filter((x) => x && !x.includes(" "));
      clean.forEach((id) => {
        const [kind, color] = style(id);
        nodes.set(id, { data: { id, label: id, kind, color, hl: highlight.includes(id) ? 1 : 0 } });
      });
      for (let i = 0; i + 1 < clean.length; i++) {
        const key = `${clean[i]}>${clean[i + 1]}`;
        if (clean[i] !== clean[i + 1]) edges.set(key, { data: { id: key, source: clean[i], target: clean[i + 1] } });
      }
    }
    const cy = cytoscape({
      container: ref.current,
      elements: [...nodes.values(), ...edges.values()],
      layout: { name: "dagre", rankDir: "LR", nodeSep: 12, rankSep: 60 } as any,
      style: [
        { selector: "node", style: { "background-color": "data(color)", label: "data(label)", "font-size": 9, color: "#44403c", "text-valign": "bottom", "text-margin-y": 4, width: 14, height: 14 } },
        { selector: "node[hl = 1]", style: { width: 22, height: 22, "border-width": 3, "border-color": "#fbbf24" } },
        { selector: "edge", style: { width: 1.2, "line-color": "#d6d3d1", "target-arrow-color": "#d6d3d1", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.7 } },
      ],
      userZoomingEnabled: true, wheelSensitivity: 0.2,
    });
    return () => cy.destroy();
  }, [JSON.stringify(paths), highlight.join()]);
  return <div ref={ref} style={{ height }} className="w-full rounded-lg border border-stone-100 bg-stone-50/50" />;
}
