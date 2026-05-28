import { NavLink } from 'react-router-dom';
import {
    LayoutDashboard,
    Terminal,
    Files,
    Cpu,
    Settings,
    Activity,
    MessageSquare,
    Users
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useAuth } from '../../auth/useAuth';

const navigation = [
    { name: 'Dashboard', href: '/', icon: LayoutDashboard },
    { name: 'Terminal', href: '/terminal', icon: Terminal },
    { name: 'File Manager', href: '/files', icon: Files },
    { name: 'GPU Allocation', href: '/gpu', icon: Cpu },
    { name: 'LLM Gateway', href: '/llm-gateway', icon: MessageSquare },
    { name: 'HPC-Linktest', href: '/hpc-linktest', icon: MessageSquare },
    { name: 'Jobs', href: '/jobs', icon: Activity },
    { name: 'Settings', href: '/settings', icon: Settings },
];

export function Sidebar() {
    const { user } = useAuth();
    const items = user?.is_admin
        ? [...navigation, { name: 'User Management', href: '/admin/users', icon: Users }]
        : navigation;

    return (
        <div className="flex h-full w-64 flex-col bg-card border-r">
            <div className="flex h-16 shrink-0 items-center px-6">
                <span className="text-xl font-bold text-primary">HPC Link</span>
            </div>
            <nav className="flex flex-1 flex-col px-4 py-4 space-y-1">
                {items.map((item) => (
                    <NavLink
                        key={item.name}
                        to={item.href}
                        className={({ isActive }) =>
                            cn(
                                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                                isActive
                                    ? "bg-secondary text-secondary-foreground"
                                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                            )
                        }
                    >
                        <item.icon className="h-4 w-4" />
                        {item.name}
                    </NavLink>
                ))}
            </nav>
        </div>
    );
}
