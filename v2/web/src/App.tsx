import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Authenticator, ThemeProvider, useAuthenticator, type Theme } from "@aws-amplify/ui-react";
import { userGroups } from "./api";
import { Logo, Shell, type Role } from "./components/Layout";
import ProviderDashboard from "./provider/Dashboard";
import NewClaim from "./provider/NewClaim";
import MyClaims from "./provider/MyClaims";
import ClaimDetail from "./provider/ClaimDetail";
import ExaminerDashboard from "./examiner/Dashboard";
import ReviewQueue from "./examiner/ReviewQueue";
import ReviewDetail from "./examiner/ReviewDetail";

const theme: Theme = {
  name: "claims",
  tokens: {
    colors: {
      brand: {
        primary: {
          10: { value: "#f4f7ff" }, 20: { value: "#e9f0fe" }, 40: { value: "#c9dafb" }, 60: { value: "#4a80f0" },
          80: { value: "#2e66e8" }, 90: { value: "#1f4fc7" }, 100: { value: "#183f9e" },
        },
      },
    },
    radii: { small: { value: "10px" }, medium: { value: "12px" }, large: { value: "18px" } },
    components: {
      authenticator: { router: { borderWidth: { value: "0" }, boxShadow: { value: "0 12px 40px rgba(30,37,50,0.10)" } } },
      button: { primary: { backgroundColor: { value: "{colors.brand.primary.80}" } } },
    },
  },
};

function Signed({ signOut, email }: { signOut?: () => void; email?: string }) {
  const [groups, setGroups] = useState<string[] | null>(null);
  useEffect(() => {
    userGroups().then(setGroups).catch(() => setGroups([]));
  }, []);
  if (groups === null) return <p className="muted" style={{ padding: 32 }}>Loading…</p>;
  const role: Role | null = groups.includes("examiners") ? "examiner" : groups.includes("providers") ? "provider" : null;
  if (!role) {
    return (
      <div className="auth-form">
        <div className="card card-body" style={{ maxWidth: 480 }}>
          <Logo />
          <p>Your account is not in the <b>providers</b> or <b>examiners</b> group yet. Ask an administrator for access.</p>
          <button className="btn ghost" onClick={signOut}>Sign out</button>
        </div>
      </div>
    );
  }
  return (
    <BrowserRouter>
      <Shell role={role} email={email} signOut={signOut}>
        <Routes>
          {role === "provider" ? (
            <>
              <Route path="/provider" element={<ProviderDashboard />} />
              <Route path="/provider/claims" element={<MyClaims />} />
              <Route path="/provider/new" element={<NewClaim />} />
              <Route path="/provider/claims/:claimId" element={<ClaimDetail />} />
              <Route path="*" element={<Navigate to="/provider" replace />} />
            </>
          ) : (
            <>
              <Route path="/examiner" element={<ExaminerDashboard />} />
              <Route path="/examiner/reviews" element={<ReviewQueue />} />
              <Route path="/examiner/reviews/:claimId" element={<ReviewDetail />} />
              <Route path="*" element={<Navigate to="/examiner" replace />} />
            </>
          )}
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <Authenticator.Provider>
        <Gate />
      </Authenticator.Provider>
    </ThemeProvider>
  );
}

function Gate() {
  const { authStatus, signOut, user } = useAuthenticator((ctx) => [ctx.authStatus, ctx.user]);
  if (authStatus === "authenticated") return <Signed signOut={signOut} email={user?.signInDetails?.loginId} />;
  return (
    <div className="auth-wrap">
      <div className="auth-art">
        <Logo />
        <h1>CMS-1500 claims, reviewed by AI agents and decided by people.</h1>
        <p>
          Providers submit claim forms with supporting records. Specialist agents check data, eligibility, medical
          necessity and plan policy, and examiners make the final call with every finding cited.
        </p>
      </div>
      <div className="auth-form">
        <Authenticator hideSignUp />
      </div>
    </div>
  );
}
