import katex from "katex";
import "katex/dist/katex.min.css";

/**
 * Renders a LaTeX expression with KaTeX. `block` renders display-style math
 * (its own line, centred); otherwise inline. Rendering errors fall back to
 * the raw source rather than throwing, so a typo can never blank a page.
 */
export default function TeX({ math, block = false, className = "" }) {
  const html = katex.renderToString(math, { displayMode: block, throwOnError: false, strict: "ignore" });
  const Tag = block ? "div" : "span";
  return <Tag className={`tex${block ? " tex-block" : ""}${className ? ` ${className}` : ""}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
