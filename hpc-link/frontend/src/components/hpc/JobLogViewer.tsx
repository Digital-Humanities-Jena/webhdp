import { useState, useEffect, useRef } from 'react';
import { X, Terminal as TerminalIcon, Download, RefreshCw } from 'lucide-react';
import { getJobLogProtocols, getJobLogUrl } from '../../api/jobs';
import { cn } from '../../lib/utils';

interface JobLogViewerProps {
    jobId: string;
    onClose: () => void;
}

export function JobLogViewer({ jobId, onClose }: JobLogViewerProps) {
    const [logs, setLogs] = useState<string[]>([]);
    const [status, setStatus] = useState<'connecting' | 'connected' | 'error' | 'closed'>('connecting');
    const scrollRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        const url = getJobLogUrl(jobId);
        const ws = new WebSocket(url, getJobLogProtocols());
        wsRef.current = ws;

        ws.onopen = () => {
            setStatus('connected');
            setLogs(['--- Connection established ---']);
        };

        ws.onmessage = (event) => {
            setLogs(prev => [...prev, event.data]);
        };

        ws.onerror = () => {
            setStatus('error');
            setLogs(prev => [...prev, '--- Connection error ---']);
        };

        ws.onclose = () => {
            setStatus('closed');
            setLogs(prev => [...prev, '--- Connection closed ---']);
        };

        return () => {
            ws.close();
        };
    }, [jobId]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    const handleDownload = () => {
        const content = logs.join('\n');
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `job-${jobId}.log`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="w-full max-w-4xl h-[80vh] flex flex-col bg-zinc-950 border border-zinc-800 rounded-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
                <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800 bg-zinc-900/50">
                    <div className="flex items-center gap-3">
                        <TerminalIcon className="h-4 w-4 text-primary" />
                        <h3 className="font-mono text-sm font-medium text-zinc-200">
                            Job {jobId} Output Logs
                        </h3>
                        <span className={cn(
                            "px-2 py-0.5 rounded-full text-[10px] font-bold uppercase",
                            status === 'connected' ? "bg-green-500/10 text-green-500" :
                            status === 'connecting' ? "bg-yellow-500/10 text-yellow-500" :
                            "bg-red-500/10 text-red-500"
                        )}>
                            {status}
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleDownload}
                            className="p-1.5 rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                            title="Download Logs"
                        >
                            <Download className="h-4 w-4" />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-1.5 rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                <div
                    ref={scrollRef}
                    className="flex-1 overflow-auto p-4 font-mono text-xs text-zinc-300 space-y-0.5 bg-black"
                >
                    {logs.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-500">
                            <RefreshCw className="h-8 w-8 animate-spin" />
                            <p>Waiting for log output...</p>
                        </div>
                    )}
                    {logs.map((log, i) => (
                        <div key={i} className="whitespace-pre-wrap border-l border-zinc-800 pl-3 ml-1">
                            {log}
                        </div>
                    ))}
                </div>

                <div className="px-4 py-2 border-t border-zinc-800 bg-zinc-900/30 flex justify-between items-center">
                    <p className="text-[10px] text-zinc-500">
                        {logs.length} lines captured
                    </p>
                    <p className="text-[10px] text-zinc-500">
                        Live tail via SSH
                    </p>
                </div>
            </div>
        </div>
    );
}
