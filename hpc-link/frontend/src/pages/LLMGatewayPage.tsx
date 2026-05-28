import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Bot, Cpu, Loader2, MessageSquare, Play, Send, Square } from 'lucide-react';
import { toast } from 'sonner';

import {
    chatWithVllmSession,
    createVllmSession,
    getVllmSessionStatus,
    listVllmModels,
    stopVllmSession,
} from '../api/apps';
import type { CreateSessionRequest } from '../api/apps';
import { getApiErrorMessage } from '../api/errors';

type ChatLine = {
    role: 'user' | 'assistant';
    content: string;
};

const formatRemaining = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
};

export default function LLMGatewayPage() {
    const [partition, setPartition] = useState('partition-a');
    const [gpuType, setGpuType] = useState('a100');
    const [gpuCount, setGpuCount] = useState(1);
    const [durationMinutes, setDurationMinutes] = useState(30);
    const [selectedModel, setSelectedModel] = useState('');
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [chatInput, setChatInput] = useState('');
    const [messages, setMessages] = useState<ChatLine[]>([]);

    const modelsQuery = useQuery({
        queryKey: ['vllm-models'],
        queryFn: listVllmModels,
        refetchInterval: 15000,
    });

    const createSessionMutation = useMutation({
        mutationFn: (payload: CreateSessionRequest) => createVllmSession(payload),
        onSuccess: (data) => {
            setSessionId(data.session_id);
            setMessages([]);
            toast.success(`Session created (job ${data.job_id})`);
        },
        onError: (error: unknown) => {
            toast.error(getApiErrorMessage(error, 'Could not create session'));
        },
    });

    const statusQuery = useQuery({
        queryKey: ['vllm-session-status', sessionId],
        queryFn: () => getVllmSessionStatus(sessionId as string),
        enabled: !!sessionId,
        refetchInterval: sessionId ? 5000 : false,
    });

    const chatMutation = useMutation({
        mutationFn: (message: string) =>
            chatWithVllmSession(sessionId as string, {
                message,
                temperature: 0.2,
                max_tokens: 256,
            }),
        onSuccess: (data) => {
            setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
        },
        onError: (error: unknown) => {
            toast.error(getApiErrorMessage(error, 'Chat request failed'));
            setMessages((prev) => prev.slice(0, -1));
        },
    });

    const stopSessionMutation = useMutation({
        mutationFn: () => stopVllmSession(sessionId as string),
        onSuccess: (data) => {
            toast.success(data.message);
            setSessionId(null);
        },
        onError: (error: unknown) => {
            toast.error(getApiErrorMessage(error, 'Could not stop session'));
        },
    });

    const activeModelId = useMemo(() => {
        if (selectedModel) {
            return selectedModel;
        }
        const first = modelsQuery.data?.[0]?.model_id;
        return first ?? '';
    }, [modelsQuery.data, selectedModel]);

    const canSend = !!sessionId && statusQuery.data?.scheduler_state === 'RUNNING' && !chatMutation.isPending;

    const handleCreateSession = (event: FormEvent) => {
        event.preventDefault();
        if (!activeModelId) {
            toast.error('No model available');
            return;
        }
        createSessionMutation.mutate({
            model_id: activeModelId,
            partition,
            gpu_type: gpuType || undefined,
            gpu_count: gpuCount,
            duration_minutes: durationMinutes,
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
                <h1 className="text-3xl font-bold tracking-tight">LLM Test Gateway</h1>
                <p className="text-muted-foreground">
                    Allocate a bounded GPU session, select one installed small model, and chat through HPC-Link.
                </p>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
                <div className="rounded-xl border bg-card p-6 shadow-sm lg:col-span-1">
                    <h2 className="mb-4 flex items-center gap-2 font-semibold">
                        <Cpu className="h-4 w-4 text-primary" />
                        Session Allocation
                    </h2>

                    <form className="space-y-4" onSubmit={handleCreateSession}>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Model</label>
                            <select
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                value={activeModelId}
                                onChange={(event) => setSelectedModel(event.target.value)}
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
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Partition</label>
                            <input
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                value={partition}
                                onChange={(event) => setPartition(event.target.value)}
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">GPU Type</label>
                                <input
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                    value={gpuType}
                                    onChange={(event) => setGpuType(event.target.value)}
                                />
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">GPU Count</label>
                                <input
                                    type="number"
                                    min={1}
                                    max={8}
                                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                    value={gpuCount}
                                    onChange={(event) => setGpuCount(Number(event.target.value))}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Duration (minutes)</label>
                            <input
                                type="number"
                                min={5}
                                max={180}
                                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                                value={durationMinutes}
                                onChange={(event) => setDurationMinutes(Number(event.target.value))}
                            />
                        </div>

                        <div className="flex gap-3 pt-2">
                            <button
                                type="submit"
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
                    </form>

                    <div className="mt-6 space-y-2 rounded-lg border bg-background p-3 text-sm">
                        <p>
                            Session: <span className="font-mono">{sessionId ?? '-'}</span>
                        </p>
                        <p>
                            Scheduler State:{' '}
                            <span className="font-semibold">{statusQuery.data?.scheduler_state ?? 'idle'}</span>
                        </p>
                        <p>
                            Time Remaining:{' '}
                            <span className="font-semibold">
                                {statusQuery.data ? formatRemaining(statusQuery.data.remaining_seconds) : '-'}
                            </span>
                        </p>
                    </div>
                </div>

                <div className="rounded-xl border bg-card shadow-sm lg:col-span-2">
                    <div className="flex items-center justify-between border-b px-6 py-4">
                        <h2 className="flex items-center gap-2 font-semibold">
                            <MessageSquare className="h-4 w-4 text-primary" />
                            Chat
                        </h2>
                        <span className="text-xs text-muted-foreground">
                            {canSend ? 'Ready' : 'Waiting for active RUNNING session'}
                        </span>
                    </div>

                    <div className="h-[420px] space-y-3 overflow-auto p-6">
                        {messages.length === 0 && (
                            <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                                Start a session, wait for `RUNNING`, then send a message.
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
                                    {line.role === 'assistant' ? <Bot className="h-3 w-3" /> : <MessageSquare className="h-3 w-3" />}
                                    {line.role}
                                </div>
                                <p className="whitespace-pre-wrap">{line.content}</p>
                            </div>
                        ))}
                        {chatMutation.isPending && (
                            <div className="mr-8 flex items-center gap-2 rounded-lg border bg-background px-4 py-3 text-sm">
                                <Loader2 className="h-4 w-4 animate-spin" /> Generating response...
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
            </div>
        </div>
    );
}
