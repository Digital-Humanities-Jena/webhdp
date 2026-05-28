import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { getStoredAuthToken } from '../auth/tokenStorage';

export default function TerminalPage() {
    const terminalRef = useRef<HTMLDivElement>(null);
    const xtermRef = useRef<Terminal | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const fitAddonRef = useRef<FitAddon | null>(null);

    useEffect(() => {
        if (!terminalRef.current) return;

        // Initialize xterm.js
        const term = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            theme: {
                background: '#1a1a1a',
                foreground: '#f0f0f0',
            },
        });

        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);

        term.open(terminalRef.current);
        fitAddon.fit();

        xtermRef.current = term;
        fitAddonRef.current = fitAddon;

        // Connect to WebSocket via Vite proxy
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const token = getStoredAuthToken();
        const subprotocols = token ? ['hpc-link-v1', `bearer.${token}`] : ['hpc-link-v1'];
        const socket = new WebSocket(
            `${protocol}//${host}/api/ws/terminal?cols=${term.cols}&rows=${term.rows}`,
            subprotocols
        );

        socket.binaryType = 'arraybuffer';
        wsRef.current = socket;

        // Handle incoming SSH output
        socket.onmessage = (event) => {
            if (typeof event.data === 'string') {
                // Handle potential control messages if any
            } else {
                term.write(new Uint8Array(event.data));
            }
        };

        socket.onopen = () => {
            term.writeln('Connected to HPC Link Terminal');
        };

        socket.onclose = () => {
            term.writeln('\r\nConnection closed.');
        };

        socket.onerror = () => {
            term.writeln('\r\nWebSocket error occurred.');
        };

        // Handle user input
        term.onData((data) => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(data);
            }
        });

        // Handle resizing
        const handleResize = () => {
            fitAddon.fit();
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    type: 'resize',
                    cols: term.cols,
                    rows: term.rows
                }));
            }
        };

        const resizeObserver = new ResizeObserver(() => {
            handleResize();
        });
        resizeObserver.observe(terminalRef.current);

        return () => {
            socket.close();
            term.dispose();
            resizeObserver.disconnect();
        };
    }, []);

    return (
        <div className="h-full flex flex-col space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Terminal</h1>
                    <p className="text-muted-foreground">Interactive shell session on the HPC login node.</p>
                </div>
            </div>

            <div className="flex-1 min-h-0 rounded-xl border bg-[#1a1a1a] p-4 shadow-sm overflow-hidden">
                <div ref={terminalRef} className="h-full w-full" />
            </div>
        </div>
    );
}
