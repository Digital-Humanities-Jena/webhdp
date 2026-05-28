import api from './client';

export interface FileStat {
    name: string;
    path: string;
    size: number;
    mtime: number;
    is_dir: boolean;
    permissions: string;
}

export interface FileListResponse {
    entries: FileStat[];
    path: string;
}

export const listFiles = async (path: string = ''): Promise<FileListResponse> => {
    const response = await api.get<FileListResponse>('/files/list', { params: { path } });
    return response.data;
};

export const getFileStat = async (path: string): Promise<FileStat> => {
    const response = await api.get('/files/stat', { params: { path } });
    return response.data;
};

export const createDirectory = async (path: string): Promise<void> => {
    await api.post('/files/mkdir', { path });
};

export const deleteFile = async (path: string): Promise<void> => {
    await api.delete('/files', { params: { path } });
};

export const downloadFile = async (path: string) => {
    const response = await api.get('/files/download', {
        params: { path },
        responseType: 'blob',
    });

    // Create a blob link to download
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    const fileName = path.split('/').pop() || 'download';
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
};

// Upload Types
interface UploadInitResponse {
    upload_id: string;
}

const CHUNK_SIZE = 1024 * 1024 * 5; // 5MB chunks

export const uploadFile = async (
    file: File,
    path: string,
    onProgress?: (progress: number) => void
): Promise<void> => {
    const targetPath = path ? `${path}/${file.name}` : file.name;

    // 1. Init upload
    // Note: Adjust the payload based on actual backend expectation.
    // Assuming it might expect 'path' as query param or body.
    // Checking plan: POST /files/upload/init - Initialize upload, open SFTP temp file
    const initRes = await api.post<UploadInitResponse>('/files/upload/init', { path: targetPath });
    const { upload_id } = initRes.data;

    // 2. Upload chunks
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

    for (let i = 0; i < totalChunks; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);

        await api.put(`/files/upload/${upload_id}`, chunk, {
            params: { chunk: i },
            headers: {
                'Content-Type': 'application/octet-stream',
            },
            onUploadProgress: (progressEvent) => {
                if (progressEvent.total) {
                    // Calculate total progress across all chunks
                    // This is a simplified progress calculation
                    const chunkProgress = (progressEvent.loaded / progressEvent.total);
                    const totalProgress = ((i + chunkProgress) / totalChunks) * 100;
                    if (onProgress) onProgress(Math.min(totalProgress, 100));
                }
            }
        });
    }

    // 3. Finish upload
    await api.post(`/files/upload/${upload_id}/finish`);
    if (onProgress) onProgress(100);
};
