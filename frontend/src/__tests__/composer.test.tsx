import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { parseCriteria, promptQuality } from "../components/Composer";
import { CreateTask } from "../pages/CreateTask";

beforeEach(() => vi.restoreAllMocks());

describe("prompt quality", () => {
  it("rates empty, vague and specific prompts", () => {
    expect(promptQuality("", []).level).toBe("empty");
    expect(promptQuality("make app", []).level).toBe("vague");
    const good = promptQuality(
      "Build a REST API with POST /links and GET /{code} endpoints that must return 404 for unknown codes, with pytest unit tests",
      ["404 for unknown", "tests pass"],
    );
    expect(good.level).toBe("specific");
    expect(good.score).toBeGreaterThanOrEqual(70);
  });

  it("parses one criterion per non-empty line", () => {
    expect(parseCriteria(" a \n\n b\n")).toEqual(["a", "b"]);
  });
});

describe("launch composer", () => {
  const setup = () => {
    vi.spyOn(api, "get").mockResolvedValue([]);
    const post = vi.spyOn(api, "post").mockImplementation(async (path: string) => (path === "/projects" ? { id: "p1" } : { id: "t1" }) as never);
    render(<MemoryRouter><CreateTask /></MemoryRouter>);
    return post;
  };

  it("language tiles and the select stay in sync", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /^Go/ }));
    expect(screen.getByLabelText("Language")).toHaveValue("go");
    expect(screen.getByRole("button", { name: /^Go/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("an idea card fills the prompt and project name", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /URL shortener/ }));
    expect((screen.getByLabelText("Natural-language requirement") as HTMLTextAreaElement).value).toContain("URL shortener");
    expect(screen.getByLabelText(/Project name/)).toHaveValue("url_shortener");
  });

  it("Ctrl+Enter in the prompt launches the loop", async () => {
    const post = setup();
    await userEvent.click(screen.getByLabelText("Natural-language requirement"));
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t1/start"));
  });
});
