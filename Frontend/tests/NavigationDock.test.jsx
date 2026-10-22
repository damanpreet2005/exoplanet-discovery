import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, beforeEach } from "vitest";
import App from "../src/App";

describe("Floating navigation dock", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
  });

  test("all existing navigation destinations are still present and routable", () => {
    render(<App />);
    const expected = [
      ["Upload & Analyze", "/"],
      ["Manual Parameters", "/manual-parameters"],
      ["Detection & Prediction", "/results"],
      ["Physics Validation", "/physics-validation"],
      ["Planet Characterization", "/characterisation"],
      ["Discovery Report", "/report"],
      ["System Status", "/status"],
    ];
    for (const [label, href] of expected) {
      const link = screen.getByRole("link", { name: label });
      expect(link).toHaveAttribute("href", href);
    }
  });

  test("the current route's link is marked active", () => {
    window.history.pushState({}, "", "/status");
    render(<App />);
    expect(screen.getByRole("link", { name: "System Status" })).toHaveClass("active");
    expect(screen.getByRole("link", { name: "Upload & Analyze" })).not.toHaveClass("active");
  });

  test("the root link is only active on the exact root route, not every route (end matching preserved)", () => {
    window.history.pushState({}, "", "/status");
    render(<App />);
    expect(screen.getByRole("link", { name: "Upload & Analyze" })).not.toHaveClass("active");
  });

  test("the dock renders inside a floating panel container, not an edge-attached full-height element", () => {
    render(<App />);
    const dock = screen.getByLabelText("Primary navigation");
    expect(dock.className).toBe("dock");
    expect(dock.querySelector(".dock-panel")).toBeInTheDocument();
  });

  test("each nav item exposes an accessible name identical to its label (serves as the hover tooltip too)", () => {
    render(<App />);
    const link = screen.getByRole("link", { name: "Physics Validation" });
    expect(link).toHaveAttribute("title", "Physics Validation");
    expect(link).toHaveAttribute("aria-label", "Physics Validation");
  });

  test("the narrow-screen menu button toggles the dock open and closed", () => {
    render(<App />);
    const dock = screen.getByLabelText("Primary navigation");
    const toggle = screen.getByRole("button", { name: "Open navigation menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(dock).toHaveAttribute("data-open", "false");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close navigation menu" })).toHaveAttribute("aria-expanded", "true");
    expect(dock).toHaveAttribute("data-open", "true");
    // The open state is exposed as an attribute, so the dock keeps its exact class.
    expect(dock.className).toBe("dock");

    fireEvent.click(screen.getByRole("button", { name: "Close navigation menu" }));
    expect(dock).toHaveAttribute("data-open", "false");
  });

  test("the open menu closes on navigation, Escape, and a tap outside it", () => {
    render(<App />);
    const dock = screen.getByLabelText("Primary navigation");
    const open = () => fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));

    open();
    fireEvent.click(screen.getByRole("link", { name: "System Status" }));
    expect(window.location.pathname).toBe("/status");
    expect(dock).toHaveAttribute("data-open", "false");

    open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(dock).toHaveAttribute("data-open", "false");

    open();
    fireEvent.pointerDown(document.body);
    expect(dock).toHaveAttribute("data-open", "false");
  });
});
