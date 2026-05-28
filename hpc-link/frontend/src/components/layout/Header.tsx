import { useQuery } from '@tanstack/react-query';
import api from '../../api/client';
import { Circle } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useAuth } from '../../auth/useAuth';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

export function Header() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const { data: health, isLoading } = useQuery({
        queryKey: ['health-ssh'],
        queryFn: async () => {
            try {
                const res = await api.get('/health/ssh');
                return res.data;
            } catch {
                return { status: 'error', connected: false };
            }
        },
        refetchInterval: 5000,
    });

    const isConnected = health?.connected === true;
    const initials = (user?.username || 'U').slice(0, 2).toUpperCase();

    return (
        <header className="flex h-16 items-center justify-between border-b bg-card px-8">
            <div className="flex items-center gap-4">
                <h2 className="text-sm font-medium text-muted-foreground">Path / Dashboard</h2>
            </div>
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
                    <Circle className={cn("h-2 w-2 fill-current", isConnected ? "text-green-500" : "text-red-500")} />
                    <span className="capitalize">{isLoading ? 'Checking...' : isConnected ? 'HPC Connected' : 'HPC Disconnected'}</span>
                </div>
                <div className="text-xs text-muted-foreground">{user?.username}</div>
                <button
                    type="button"
                    className="text-xs rounded-md border px-2 py-1 hover:bg-secondary"
                    onClick={() => {
                        logout();
                        navigate('/login', { replace: true });
                        toast.success('Signed out');
                    }}
                >
                    Logout
                </button>
                <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center text-xs font-bold">
                    {initials}
                </div>
            </div>
        </header>
    );
}
