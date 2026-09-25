import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import ManualParamForm from "../src/components/ManualParamForm";

const FEATURES = [
  { canonical: "koi_period", display: "Orbital Period", unit: "days", aliases: ["period"] },
  { canonical: "koi_teq", display: "Equilibrium Temperature", unit: "K", aliases: ["temperature"] },
];

describe("ManualParamForm", () => {
  test("renders a human-readable label and canonical name for each feature, never feature_N", () => {
    render(<ManualParamForm features={FEATURES} values={{}} onChange={() => {}} disabled={false} />);
    expect(screen.getByText("Orbital Period")).toBeInTheDocument();
    expect(screen.getByText("(koi_period)")).toBeInTheDocument();
    expect(screen.getByText("Equilibrium Temperature")).toBeInTheDocument();
    expect(screen.queryByText(/feature_1/i)).not.toBeInTheDocument();
  });

  test("shows the unit next to each input", () => {
    render(<ManualParamForm features={FEATURES} values={{}} onChange={() => {}} disabled={false} />);
    expect(screen.getByText("days")).toBeInTheDocument();
    expect(screen.getByText("K")).toBeInTheDocument();
  });

  test("calls onChange with the canonical name when a value is typed", () => {
    const onChange = vi.fn();
    render(<ManualParamForm features={FEATURES} values={{}} onChange={onChange} disabled={false} />);
    fireEvent.change(screen.getByLabelText(/Orbital Period/i), { target: { value: "9.75" } });
    expect(onChange).toHaveBeenCalledWith("koi_period", "9.75");
  });
});
