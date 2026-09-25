import "@testing-library/jest-dom/vitest";

// jsdom does not implement matchMedia or canvas rendering contexts. These are
// harmless test-environment shims for the Starfield background component --
// they do not affect what the component renders in a real browser.
if (!window.matchMedia) {
  window.matchMedia = () => ({
    matches: false,
    addListener: () => {},
    removeListener: () => {},
  });
}

HTMLCanvasElement.prototype.getContext = () => ({
  clearRect: () => {},
  beginPath: () => {},
  arc: () => {},
  fill: () => {},
});

