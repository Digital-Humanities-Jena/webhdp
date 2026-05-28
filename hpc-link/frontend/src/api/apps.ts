import api from './client';

export interface ApplicationDescriptor {
    app_id: string;
    name: string;
    description: string;
}

export interface VllmModelDescriptor {
    model_id: string;
    label: string;
    path: string;
    installed?: boolean | null;
}

export interface CreateSessionRequest {
    model_id: string;
    partition?: string;
    gpu_type?: string;
    gpu_count: number;
    duration_minutes: number;
}

export interface SessionCreateResponse {
    session_id: string;
    app_id: string;
    model_id: string;
    model_label: string;
    job_id: string;
    remote_session_dir: string;
    status: string;
    created_at: string;
    expires_at: string;
}

export interface SessionStatusResponse {
    session_id: string;
    app_id: string;
    model_id: string;
    model_label: string;
    job_id: string;
    status: string;
    scheduler_state: string;
    scheduler_reason?: string;
    created_at: string;
    expires_at: string;
    remaining_seconds: number;
}

export interface ChatRequest {
    message: string;
    temperature: number;
    max_tokens: number;
}

export interface ChatResponse {
    session_id: string;
    model_id: string;
    reply: string;
    usage_prompt_tokens?: number;
    usage_completion_tokens?: number;
}

export interface SessionStopResponse {
    session_id: string;
    job_id: string;
    cancelled: boolean;
    message: string;
}

export const listApplications = async (): Promise<ApplicationDescriptor[]> => {
    const response = await api.get<ApplicationDescriptor[]>('/apps');
    return response.data;
};

export const listVllmModels = async (): Promise<VllmModelDescriptor[]> => {
    const response = await api.get<VllmModelDescriptor[]>('/apps/vllm/models');
    return response.data;
};

export const createVllmSession = async (
    request: CreateSessionRequest
): Promise<SessionCreateResponse> => {
    const response = await api.post<SessionCreateResponse>('/apps/vllm/sessions', request);
    return response.data;
};

export const getVllmSessionStatus = async (sessionId: string): Promise<SessionStatusResponse> => {
    const response = await api.get<SessionStatusResponse>(`/apps/vllm/sessions/${sessionId}`);
    return response.data;
};

export const chatWithVllmSession = async (
    sessionId: string,
    request: ChatRequest
): Promise<ChatResponse> => {
    const response = await api.post<ChatResponse>(`/apps/vllm/sessions/${sessionId}/chat`, request);
    return response.data;
};

export const stopVllmSession = async (sessionId: string): Promise<SessionStopResponse> => {
    const response = await api.delete<SessionStopResponse>(`/apps/vllm/sessions/${sessionId}`);
    return response.data;
};
