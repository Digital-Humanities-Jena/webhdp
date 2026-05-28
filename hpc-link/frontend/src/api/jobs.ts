import api from './client';
import { getStoredAuthToken } from '../auth/tokenStorage';

export interface JobConfig {
    job_name: string;
    partition: string;
    time_limit: string;
    nodes: number;
    tasks_per_node: number;
    cpus_per_task: number;
    memory: string;
    gpu_type?: string;
    gpu_count: number;
    output_path: string;
    error_path: string;
    working_dir?: string;
    modules: string[];
    environment_vars: Record<string, string>;
    commands: string[];
    use_uv: boolean;
    uv_install: boolean;
    webhook_url?: string;
}

export interface JobStatus {
    job_id: string;
    name: string;
    partition: string;
    state: string;
    time_used: string;
    nodes: number;
    reason?: string;
}

export interface JobSubmissionResponse {
    job_id: string;
    message: string;
    script_path: string;
}

export const listJobs = async (): Promise<JobStatus[]> => {
    const response = await api.get<JobStatus[]>('/jobs/');
    return response.data;
};

export const getJobStatus = async (jobId: string): Promise<JobStatus> => {
    const response = await api.get<JobStatus>(`/jobs/${jobId}`);
    return response.data;
};

export const submitJob = async (config: JobConfig): Promise<JobSubmissionResponse> => {
    const response = await api.post<JobSubmissionResponse>('/jobs/submit', config);
    return response.data;
};

export const cancelJob = async (jobId: string): Promise<void> => {
    await api.delete(`/jobs/${jobId}`);
};

export const getJobLogUrl = (jobId: string): string => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = import.meta.env.VITE_API_URL
        ? import.meta.env.VITE_API_URL.replace(/^https?:\/\//, '')
        : window.location.host;
    return `${protocol}//${host}/api/jobs/${jobId}/logs`;
};

export const getJobLogProtocols = (): string[] => {
    const token = getStoredAuthToken();
    if (!token) {
        return ['hpc-link-v1'];
    }
    return ['hpc-link-v1', `bearer.${token}`];
};
