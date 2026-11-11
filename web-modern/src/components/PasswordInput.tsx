/** Password field with a show/hide (eye) button. Takes the usual input props; Field passes id and aria-describedby. */
import { useId, useState, type InputHTMLAttributes } from "react";

import { Icon } from "./icons";

export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [shown, setShown] = useState(false);
  const fallbackId = useId();
  const id = props.id ?? fallbackId;
  // The button's name is "Show"/"Hide" (not "Show password"), so finding the field by its "Password" label stays unambiguous.
  return (
    <div className="password-input">
      <input {...props} id={id} type={shown ? "text" : "password"} />
      <button type="button" className="password-toggle" aria-label={shown ? "Hide" : "Show"} aria-controls={id} aria-pressed={shown}
        title={shown ? "Hide password" : "Show password"} onClick={() => setShown((v) => !v)}>
        <Icon name={shown ? "eyeOff" : "eye"} />
      </button>
    </div>
  );
}
