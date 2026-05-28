import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { Layout } from './components/layout/Layout';
import { AuthProvider } from './auth/AuthContext';
import { RequireAdmin, RequireAuth } from './auth/RouteGuards';
import DashboardPage from './pages/DashboardPage';
import TerminalPage from './pages/TerminalPage';
import FileManagerPage from './pages/FileManagerPage';
import GPUAllocationPage from './pages/GPUAllocationPage';
import JobsPage from './pages/JobsPage';
import LLMGatewayPage from './pages/LLMGatewayPage';
import HPCLinktestPage from './pages/HPCLinktestPage';
import LoginPage from './pages/LoginPage';
import AdminUsersPage from './pages/AdminUsersPage';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/terminal" element={<TerminalPage />} />
                <Route path="/files" element={<FileManagerPage />} />
                <Route path="/gpu" element={<GPUAllocationPage />} />
                <Route path="/llm-gateway" element={<LLMGatewayPage />} />
                <Route path="/hpc-linktest" element={<HPCLinktestPage />} />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/settings" element={<div>Settings (Coming Soon)</div>} />
                <Route element={<RequireAdmin />}>
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                </Route>
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      <Toaster />
    </QueryClientProvider>
  );
}

export default App;
