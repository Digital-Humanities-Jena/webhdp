import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Bot, Loader2, MessageSquare, Play, Send, Square, Text } from 'lucide-react';
import { toast } from 'sonner';

import {
    chatWithVllmSession,
    createVllmSession,
    getVllmSessionStatus,
    listApplications,
    listVllmModels,
    stopVllmSession,
} from '../api/apps';
import type { CreateSessionRequest } from '../api/apps';

type ChatLine = {
    role: 'user' | 'assistant';
    content: string;
};

type LogLevel = 'info' | 'success' | 'event' | 'error';

type LogEntry = {
    id: number;
    timestamp: string;
    level: LogLevel;
    message: string;
};

const DEFAULT_PARTITION = 'partition-a';
const DEFAULT_DURATION_MINUTES = 30;
const DEFAULT_GPU_COUNT = 1;

const formatRemaining = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
};

const formatLogTime = () =>
    new Date().toLocaleTimeString('en-US', {
        hour12: false,
    });

const levelClass: Record<LogLevel, string> = {
    info: 'text-muted-foreground',
    success: 'text-emerald-400',
    event: 'text-blue-400',
    error: 'text-red-400',
};

const extractErrorDetail = (error: unknown, fallback: string) => {
    if (typeof error !== 'object' || error === null) {
        return fallback;
    }
    const withMessage = error as {
        message?: string;
        response?: { data?: { detail?: string } };
    };
    return withMessage.response?.data?.detail ?? withMessage.message ?? fallback;
};

export default function HPCLinktestPage() {
    const [selectedApp, setSelectedApp] = useState('');
    const [selectedModel, setSelectedModel] = useState('');
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [chatInput, setChatInput] = useState('');
    const [messages, setMessages] = useState<ChatLine[]>([]);
    const [logs, setLogs] = useState<LogEntry[]>([]);

    const logCounterRef = useRef(1);
    const lastSchedulerStateRef = useRef<string | null>(null);
    const lastAppIdRef = useRef<string | null>(null);

    const appendLog = useCallback((level: LogLevel, message: string) => {
        setLogs((previous) => {
            const nextEntry: LogEntry = {
                id: logCounterRef.current,
                timestamp: formatLogTime(),
                level,
                message,
            };
            logCounterRef.current += 1;
            const next = [...previous, nextEntry];
            return next.length > 300 ? next.slice(next.length - 300) : next;
        });
    }, []);

    useEffect(() => {
        appendLog('info', 'HPC-Linktest loaded. Discovering pre-specified HPC applications from /apps.');
    }, [appendLog]);

    const appsQuery = useQuery({
        queryKey: ['hpc-linktest-applications'],
        queryFn: listApplications,
        refetchInterval: 20000,
    });

    useEffect(() => {
        if (appsQuery.data) {
            appendLog('event', `Application catalog refreshed (${appsQuery.data.length} apps from HPC-Link).`);
        }
    }, [appendLog, appsQuery.data]);

    useEffect(() => {
        if (appsQuery.error) {
            appendLog('error', 'Failed to refresh application catalog from /apps.');
        }
    }, [appendLog, appsQuery.error]);

    const activeAppId = useMemo(() => {
        if (selectedApp) {
            return selectedApp;
        }
        return appsQuery.data?.[0]?.app_id ?? '';
    }, [appsQuery.data, selectedApp]);

    useEffect(() => {
        if (!activeAppId) {
            return;
        }
        if (activeAppId !== lastAppIdRef.current) {
            appendLog('event', `Active application set to '${activeAppId}'.`);
            lastAppIdRef.current = activeAppId;
        }
    }, [activeAppId, appendLog]);

    const modelsQuery = useQuery({
        queryKey: ['hpc-linktest-vllm-models', activeAppId],
        queryFn: listVllmModels,
        enabled: activeAppId === 'vllm',
        refetchInterval: 15000,
    });

    useEffect(() => {
        if (modelsQuery.data && activeAppId === 'vllm') {
            appendLog('event', `Model list refreshed (${modelsQuery.data.length} entries).`);
        }
    }, [activeAppId, appendLog, modelsQuery.data]);

    useEffect(() => {
        if (modelsQuery.error && activeAppId === 'vllm') {
            appendLog('error', 'Failed to refresh model list from /apps/vllm/models.');
        }
    }, [activeAppId, appendLog, modelsQuery.error]);

    const createSessionMutation = useMutation({
        mutationFn: (payload: CreateSessionRequest) => createVllmSession(payload),
        onMutate: () => {
            appendLog(
                'info',
                `Submitting allocation request for app='${activeAppId}' (partition=${DEFAULT_PARTITION}, duration=${DEFAULT_DURATION_MINUTES}m, gpus=${DEFAULT_GPU_COUNT}).`
            );
        },
        onSuccess: (data) => {
            setSessionId(data.session_id);
            setMessages([]);
            lastSchedulerStateRef.current = null;
            appendLog('success', `Allocation created: session=${data.session_id}, job=${data.job_id}.`);
            toast.success(`Allocation started (job ${data.job_id})`);
        },
        onError: (error: unknown) => {
            const detail = extractErrorDetail(error, 'Could not create session');
            appendLog('error', `Allocation failed: ${detail}`);
            toast.error(detail);
        },
    });

    const statusQuery = useQuery({
        queryKey: ['hpc-linktest-session-status', sessionId],
        queryFn: () => getVllmSessionStatus(sessionId as string),
        enabled: !!sessionId,
        refetchInterval: sessionId ? 5000 : false,
    });

    useEffect(() => {
        if (!statusQuery.data) {
            return;
        }

        const state = statusQuery.data.scheduler_state;
        if (state !== lastSchedulerStateRef.current) {
            const reason = statusQuery.data.scheduler_reason ? ` (reason=${statusQuery.data.scheduler_reason})` : '';
            appendLog('event', `Scheduler state changed to ${state}${reason}.`);
            lastSchedulerStateRef.current = state;
        }
    }, [appendLog, statusQuery.data]);

    useEffect(() => {
        if (statusQuery.error) {
            appendLog('error', 'Session status check failed.');
        }
    }, [appendLog, statusQuery.error]);

    const chatMutation = useMutation({
        mutationFn: (message: string) =>
            chatWithVllmSession(sessionId as string, {
                message,
                temperature: 0.2,
                max_tokens: 256,
            }),
        onMutate: (message) => {
            appendLog('info', `Sending chat prompt (${message.length} chars).`);
        },
        onSuccess: (data) => {
            setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
            appendLog(
                'success',
                `Assistant response received (prompt_tokens=${data.usage_prompt_tokens ?? '-'}, completion_tokens=${data.usage_completion_tokens ?? '-'}).`
            );
        },
        onError: (error: unknown) => {
            const detail = extractErrorDetail(error, 'Chat request failed');
            appendLog('error', `Chat request failed: ${detail}`);
            toast.error(detail);
        },
    });

    const stopSessionMutation = useMutation({
        mutationFn: () => stopVllmSession(sessionId as string),
        onMutate: () => {
            appendLog('info', 'Releasing current allocation via scancel.');
        },
        onSuccess: (data) => {
            appendLog('success', `Release request completed: ${data.message}`);
            toast.success(data.message);
            setSessionId(null);
            lastSchedulerStateRef.current = null;
        },
        onError: (error: unknown) => {
            const detail = extractErrorDetail(error, 'Could not stop session');
            appendLog('error', `Release failed: ${detail}`);
            toast.error(detail);
        },
    });

    const activeModelId = useMemo(() => {
        if (selectedModel) {
            return selectedModel;
        }
        return modelsQuery.data?.[0]?.model_id ?? '';
    }, [modelsQuery.data, selectedModel]);

    const canSend =
        activeAppId === 'vllm' &&
        !!sessionId &&
        statusQuery.data?.scheduler_state === 'RUNNING' &&
        !chatMutation.isPending;
    const chatReadinessText =
        activeAppId !== 'vllm'
            ? 'Selected app is not wired for chat in this demo'
            : canSend
              ? 'Ready'
              : 'Waiting for RUNNING allocation';

    const handleAllocate = () => {
        if (!activeAppId) {
            appendLog('error', 'Allocation blocked because no application is available.');
            toast.error('No application available');
            return;
        }

        if (activeAppId !== 'vllm') {
            appendLog(
                'error',
                `Allocation for app '${activeAppId}' is not wired in this demo yet. Currently supported runtime: vllm.`
            );
            toast.error(`App '${activeAppId}' is not wired yet in this demo`);
            return;
        }

        if (!activeModelId) {
            appendLog('error', 'Allocation blocked because no model is available.');
            toast.error('No model available');
            return;
        }

        createSessionMutation.mutate({
            model_id: activeModelId,
            partition: DEFAULT_PARTITION,
            gpu_count: DEFAULT_GPU_COUNT,
            duration_minutes: DEFAULT_DURATION_MINUTES,
        });
    };

    const handleSend = (event: FormEvent) => {
        event.preventDefault();
        const message = chatInput.trim();
        if (!message || !canSend) {
            return;
        }

        setMessages((prev) => [...prev, { role: 'user', content: message }]);
        setChatInput('');
        chatMutation.mutate(message);
    };

    return (
        <div className="mx-auto max-w-6xl space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">HPC-Linktest</h1>
                <p className="text-muted-foreground">
                    Demonstrates how any pre-specified application can use HPC-Link for allocation and execution.
                    This demo currently runs the pre-specified <span className="font-mono">vllm</span> runtime.
                </p>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
                <div className="rounded-xl border bg-card p-6 shadow-sm lg:col-span-1">
                    <h2 className="mb-4 flex items-center gap-2 font-semibold">
                        <Play className="h-4 w-4 text-primary" />
                        Allocation Control
                    </h2>

                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Application</label>
                            <select
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                value={activeAppId}
                                onChange={(event) => setSelectedApp(event.target.value)}
                                disabled={!!sessionId}
                            >
                                {appsQuery.isLoading && <option>Loading applications...</option>}
                                {!appsQuery.isLoading &&
                                    appsQuery.data?.map((app) => (
                                        <option key={app.app_id} value={app.app_id}>
                                            {app.name} ({app.app_id})
                                        </option>
                                    ))}
                            </select>
                            <p className="text-xs text-muted-foreground">
                                Catalog source: <span className="font-mono">GET /apps</span>
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Model</label>
                            <select
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                value={activeModelId}
                                onChange={(event) => setSelectedModel(event.target.value)}
                                disabled={activeAppId !== 'vllm'}
                            >
                                {modelsQuery.isLoading && <option>Loading models...</option>}
                                {!modelsQuery.isLoading &&
                                    modelsQuery.data?.map((model) => (
                                        <option key={model.model_id} value={model.model_id}>
                                            {model.label}
                                            {model.installed === false ? ' (missing)' : ''}
                                        </option>
                                    ))}
                            </select>
                            {activeAppId !== 'vllm' && (
                                <p className="text-xs text-muted-foreground">
                                    This demo currently maps model-backed allocation only for <span className="font-mono">vllm</span>.
                                </p>
                            )}
                        </div>

                        <div className="rounded-lg border bg-background p-3 text-sm">
                            <p>
                                Selected app: <span className="font-semibold">{activeAppId || '-'}</span>
                            </p>
                            <p>
                                Partition: <span className="font-semibold">{DEFAULT_PARTITION}</span>
                            </p>
                            <p>
                                Duration: <span className="font-semibold">{DEFAULT_DURATION_MINUTES} minutes</span>
                            </p>
                            <p>
                                GPU count: <span className="font-semibold">{DEFAULT_GPU_COUNT}</span>
                            </p>
                        </div>

                        <div className="flex gap-3">
                            <button
                                type="button"
                                onClick={handleAllocate}
                                disabled={createSessionMutation.isPending || !!sessionId}
                                className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                            >
                                {createSessionMutation.isPending ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Play className="h-4 w-4" />
                                )}
                                Allocate
                            </button>
                            <button
                                type="button"
                                disabled={!sessionId || stopSessionMutation.isPending}
                                onClick={() => stopSessionMutation.mutate()}
                                className="flex flex-1 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
                            >
                                {stopSessionMutation.isPending ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Square className="h-4 w-4" />
                                )}
                                Release
                            </button>
                        </div>
                    </div>

                    <div className="mt-6 space-y-2 rounded-lg border bg-background p-3 text-sm">
                        <p>
                            Session: <span className="font-mono">{sessionId ?? '-'}</span>
                        </p>
                        <p>
                            Scheduler: <span className="font-semibold">{statusQuery.data?.scheduler_state ?? 'idle'}</span>
                        </p>
                        <p>
                            Remaining:{' '}
                            <span className="font-semibold">
                                {statusQuery.data ? formatRemaining(statusQuery.data.remaining_seconds) : '-'}
                            </span>
                        </p>
                    </div>
                </div>

                <div className="space-y-6 lg:col-span-2">
                    <div className="rounded-xl border bg-card shadow-sm">
                        <div className="flex items-center justify-between border-b px-6 py-4">
                            <h2 className="flex items-center gap-2 font-semibold">
                                <MessageSquare className="h-4 w-4 text-primary" />
                                Chat Interface
                            </h2>
                            <span className="text-xs text-muted-foreground">{chatReadinessText}</span>
                        </div>

                        <div className="h-[360px] space-y-3 overflow-auto p-6">
                            {messages.length === 0 && (
                                <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                                    Allocate first, wait for `RUNNING`, then send a prompt.
                                </div>
                            )}

                            {messages.map((line, index) => (
                                <div
                                    key={`${line.role}-${index}`}
                                    className={`rounded-lg px-4 py-3 text-sm ${
                                        line.role === 'user'
                                            ? 'ml-8 bg-primary text-primary-foreground'
                                            : 'mr-8 border bg-background'
                                    }`}
                                >
                                    <div className="mb-1 flex items-center gap-2 text-xs opacity-80">
                                        {line.role === 'assistant' ? (
                                            <Bot className="h-3 w-3" />
                                        ) : (
                                            <MessageSquare className="h-3 w-3" />
                                        )}
                                        {line.role}
                                    </div>
                                    <p className="whitespace-pre-wrap">{line.content}</p>
                                </div>
                            ))}

                            {chatMutation.isPending && (
                                <div className="mr-8 flex items-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm">
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                    Waiting for model response...
                                </div>
                            )}
                        </div>

                        <form className="border-t p-4" onSubmit={handleSend}>
                            <div className="flex gap-3">
                                <input
                                    className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
                                    placeholder="Type your prompt..."
                                    value={chatInput}
                                    onChange={(event) => setChatInput(event.target.value)}
                                    disabled={!canSend}
                                />
                                <button
                                    type="submit"
                                    disabled={!canSend || chatInput.trim().length === 0}
                                    className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                                >
                                    <Send className="h-4 w-4" />
                                    Send
                                </button>
                            </div>
                        </form>
                    </div>

                    <div className="rounded-xl border bg-card shadow-sm">
                        <div className="flex items-center justify-between border-b px-6 py-4">
                            <h2 className="flex items-center gap-2 font-semibold">
                                <Text className="h-4 w-4 text-primary" />
                                Detailed Log
                            </h2>
                            <button
                                type="button"
                                className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                                onClick={() => setLogs([])}
                            >
                                Clear
                            </button>
                        </div>
                        <div className="h-[220px] space-y-1 overflow-auto bg-zinc-950 px-4 py-3 font-mono text-xs text-zinc-200">
                            {logs.length === 0 && <p className="text-zinc-500">No log entries yet.</p>}
                            {logs.map((entry) => (
                                <p key={entry.id} className="break-words">
                                    <span className="text-zinc-500">[{entry.timestamp}]</span>{' '}
                                    <span className={levelClass[entry.level]}>[{entry.level.toUpperCase()}]</span>{' '}
                                    <span>{entry.message}</span>
                                </p>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
