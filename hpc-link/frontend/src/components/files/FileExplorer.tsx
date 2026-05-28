import type { FileStat } from '../../api/files';
import { Folder, Download, Trash2, File as FileIcon } from 'lucide-react';

interface FileExplorerProps {
    files: FileStat[];
    onNavigate: (path: string) => void;
    onDelete: (file: FileStat) => void;
    onDownload: (file: FileStat) => void;
}

function formatBytes(bytes: number, decimals = 2) {
    if (!+bytes) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

function formatDate(timestamp: number) {
    return new Date(timestamp * 1000).toLocaleString();
}

export function FileExplorer({ files, onNavigate, onDelete, onDownload }: FileExplorerProps) {
    const sortedFiles = [...files].sort((a, b) => {
        if (a.is_dir === b.is_dir) {
            return a.name.localeCompare(b.name);
        }
        return a.is_dir ? -1 : 1;
    });

    return (
        <div className="w-full overflow-auto">
            <table className="w-full text-sm text-left">
                <thead className="bg-muted/50 text-muted-foreground sticky top-0">
                    <tr>
                        <th className="px-4 py-3 font-medium w-8">Type</th>
                        <th className="px-4 py-3 font-medium">Name</th>
                        <th className="px-4 py-3 font-medium w-32">Size</th>
                        <th className="px-4 py-3 font-medium w-48">Modified</th>
                        <th className="px-4 py-3 font-medium w-32 text-right">Actions</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-border">
                    {sortedFiles.length === 0 ? (
                        <tr>
                            <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                                This directory is empty.
                            </td>
                        </tr>
                    ) : (
                        sortedFiles.map((file) => (
                            <tr
                                key={file.path}
                                className="group hover:bg-muted/50 transition-colors"
                            >
                                <td className="px-4 py-3">
                                    {file.is_dir ? (
                                        <Folder className="h-5 w-5 text-blue-500 fill-blue-500/20" />
                                    ) : (
                                        <FileIcon className="h-5 w-5 text-gray-500" />
                                    )}
                                </td>
                                <td className="px-4 py-3 font-medium">
                                    {file.is_dir ? (
                                        <button
                                            onClick={() => onNavigate(file.path)}
                                            className="hover:underline hover:text-primary text-left w-full truncate"
                                        >
                                            {file.name}
                                        </button>
                                    ) : (
                                        <span className="text-foreground truncate block">{file.name}</span>
                                    )}
                                </td>
                                <td className="px-4 py-3 text-muted-foreground">
                                    {file.is_dir ? '-' : formatBytes(file.size)}
                                </td>
                                <td className="px-4 py-3 text-muted-foreground">
                                    {formatDate(file.mtime)}
                                </td>
                                <td className="px-4 py-3 text-right">
                                    <div className="flex items-center justify-end space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                        {!file.is_dir && (
                                            <button
                                                onClick={() => onDownload(file)}
                                                className="p-1 hover:bg-secondary rounded text-muted-foreground hover:text-foreground"
                                                title="Download"
                                            >
                                                <Download className="h-4 w-4" />
                                            </button>
                                        )}
                                        <button
                                            onClick={() => onDelete(file)}
                                            className="p-1 hover:bg-destructive/10 rounded text-muted-foreground hover:text-destructive"
                                            title="Delete"
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
}
