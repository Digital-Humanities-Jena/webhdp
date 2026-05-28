import api from './client';

export interface PartitionInfo {
    partition: string;
    nodes: string;
    available: string;
    node_count: string;
    gres: string;
    state: string;
}

export interface PartitionsResponse {
    partitions: PartitionInfo[];
}

export interface GPUAllocationRequest {
    command: string;
    partition?: string;
    gpu_type?: string;
    gpu_count?: number;
    time_limit?: string;
}

export interface CommandResponse {
    stdout: string;
    stderr: string;
    exit_code: number;
    success: boolean;
}

export interface NvidiaSmiResponse {
    success: boolean;
    output: string;
    gpu_name?: string;
    gpu_memory?: string;
    partition: string;
    error?: string;
}

export const listPartitions = async (): Promise<PartitionsResponse> => {
    const response = await api.get<PartitionsResponse>('/hpc/partitions');
    return response.data;
};

export const allocateGPU = async (request: GPUAllocationRequest): Promise<CommandResponse> => {
    const response = await api.post<CommandResponse>('/hpc/allocate', request);
    return response.data;
};

export const runNvidiaSmi = async (partition?: string, gpu_type?: string): Promise<NvidiaSmiResponse> => {
    const response = await api.get<NvidiaSmiResponse>('/hpc/nvidia-smi', {
        params: { partition, gpu_type }
    });
    return response.data;
};
