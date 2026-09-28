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

  test("a field with a resolved status renders as a locked, read-only value with a badge", () => {
    render(
      <ManualParamForm
        features={FEATURES}
        values={{ koi_period: "9.488" }}
        onChange={() => {}}
        disabled={false}
        statusByCanonical={{ koi_period: "estimated" }}
      />
    );
    expect(screen.getByText("9.488")).toBeInTheDocument();
    expect(screen.getByText(/estimated from light curve/i)).toBeInTheDocument();
    // Locked -- no editable number input for this field.
    expect(screen.queryByLabelText(/Orbital Period/i)).not.toBeInTheDocument();
  });

  test("an 'unavailable' status still renders an editable input", () => {
    render(
      <ManualParamForm
        features={FEATURES}
        values={{}}
        onChange={() => {}}
        disabled={false}
        statusByCanonical={{ koi_teq: "unavailable" }}
      />
    );
    expect(screen.getByLabelText(/Equilibrium Temperature/i)).toBeInTheDocument();
  });

  test("expertMode unlocks a resolved field back into an editable input", () => {
    render(
      <ManualParamForm
        features={FEATURES}
        values={{ koi_period: "9.488" }}
        onChange={() => {}}
        disabled={false}
        statusByCanonical={{ koi_period: "catalog" }}
        expertMode
      />
    );
    expect(screen.getByLabelText(/Orbital Period/i)).toBeInTheDocument();
  });
});
