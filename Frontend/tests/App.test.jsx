import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import App from "../src/App";

describe("App shell", () => {
  test("renders sidebar navigation and the upload page by default", () => {
    render(<App />);
    expect(screen.getByText("Exoplanet Discovery")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Upload a Light Curve/i })).toBeInTheDocument();
    expect(screen.getByText(/Drag & drop an observational CSV here/i)).toBeInTheDocument();
  });

  test("Results page shows an honest empty state before any analysis has run", async () => {
    render(<App />);
    const resultsLink = screen.getByRole("link", { name: /Results/i });
    resultsLink.click();
    expect(await screen.findByText(/No analysis yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/Predicted class/i)).not.toBeInTheDocument();
  });
});
