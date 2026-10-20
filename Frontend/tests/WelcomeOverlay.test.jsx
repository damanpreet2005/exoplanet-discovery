import { render, screen, act } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import WelcomeOverlay from "../src/components/WelcomeOverlay";

describe("WelcomeOverlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("renders the welcome title immediately", () => {
    render(<WelcomeOverlay onDone={() => {}} />);
    expect(screen.getByText("Welcome to Exo Discovery")).toBeInTheDocument();
  });

  test("does not call onDone before the visible duration elapses", () => {
    const onDone = vi.fn();
    render(<WelcomeOverlay onDone={onDone} />);
    act(() => vi.advanceTimersByTime(1000));
    expect(onDone).not.toHaveBeenCalled();
  });

  test("begins the leaving (fade-out) transition after ~1.8s, before fully finishing", () => {
    render(<WelcomeOverlay onDone={() => {}} />);
    act(() => vi.advanceTimersByTime(1800));
    expect(document.querySelector(".welcome-overlay.is-leaving")).toBeInTheDocument();
  });

  test("calls onDone automatically once the full sequence (visible + fade-out) completes, with no click required", () => {
    const onDone = vi.fn();
    render(<WelcomeOverlay onDone={onDone} />);
    act(() => vi.advanceTimersByTime(1800 + 400));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  test("the total on-screen time stays within the requested 1.5-2.5s window", () => {
    const onDone = vi.fn();
    render(<WelcomeOverlay onDone={onDone} />);
    act(() => vi.advanceTimersByTime(2500));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  test("cleans up its timers on unmount (no stray onDone call after unmount)", () => {
    const onDone = vi.fn();
    const { unmount } = render(<WelcomeOverlay onDone={onDone} />);
    unmount();
    act(() => vi.advanceTimersByTime(5000));
    expect(onDone).not.toHaveBeenCalled();
  });
});
