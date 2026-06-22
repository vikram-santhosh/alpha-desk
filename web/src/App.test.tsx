import { cleanup, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function mockReducedMotion(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AlphaDesk cockpit shell", () => {
  it("mounts the backend feature cockpit shell", () => {
    mockReducedMotion(false);

    render(<App />);

    expect(screen.getByRole("heading", { name: "Explore the AlphaDesk engines directly." })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Explore live AlphaDesk systems" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Run a ticker debate" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prism deliberation" })).toBeInTheDocument();
    expect(screen.getByText("No run yet — enter a ticker or idea and run the council.")).toBeInTheDocument();
  });

  it("omits aurora drift markers when reduced motion is preferred", () => {
    mockReducedMotion(true);

    render(<App />);

    const drifting = screen
      .getAllByTestId("aurora-blob")
      .filter((blob) => blob.getAttribute("data-drift") === "true");
    expect(drifting).toHaveLength(0);
  });

  it("renders backend feature navigation links", () => {
    mockReducedMotion(false);

    render(<App />);

    expect(screen.getByRole("link", { name: "Features" })).toHaveAttribute("href", "#features");
    expect(screen.getByRole("link", { name: "Council" })).toHaveAttribute("href", "#council");
    expect(screen.getByRole("link", { name: "Scout" })).toHaveAttribute("href", "#scout");
    expect(screen.getByRole("link", { name: "Context" })).toHaveAttribute("href", "#context");
  });

  it("has no axe accessibility violations in the empty cockpit", async () => {
    mockReducedMotion(true);

    const { container } = render(<App />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
