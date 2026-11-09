import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Confetti } from "../components/Confetti";
import { Toaster, toast } from "../components/Toast";
import { ScoreRing } from "../components/ui";

const setReducedMotion = (reduce: boolean) =>
  vi.spyOn(window, "matchMedia").mockImplementation(
    (q: string) => ({ matches: reduce && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList,
  );

describe("motion components", () => {
  afterEach(() => vi.restoreAllMocks());

  it("a toast appears and goes away on its own", () => {
    vi.useFakeTimers();
    render(<Toaster />);
    act(() => toast("Loop started", "ok"));
    expect(screen.getByText("Loop started")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText("Loop started")).toBeNull();
    vi.useRealTimers();
  });

  it("confetti renders particles, but nothing under reduced motion", () => {
    setReducedMotion(false);
    const { unmount } = render(<Confetti count={5} />);
    expect(screen.getByTestId("confetti").children).toHaveLength(5);
    unmount();
    setReducedMotion(true);
    render(<Confetti count={5} />);
    expect(screen.queryByTestId("confetti")).toBeNull();
  });

  it("the score ring shows the rounded value, or a dash without one", () => {
    const { rerender } = render(<ScoreRing value={93.6} label="Quality" />);
    expect(screen.getByText("94")).toBeInTheDocument();
    rerender(<ScoreRing value={null} label="Quality" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
