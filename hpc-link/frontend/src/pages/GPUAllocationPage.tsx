import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
    Cpu,
    Play,
    RefreshCw,
    AlertCircle,
    CheckCircle2,
    Terminal as TerminalIcon,
    Clock,
    Layers,
    Zap,
    Activity
} from 'lucide-react';
import { listPartitions, runNvidiaSmi, allocateGPU } from '../api/hpc';
import type { GPUAllocationRequest } from '../api/hpc';
import { getApiErrorMessage } from '../api/errors';
import { toast } from 'sonner';
import { cn } from '../lib/utils';

export default function GPUAllocationPage() {
    const [partition, setPartition] = useState<string>('partition-a');
    const [gpuType, setGpuType] = useState<string>('');
    const [gpuCount, setGpuCount] = useState<number>(1);
    const [timeLimit, setTimeLimit] = useState<string>('01:00:00');
    const [command, setCommand] = useState<string>('nvidia-smi');

    const { data: partitionData, isLoading: isLoadingPartitions } = useQuery({
        queryKey: ['partitions'],
        queryFn: listPartitions,
    });

    const { data: nvidiaSmi, isLoading: isLoadingSmi, refetch: refetchSmi } = useQuery({
        queryKey: ['nvidia-smi', partition, gpuType],
        queryFn: () => runNvidiaSmi(partition, gpuType || undefined),
        enabled: false, // Don't run automatically
    });

    const allocationMutation = useMutation({
        mutationFn: (req: GPUAllocationRequest) => allocateGPU(req),
        onSuccess: (data) => {
            if (data.success) {
                toast.success('GPU Allocation successful');
            } else {
                toast.error(`Allocation failed: ${data.stderr}`);
            }
        },
        onError: (error: unknown) => {
            toast.error(`Error: ${getApiErrorMessage(error, 'GPU allocation failed')}`);
        }
    });

    const handleQuickTest = () => {
        refetchSmi();
    };

    const handleAllocate = (e: React.FormEvent) => {
        e.preventDefault();
        allocationMutation.mutate({
            command,
            partition,
            gpu_type: gpuType || undefined,
            gpu_count: gpuCount,
            time_limit: timeLimit,
        });
    };

    return (
        <div className="space-y-8 max-w-6xl mx-auto">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">GPU Allocation</h1>
                <p className="text-muted-foreground">Request interactive GPU resources or test current availability.</p>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
                {/* Allocation Form */}
                <div className="rounded-xl border bg-card shadow-sm">
                    <div className="p-6 border-b flex items-center gap-2">
                        <Cpu className="h-5 w-5 text-primary" />
                        <h3 className="font-semibold">Resource Request</h3>
                    </div>
                    <form onSubmit={handleAllocate} className="p-6 space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Partition</label>
                            <select
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                value={partition}
                                onChange={(e) => setPartition(e.target.value)}
                            >
                                {isLoadingPartitions ? (
                                    <option>Loading...</option>
                                ) : (
                                    partitionData?.partitions.map((p) => (
                                        <option key={p.partition} value={p.partition}>
                                            {p.partition} ({p.state}, {p.available} nodes)
                                        </option>
                                    ))
                                )}
                            </select>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">GPU Type (Optional)</label>
                                <input
                                    type="text"
                                    placeholder="e.g. a100, rtx3090"
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={gpuType}
                                    onChange={(e) => setGpuType(e.target.value)}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">GPU Count</label>
                                <input
                                    type="number"
                                    min="1"
                                    max="8"
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={gpuCount}
                                    onChange={(e) => setGpuCount(parseInt(e.target.value))}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium flex items-center gap-2">
                                <Clock className="h-4 w-4" /> Time Limit
                            </label>
                            <input
                                type="text"
                                placeholder="HH:MM:SS"
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                value={timeLimit}
                                onChange={(e) => setTimeLimit(e.target.value)}
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium flex items-center gap-2">
                                <TerminalIcon className="h-4 w-4" /> Command
                            </label>
                            <input
                                type="text"
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
                                value={command}
                                onChange={(e) => setCommand(e.target.value)}
                            />
                        </div>

                        <div className="pt-4 flex gap-4">
                            <button
                                type="submit"
                                disabled={allocationMutation.isPending}
                                className="flex-1 flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                            >
                                {allocationMutation.isPending ? (
                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Play className="h-4 w-4" />
                                )}
                                Run Command
                            </button>
                            <button
                                type="button"
                                onClick={handleQuickTest}
                                disabled={isLoadingSmi}
                                className="flex-1 flex items-center justify-center gap-2 rounded-lg border bg-background px-4 py-2 text-sm font-medium hover:bg-secondary transition-colors disabled:opacity-50"
                            >
                                {isLoadingSmi ? (
                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Zap className="h-4 w-4" />
                                )}
                                Quick Test (nvidia-smi)
                            </button>
                        </div>
                    </form>
                </div>

                {/* Status and Results */}
                <div className="space-y-6">
                    {/* Status Card */}
                    <div className="rounded-xl border bg-card shadow-sm p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="font-semibold flex items-center gap-2">
                                <Activity className="h-5 w-5 text-primary" />
                                Status
                            </h3>
                            {allocationMutation.data?.success || nvidiaSmi?.success ? (
                                <span className="flex items-center gap-1 text-xs font-medium text-green-500 bg-green-500/10 px-2 py-1 rounded-full">
                                    <CheckCircle2 className="h-3 w-3" /> {allocationMutation.data ? 'Command Success' : 'Ready'}
                                </span>
                            ) : (allocationMutation.error || nvidiaSmi?.error || (allocationMutation.data && !allocationMutation.data.success)) ? (
                                <span className="flex items-center gap-1 text-xs font-medium text-red-500 bg-red-500/10 px-2 py-1 rounded-full">
                                    <AlertCircle className="h-3 w-3" /> Error
                                </span>
                            ) : (
                                <span className="text-xs font-medium text-muted-foreground bg-secondary px-2 py-1 rounded-full">
                                    Idle
                                </span>
                            )}
                        </div>

                        {(nvidiaSmi || allocationMutation.data) && (
                            <div className="space-y-3">
                                {nvidiaSmi && (
                                    <div className="grid grid-cols-2 gap-4">
                                        <div className="space-y-1">
                                            <p className="text-xs text-muted-foreground uppercase font-semibold">GPU Name</p>
                                            <p className="text-sm font-medium">{nvidiaSmi.gpu_name || 'N/A'}</p>
                                        </div>
                                        <div className="space-y-1">
                                            <p className="text-xs text-muted-foreground uppercase font-semibold">Memory Usage</p>
                                            <p className="text-sm font-medium">{nvidiaSmi.gpu_memory || 'N/A'}</p>
                                        </div>
                                    </div>
                                )}
                                <div className="space-y-1">
                                    <p className="text-xs text-muted-foreground uppercase font-semibold">Partition</p>
                                    <p className="text-sm font-medium">{nvidiaSmi?.partition || partition}</p>
                                </div>
                                {allocationMutation.data && (
                                    <div className="space-y-1">
                                        <p className="text-xs text-muted-foreground uppercase font-semibold">Exit Code</p>
                                        <p className="text-sm font-medium">{allocationMutation.data.exit_code}</p>
                                    </div>
                                )}
                            </div>
                        )}
                        {!nvidiaSmi && !isLoadingSmi && !allocationMutation.data && !allocationMutation.isPending && (
                            <div className="text-center py-4 text-muted-foreground text-sm">
                                Run "Quick Test" or "Run Command" to see results
                            </div>
                        )}
                        {(isLoadingSmi || allocationMutation.isPending) && (
                            <div className="flex flex-col items-center justify-center py-4 gap-2">
                                <RefreshCw className="h-8 w-8 animate-spin text-primary" />
                                <p className="text-sm text-muted-foreground">
                                    {isLoadingSmi ? "Allocating GPU and running nvidia-smi..." : "Executing command on allocated GPU..."}
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Output Viewer */}
                    <div className="rounded-xl border bg-black shadow-sm overflow-hidden flex flex-col h-[300px]">
                        <div className="bg-zinc-900 px-4 py-2 border-b border-zinc-800 flex items-center justify-between">
                            <span className="text-xs font-mono text-zinc-400">Output Log</span>
                            <button
                                onClick={() => {
                                    const text = allocationMutation.data?.stdout || nvidiaSmi?.output || '';
                                    navigator.clipboard.writeText(text);
                                    toast.success('Copied to clipboard');
                                }}
                                className="text-xs text-zinc-400 hover:text-white transition-colors"
                            >
                                Copy
                            </button>
                        </div>
                        <div className="flex-1 p-4 font-mono text-xs text-green-500 overflow-auto whitespace-pre">
                            {allocationMutation.data?.stdout || allocationMutation.data?.stderr || nvidiaSmi?.output || nvidiaSmi?.error || 'No output yet.'}
                        </div>
                    </div>
                </div>
            </div>

            {/* Partitions List */}
            <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
                <div className="p-6 border-b flex items-center gap-2">
                    <Layers className="h-5 w-5 text-primary" />
                    <h3 className="font-semibold">Available Partitions</h3>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                        <thead className="text-xs text-muted-foreground uppercase bg-secondary/50">
                            <tr>
                                <th className="px-6 py-3 font-semibold">Partition</th>
                                <th className="px-6 py-3 font-semibold">State</th>
                                <th className="px-6 py-3 font-semibold">Available</th>
                                <th className="px-6 py-3 font-semibold">Nodes</th>
                                <th className="px-6 py-3 font-semibold">GRES (GPUs)</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {isLoadingPartitions ? (
                                <tr>
                                    <td colSpan={5} className="px-6 py-4 text-center">Loading partitions...</td>
                                </tr>
                            ) : (
                                partitionData?.partitions.map((p) => (
                                    <tr key={p.partition} className="hover:bg-secondary/30 transition-colors">
                                        <td className="px-6 py-4 font-medium">{p.partition}</td>
                                        <td className="px-6 py-4">
                                            <span className={cn(
                                                "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase",
                                                p.state === 'up' ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                                            )}>
                                                {p.state}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4">{p.available}</td>
                                        <td className="px-6 py-4">{p.node_count}</td>
                                        <td className="px-6 py-4 font-mono text-xs">{p.gres}</td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
