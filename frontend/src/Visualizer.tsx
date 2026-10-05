import { useEffect, useRef } from "react";
export function Visualizer({
  input,
  output,
  state,
  expanded,
}: {
  input: AnalyserNode | null;
  output: AnalyserNode | null;
  state: string;
  expanded: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current!,
      ctx = element.getContext("2d")!;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0,
      last = 0;
    const bins = new Uint8Array(128);
    const render = (time: number) => {
      frame = requestAnimationFrame(render);
      if (time - last < (reduced.matches ? 200 : 33)) return;
      last = time;
      const size = element.getBoundingClientRect();
      const dpr = Math.min(devicePixelRatio, 2);
      if (
        element.width !== Math.round(size.width * dpr) ||
        element.height !== Math.round(size.height * dpr)
      ) {
        element.width = size.width * dpr;
        element.height = size.height * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.width, size.height);
      const x = size.width / 2,
        y = size.height / 2,
        r = Math.min(size.width, size.height) * (expanded ? 0.24 : 0.27);
      bins.fill(0);
      const source =
        state === "speaking" ? output : state === "listening" ? input : null;
      source?.getByteFrequencyData(bins);
      const amplitude = bins.reduce((a, b) => a + b, 0) / (bins.length * 255);
      const glow = ctx.createRadialGradient(x, y, r * 0.1, x, y, r * 1.6);
      glow.addColorStop(0, `rgba(145,232,186,${0.035 + amplitude * 0.18})`);
      glow.addColorStop(1, "rgba(145,232,186,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size.width, size.height);
      const ink = state === "error" ? "239,140,118" : "152,228,188";
      for (let ring = 0; ring < 3; ring++) {
        ctx.strokeStyle = `rgba(${ink},${0.11 + ring * 0.045})`;
        ctx.lineWidth = ring === 1 ? 1.5 : 0.6;
        ctx.beginPath();
        ctx.ellipse(
          x,
          y,
          r * (1 + ring * 0.17),
          r * (1 + ring * 0.17) * (ring === 1 ? 0.96 : 1),
          0,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
      }
      for (let i = 0; i < 128; i++) {
        const angle = (i / 128) * Math.PI * 2 - Math.PI / 2,
          energy = (bins[i] || 0) / 255;
        const inner = r * 1.43;
        const length =
          (i % 8 === 0 ? 8 : 3) + (reduced.matches ? 0 : energy * r * 0.5);
        ctx.strokeStyle = `rgba(${ink},${0.2 + energy * 0.65})`;
        ctx.lineWidth = i % 8 === 0 ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(x + Math.cos(angle) * inner, y + Math.sin(angle) * inner);
        ctx.lineTo(
          x + Math.cos(angle) * (inner + length),
          y + Math.sin(angle) * (inner + length),
        );
        ctx.stroke();
      }
      // A continuous contour uses genuine frequency data, static when audio is silent.
      ctx.strokeStyle = `rgba(${ink},.72)`;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let i = 0; i <= 128; i++) {
        const angle = (i / 128) * Math.PI * 2;
        const energy = (bins[i % 128] || 0) / 255;
        const radial = r * (0.8 + energy * 0.25);
        const px = x + Math.cos(angle) * radial,
          py = y + Math.sin(angle) * radial;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.strokeStyle = `rgba(${ink},.08)`;
      ctx.lineWidth = 0.7;
      for (let i = -2; i <= 2; i++) {
        ctx.beginPath();
        ctx.moveTo(x - r * 0.5, y + i * r * 0.2);
        ctx.lineTo(x + r * 0.5, y + i * r * 0.2);
        ctx.stroke();
      }
      ctx.fillStyle = `rgba(${ink},.9)`;
      ctx.font = `500 ${Math.max(12, r * 0.2)}px ui-monospace, monospace`;
      ctx.textAlign = "center";
      ctx.fillText("J / L", x, y + 5);
      if (r < 50) return;
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillStyle = `rgba(${ink},.55)`;
      ctx.fillText(
        source ? "LIVE AUDIO SIGNAL" : "LOCAL INTELLIGENCE",
        x,
        y + r * 0.44,
      );
    };
    frame = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frame);
  }, [input, output, state, expanded]);
  return (
    <canvas
      ref={canvas}
      className="visualizer"
      aria-label={`Voice visualizer: ${state}. Responds to actual microphone and speaker audio.`}
    />
  );
}
