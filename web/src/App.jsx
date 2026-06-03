import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./auth";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import Login from "./pages/Login";
import Forgot from "./pages/Forgot";
import Reset from "./pages/Reset";
import ChangePassword from "./pages/ChangePassword";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import Modules from "./pages/Modules";
import Control from "./pages/Control";
import Automation from "./pages/Automation";
import Localities from "./pages/Localities";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot" element={<Forgot />} />
          <Route path="/reset" element={<Reset />} />
          <Route element={<ProtectedRoute permission="read"><Layout /></ProtectedRoute>}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/change-password" element={<ChangePassword />} />
            <Route path="/users" element={
              <ProtectedRoute permission="admin"><Users /></ProtectedRoute>
            } />
            <Route path="/modules" element={
              <ProtectedRoute permission="admin"><Modules /></ProtectedRoute>
            } />
            <Route path="/control" element={
              <ProtectedRoute permission="control"><Control /></ProtectedRoute>
            } />
            <Route path="/automation" element={
              <ProtectedRoute permission="admin"><Automation /></ProtectedRoute>
            } />
            <Route path="/localities" element={
              <ProtectedRoute permission="admin"><Localities /></ProtectedRoute>
            } />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
