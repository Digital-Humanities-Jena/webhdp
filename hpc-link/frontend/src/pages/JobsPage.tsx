import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
    Activity,
    Plus,
    Play,
    XCircle,
    RefreshCw,
    Trash2,
    Eye
} from 'lucide-react';
import { listJobs, submitJob, cancelJob } from '../api/jobs';
import type { JobConfig } from '../api/jobs';
import { listPartitions } from '../api/hpc';
import { getApiErrorMessage } from '../api/errors';
import { toast } from 'sonner';
import { cn } from '../lib/utils';
import { JobLogViewer } from '../components/hpc/JobLogViewer';

export default function JobsPage() {
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

    // Form State
    const [jobName, setJobName] = useState('hpc-link-job');
    const [partition, setPartition] = useState('partition-a');
    const [command, setCommand] = useState('nvidia-smi');
    const [workingDir, setWorkingDir] = useState('/srv/hpc-link/data');
    const [gpuCount, setGpuCount] = useState(1);
    const [timeLimit, setTimeLimit] = useState('01:00:00');

    const { data: jobs, isLoading: isLoadingJobs, refetch: refetchJobs } = useQuery({
        queryKey: ['jobs'],
        queryFn: listJobs,
        refetchInterval: 10000,
    });

    const { data: partitions } = useQuery({
        queryKey: ['partitions'],
        queryFn: listPartitions,
    });

    const submitMutation = useMutation({
        mutationFn: (config: JobConfig) => submitJob(config),
        onSuccess: () => {
            toast.success('Job submitted successfully');
            setIsSubmitting(false);
            refetchJobs();
        },
        onError: (error: unknown) => {
            toast.error(`Submission failed: ${getApiErrorMessage(error, 'Job submission failed')}`);
        }
    });

    const cancelMutation = useMutation({
        mutationFn: (jobId: string) => cancelJob(jobId),
        onSuccess: () => {
            toast.success('Job cancellation requested');
            refetchJobs();
        },
        onError: (error: unknown) => {
            toast.error(`Cancellation failed: ${getApiErrorMessage(error, 'Job cancellation failed')}`);
        }
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        submitMutation.mutate({
            job_name: jobName,
            partition,
            commands: [command],
            working_dir: workingDir,
            gpu_count: gpuCount,
            time_limit: timeLimit,
            nodes: 1,
            tasks_per_node: 1,
            cpus_per_task: 1,
            memory: '8G',
            output_path: 'slurm-%j.out',
            error_path: 'slurm-%j.err',
            modules: [],
            environment_vars: {},
            use_uv: false,
            uv_install: false
        });
    };

    return (
        <div className="space-y-8 max-w-6xl mx-auto">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Job Manager</h1>
                    <p className="text-muted-foreground">Submit and monitor SLURM batch jobs.</p>
                </div>
                <button
                    onClick={() => setIsSubmitting(!isSubmitting)}
                    className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                    {isSubmitting ? <XCircle className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                    {isSubmitting ? 'Cancel' : 'New Job'}
                </button>
            </div>

            {isSubmitting && (
                <div className="rounded-xl border bg-card shadow-sm animate-in fade-in slide-in-from-top-4 duration-300">
                    <div className="p-6 border-b flex items-center gap-2">
                        <Plus className="h-5 w-5 text-primary" />
                        <h3 className="font-semibold">Submit New Job</h3>
                    </div>
                    <form onSubmit={handleSubmit} className="p-6 space-y-4">
                        <div className="grid gap-4 md:grid-cols-2">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Job Name</label>
                                <input
                                    type="text"
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={jobName}
                                    onChange={(e) => setJobName(e.target.value)}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Partition</label>
                                <select
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={partition}
                                    onChange={(e) => setPartition(e.target.value)}
                                >
                                    {partitions?.partitions.map(p => (
                                        <option key={p.partition} value={p.partition}>{p.partition}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Working Directory</label>
                            <input
                                type="text"
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
                                value={workingDir}
                                onChange={(e) => setWorkingDir(e.target.value)}
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Command</label>
                            <textarea
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono min-h-[100px] focus:outline-none focus:ring-2 focus:ring-primary"
                                value={command}
                                onChange={(e) => setCommand(e.target.value)}
                            />
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">GPU Count</label>
                                <input
                                    type="number"
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={gpuCount}
                                    onChange={(e) => setGpuCount(parseInt(e.target.value))}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Time Limit</label>
                                <input
                                    type="text"
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                                    value={timeLimit}
                                    onChange={(e) => setTimeLimit(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="pt-4">
                            <button
                                type="submit"
                                disabled={submitMutation.isPending}
                                className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                            >
                                {submitMutation.isPending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                Submit Job
                            </button>
                        </div>
                    </form>
                </div>
            )}

            <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
                <div className="p-6 border-b flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Activity className="h-5 w-5 text-primary" />
                        <h3 className="font-semibold">Active Jobs</h3>
                    </div>
                    <button
                        onClick={() => refetchJobs()}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                    >
                        <RefreshCw className={cn("h-4 w-4", isLoadingJobs && "animate-spin")} />
                    </button>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                        <thead className="text-xs text-muted-foreground uppercase bg-secondary/50">
                            <tr>
                                <th className="px-6 py-3 font-semibold">ID</th>
                                <th className="px-6 py-3 font-semibold">Name</th>
                                <th className="px-6 py-3 font-semibold">Partition</th>
                                <th className="px-6 py-3 font-semibold">State</th>
                                <th className="px-6 py-3 font-semibold">Time</th>
                                <th className="px-6 py-3 font-semibold">Nodes</th>
                                <th className="px-6 py-3 font-semibold text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {isLoadingJobs ? (
                                <tr>
                                    <td colSpan={7} className="px-6 py-4 text-center">Loading jobs...</td>
                                </tr>
                            ) : jobs?.length === 0 ? (
                                <tr>
                                    <td colSpan={7} className="px-6 py-4 text-center text-muted-foreground">No active jobs found.</td>
                                </tr>
                            ) : (
                                jobs?.map((job) => (
                                    <tr key={job.job_id} className="hover:bg-secondary/30 transition-colors">
                                        <td className="px-6 py-4 font-mono">{job.job_id}</td>
                                        <td className="px-6 py-4 font-medium">{job.name}</td>
                                        <td className="px-6 py-4">{job.partition}</td>
                                        <td className="px-6 py-4">
                                            <span className={cn(
                                                "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase",
                                                job.state === 'RUNNING' ? "bg-green-500/10 text-green-500" :
                                                job.state === 'PENDING' ? "bg-yellow-500/10 text-yellow-500" :
                                                "bg-blue-500/10 text-blue-500"
                                            )}>
                                                {job.state}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 font-mono text-xs">{job.time_used}</td>
                                        <td className="px-6 py-4">{job.nodes}</td>
                                        <td className="px-6 py-4 text-right flex items-center justify-end gap-2">
                                            <button
                                                onClick={() => setSelectedJobId(job.job_id)}
                                                title="View Logs"
                                                className="p-1.5 rounded-md hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors"
                                            >
                                                <Eye className="h-4 w-4" />
                                            </button>
                                            <button
                                                onClick={() => cancelMutation.mutate(job.job_id)}
                                                disabled={cancelMutation.isPending}
                                                title="Cancel Job"
                                                className="p-1.5 rounded-md hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-colors disabled:opacity-50"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </button>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {selectedJobId && (
                <JobLogViewer
                    jobId={selectedJobId}
                    onClose={() => setSelectedJobId(null)}
                />
            )}
        </div>
    );
}
