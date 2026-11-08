import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { CreateTask } from "../pages/CreateTask";

function setup() {
  const post = vi
    .spyOn(api, "post")
    .mockImplementation(async (path: string) =>
      (path === "/projects" ? { id: "p1" } : { id: "t1" }) as never,
    );
  const upload = vi.spyOn(api, "upload").mockResolvedValue({} as never);
  render(
    <MemoryRouter>
      <CreateTask />
    </MemoryRouter>,
  );
  return { post, upload };
}

beforeEach(() => vi.restoreAllMocks());

describe("task creation with languages and repositories", () => {
  it("defaults to a new Python project", async () => {
    const { post, upload } = setup();
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t1/start"));
    expect(post).toHaveBeenCalledWith("/projects", { name: "employee_management", language: "python" });
    const task = post.mock.calls.find((c) => c[0] === "/tasks")![1] as Record<string, unknown>;
    expect(task.source_type).toBe("none");
    expect(task.git_url).toBeUndefined();
    expect(upload).not.toHaveBeenCalled();
  });

  it("sends the chosen language", async () => {
    const { post } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Language"), "javascript");
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t1/start"));
    expect(post).toHaveBeenCalledWith("/projects", { name: "employee_management", language: "javascript" });
  });

  it("uploads the zip after creating the task and before starting it", async () => {
    const { post, upload } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Starting point"), "zip");
    const file = new File(["zip"], "repo.zip", { type: "application/zip" });
    await userEvent.upload(screen.getByLabelText("Repository zip"), file);
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t1/start"));
    expect(upload).toHaveBeenCalledWith("/tasks/t1/source", file);
    expect(upload.mock.invocationCallOrder[0]).toBeLessThan(
      post.mock.invocationCallOrder[post.mock.calls.findIndex((c) => c[0] === "/tasks/t1/start")],
    );
    const task = post.mock.calls.find((c) => c[0] === "/tasks")![1] as Record<string, unknown>;
    expect(task.source_type).toBe("zip");
  });

  it("refuses to submit a zip task without a file", async () => {
    const { post } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Starting point"), "zip");
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Choose a .zip file/);
    expect(post).not.toHaveBeenCalled();
  });

  it("passes the git URL and warns that the repo is untrusted", async () => {
    const { post } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Starting point"), "git");
    await userEvent.type(screen.getByLabelText("Git URL"), "https://github.com/a/b");
    expect(screen.getByText(/treated as untrusted/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t1/start"));
    const task = post.mock.calls.find((c) => c[0] === "/tasks")![1] as Record<string, unknown>;
    expect(task).toMatchObject({ source_type: "git", git_url: "https://github.com/a/b" });
  });
});
