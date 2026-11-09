import { useState, type InputHTMLAttributes } from "react";
import { IconEye, IconEyeOff } from "./icons";

/** A password input with an eye button to reveal what was typed. Render it inside a <label>. */
export function PasswordField(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [shown, setShown] = useState(false);
  return (
    <span className="pw-wrap">
      <input {...props} type={shown ? "text" : "password"} />
      <button
        type="button"
        className="pw-eye"
        aria-label={shown ? "Hide characters" : "Show characters"}
        aria-pressed={shown}
        onClick={() => setShown((s) => !s)}
      >
        {shown ? <IconEyeOff /> : <IconEye />}
      </button>
    </span>
  );
}
