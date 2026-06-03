import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function ProtectedRoute({ children, permission }) {
  const { user, loading, has } = useAuth();
  if (loading) return <div className="login-wrap"><p className="muted">Načítám…</p></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (permission && !has(permission))
    return <main><div className="panel"><p className="muted">Nemáš oprávnění pro tuto stránku.</p></div></main>;
  return children;
}
