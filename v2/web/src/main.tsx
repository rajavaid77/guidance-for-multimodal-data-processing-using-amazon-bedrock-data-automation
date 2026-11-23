import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Amplify } from "aws-amplify";
import "@aws-amplify/ui-react/styles.css";
import "./styles.css";
import { loadConfig } from "./config";
import App from "./App";

loadConfig()
  .then((cfg) => {
    Amplify.configure({
      Auth: { Cognito: { userPoolId: cfg.userPoolId, userPoolClientId: cfg.userPoolClientId, loginWith: { email: true } } },
    });
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  })
  .catch((err) => {
    document.getElementById("root")!.textContent = `Configuration error: ${err.message}`;
  });
