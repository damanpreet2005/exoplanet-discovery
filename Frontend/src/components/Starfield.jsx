import { useEffect, useRef } from "react";

/**
 * Subtle animated star field rendered on a single canvas (not hundreds of DOM
 * nodes) so it stays cheap. Respects prefers-reduced-motion by rendering a
 * static frame instead of animating.
 */
export default function Starfield() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let stars = [];
    let animationFrame;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      const count = Math.floor((canvas.width * canvas.height) / 9000);
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.2 + 0.2,
        phase: Math.random() * Math.PI * 2,
        speed: Math.random() * 0.015 + 0.005,
      }));
    }

    function draw(time) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const star of stars) {
        const twinkle = reduceMotion ? 0.7 : 0.5 + 0.5 * Math.sin(star.phase + time * star.speed);
        ctx.globalAlpha = 0.25 + twinkle * 0.6;
        ctx.fillStyle = "#cfe4ff";
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        ctx.fill();
      }
      if (!reduceMotion) animationFrame = requestAnimationFrame(draw);
    }

    resize();
    draw(0);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      if (animationFrame) cancelAnimationFrame(animationFrame);
    };
  }, []);

  return <canvas ref={canvasRef} className="starfield-canvas" aria-hidden="true" />;
}
