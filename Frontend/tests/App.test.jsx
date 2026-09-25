import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import App from "../src/App";

describe("App shell", () => {
  test("renders sidebar navigation and the upload page by default", () => {
    render(<App />);
    expect(screen.getByText("Exoplanet Discovery")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Step 1.*Upload Light Curve/i })).toBeInTheDocument();
    expect(screen.getByText(/Drag & drop an observational CSV here/i)).toBeInTheDocument();
  });

  test("Results page redirects back to Upload before any light curve has been analyzed", async () => {
    render(<App />);
    const resultsLink = screen.getByRole("link", { name: /Results/i });
    fireEvent.click(resultsLink);
    // Guided flow: with no light curve attached, Results redirects to Page 1
    // rather than showing an inline empty state or any prediction.
    expect(await screen.findByRole("heading", { name: /Step 1.*Upload Light Curve/i })).toBeInTheDocument();
    expect(screen.queryByText(/Predicted class/i)).not.toBeInTheDocument();
  });

  test("Manual Parameters page redirects back to Upload before any light curve has been analyzed", async () => {
    render(<App />);
    const paramsLink = screen.getByRole("link", { name: /Manual Parameters/i });
    fireEvent.click(paramsLink);
    expect(await screen.findByRole("heading", { name: /Step 1.*Upload Light Curve/i })).toBeInTheDocument();
  });
});
