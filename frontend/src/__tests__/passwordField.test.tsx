import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PasswordField } from "../components/PasswordField";

describe("PasswordField", () => {
  it("hides the characters by default and reveals them on request", async () => {
    render(
      <label>
        Password
        <PasswordField defaultValue="s3cretpass" />
      </label>,
    );
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");

    await userEvent.click(screen.getByRole("button", { name: "Show characters" }));
    expect(input.type).toBe("text");
    expect(input.value).toBe("s3cretpass");

    await userEvent.click(screen.getByRole("button", { name: "Hide characters" }));
    expect(input.type).toBe("password");
  });
});
