import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "../styles.css";
import { Shell, type Role } from "../components/Layout";
import ProviderDashboard from "../provider/Dashboard";
import NewClaim from "../provider/NewClaim";
import MyClaims from "../provider/MyClaims";
import ClaimDetail from "../provider/ClaimDetail";
import ExaminerDashboard from "../examiner/Dashboard";
import ReviewQueue from "../examiner/ReviewQueue";
import ReviewDetail from "../examiner/ReviewDetail";

const role: Role = location.pathname.startsWith("/examiner") ? "examiner" : "provider";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Shell role={role} email={role === "examiner" ? "examiner@example.com" : "provider@example.com"} signOut={() => undefined}>
        <Routes>
          <Route path="/provider" element={<ProviderDashboard />} />
          <Route path="/provider/claims" element={<MyClaims />} />
          <Route path="/provider/new" element={<NewClaim />} />
          <Route path="/provider/claims/:claimId" element={<ClaimDetail />} />
          <Route path="/examiner" element={<ExaminerDashboard />} />
          <Route path="/examiner/reviews" element={<ReviewQueue />} />
          <Route path="/examiner/reviews/:claimId" element={<ReviewDetail />} />
          <Route path="*" element={<Navigate to="/provider" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  </StrictMode>,
);
