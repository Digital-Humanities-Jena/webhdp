import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listFiles, deleteFile, uploadFile, downloadFile, type FileStat } from '../api/files';
import { Loader2, RefreshCw, Home, Upload, AlertCircle } from 'lucide-react';
import { FileExplorer } from '../components/files/FileExplorer';
import { Breadcrumbs } from '../components/files/Breadcrumbs';

export default function FileManagerPage() {
    const [currentPath, setCurrentPath] = useState('/');
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const queryClient = useQueryClient();

    // Handle path not starting with /
    const safeCurrentPath = currentPath.startsWith('/') ? currentPath : '/' + currentPath;

    const { data, isLoading, error } = useQuery({
        queryKey: ['files', safeCurrentPath],
        queryFn: () => listFiles(safeCurrentPath),
        retry: 1,
    });

    const deleteMutation = useMutation({
        mutationFn: deleteFile,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['files', safeCurrentPath] });
        },
    });

    const handleNavigate = (path: string) => {
        setCurrentPath(path);
    };

    const handleDelete = async (file: FileStat) => {
        if (confirm(`Are you sure you want to delete ${file.name}?`)) {
            deleteMutation.mutate(file.path);
        }
    };

    const handleDownload = async (file: FileStat) => {
        try {
            await downloadFile(file.path);
        } catch (e) {
            console.error("Download failed", e);
            alert("Failed to download file");
        }
    };

    const handleUploadClick = () => {
        fileInputRef.current?.click();
    };

    const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        setUploading(true);
        setUploadProgress(0);

        try {
            await uploadFile(file, safeCurrentPath === '/' ? '' : safeCurrentPath, (progress) => {
                setUploadProgress(progress);
            });
            queryClient.invalidateQueries({ queryKey: ['files', safeCurrentPath] });
            // Reset input
            if (fileInputRef.current) fileInputRef.current.value = '';
        } catch (e) {
            console.error("Upload failed", e);
            alert("Failed to upload file");
        } finally {
            setUploading(false);
        }
    };

    return (
        <div className="flex flex-col h-full p-6 space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold tracking-tight">File Manager</h1>
                <div className="flex items-center space-x-2">
                    <input
                        type="file"
                        ref={fileInputRef}
                        className="hidden"
                        onChange={handleFileChange}
                    />
                    <button
                        onClick={handleUploadClick}
                        disabled={uploading}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                    >
                        {uploading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Upload className="h-4 w-4" />
                        )}
                        {uploading ? `${Math.round(uploadProgress)}%` : 'Upload'}
                    </button>
                    <button
                        onClick={() => queryClient.invalidateQueries({ queryKey: ['files'] })}
                        className="p-2 hover:bg-secondary rounded-md border"
                        title="Refresh"
                    >
                        <RefreshCw className="h-4 w-4" />
                    </button>
                </div>
            </div>

            <div className="flex items-center space-x-2 text-sm text-muted-foreground bg-card border p-2 rounded-md">
                <button onClick={() => setCurrentPath('/')} className="hover:text-primary transition-colors">
                    <Home className="h-4 w-4" />
                </button>
                <span className="text-muted-foreground/50">/</span>
                <Breadcrumbs path={safeCurrentPath} onNavigate={handleNavigate} />
            </div>

            <div className="flex-1 rounded-lg border bg-card shadow-sm overflow-hidden flex flex-col min-h-[400px]">
                {isLoading ? (
                    <div className="flex-1 flex items-center justify-center">
                        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                ) : error ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-destructive p-4 space-y-2">
                        <AlertCircle className="h-8 w-8" />
                        <p className="font-semibold">Error loading files</p>
                        <p className="text-sm">{(error as Error).message}</p>
                    </div>
                ) : (
                    <FileExplorer
                        files={data?.entries || []}
                        onNavigate={handleNavigate}
                        onDelete={handleDelete}
                        onDownload={handleDownload}
                    />
                )}
            </div>
        </div>
    );
}
