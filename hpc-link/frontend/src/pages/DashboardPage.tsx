import {
    Terminal,
    Cpu,
    Activity,
    Zap,
    Server,
    Cloud,
    MessageSquare
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';

export default function DashboardPage() {
    const navigate = useNavigate();
    const { data: health } = useQuery({
        queryKey: ['health'],
        queryFn: async () => {
            const res = await api.get('/health');
            return res.data;
        },
        refetchInterval: 5000,
    });

    const cards = [
        {
            name: 'HPC Status',
            value: health?.status === 'ok' ? 'Connected' : 'Disconnected',
            icon: Server,
            color: health?.status === 'ok' ? 'text-green-500' : 'text-red-500'
        },
        { name: 'Active Jobs', value: '3', icon: Activity, color: 'text-blue-500' },
        { name: 'GPU Quota', value: '80%', icon: Cpu, color: 'text-purple-500' },
        { name: 'Storage', value: '1.2 TB', icon: Cloud, color: 'text-orange-500' },
    ];

    return (
        <div className="space-y-8">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
                <p className="text-muted-foreground">Welcome to HPC Link. Manage your remote computing resources.</p>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                {cards.map((card) => (
                    <div key={card.name} className="rounded-xl border bg-card p-6 shadow-sm">
                        <div className="flex items-center justify-between space-y-0 pb-2">
                            <h3 className="text-sm font-medium">{card.name}</h3>
                            <card.icon className={`h-4 w-4 ${card.color}`} />
                        </div>
                        <div className="text-2xl font-bold">{card.value}</div>
                    </div>
                ))}
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
                <div className="col-span-4 rounded-xl border bg-card shadow-sm overflow-hidden">
                    <div className="p-6 border-b">
                        <h3 className="font-semibold">Quick Actions</h3>
                    </div>
                    <div className="p-6 grid grid-cols-2 gap-4">
                        <button
                            onClick={() => navigate('/terminal')}
                            className="flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                        >
                            <Terminal className="h-4 w-4" />
                            Open Terminal
                        </button>
                        <button
                            onClick={() => navigate('/gpu')}
                            className="flex items-center justify-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm font-medium hover:bg-secondary transition-colors"
                        >
                            <Zap className="h-4 w-4" />
                            Allocate GPU
                        </button>
                        <button
                            onClick={() => navigate('/jobs')}
                            className="flex items-center justify-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm font-medium hover:bg-secondary transition-colors col-span-2"
                        >
                            <Activity className="h-4 w-4" />
                            Submit New Job
                        </button>
                        <button
                            onClick={() => navigate('/llm-gateway')}
                            className="flex items-center justify-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm font-medium hover:bg-secondary transition-colors col-span-2"
                        >
                            <MessageSquare className="h-4 w-4" />
                            Open LLM Gateway
                        </button>
                        <button
                            onClick={() => navigate('/hpc-linktest')}
                            className="flex items-center justify-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm font-medium hover:bg-secondary transition-colors col-span-2"
                        >
                            <MessageSquare className="h-4 w-4" />
                            Open HPC-Linktest
                        </button>
                    </div>
                </div>

                <div className="col-span-3 rounded-xl border bg-card shadow-sm">
                    <div className="p-6 border-b">
                        <h3 className="font-semibold">Recent Activity</h3>
                    </div>
                    <div className="p-6">
                        <div className="space-y-4">
                            {[1, 2, 3].map((i) => (
                                <div key={i} className="flex items-center gap-4">
                                    <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center">
                                        <Activity className="h-4 w-4 text-muted-foreground" />
                                    </div>
                                    <div className="flex-1 space-y-1">
                                        <p className="text-sm font-medium">Job #2841{i} completed</p>
                                        <p className="text-xs text-muted-foreground">2 hours ago</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
