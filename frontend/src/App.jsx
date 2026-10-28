import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext.jsx";
import RequireAuth from "./auth/RequireAuth.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import ProductPage from "./pages/ProductPage.jsx";
import StatusPage from "./pages/StatusPage.jsx";
import { RealtimeProvider } from "./realtime/RealtimeContext.jsx";

export default function App() {
  return (
    <AuthProvider>
      <RealtimeProvider>
      <Routes>
        <Route path="/login" element={<AuthPage />} />
        <Route path="/register" element={<AuthPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <DashboardPage />
            </RequireAuth>
          }
        />
        <Route
          path="/products/:id"
          element={
            <RequireAuth>
              <ProductPage />
            </RequireAuth>
          }
        />
        <Route
          path="/status"
          element={
            <RequireAuth>
              <StatusPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </RealtimeProvider>
    </AuthProvider>
  );
}
