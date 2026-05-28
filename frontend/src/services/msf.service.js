// services/msf.service.js
// Service for Metadata Source File (MSF) operations

import api from './api'

const msfService = {
    /**
     * Upload an MSF file and get its server-side path
     * @param {File} file - The MSF file to upload
     * @returns {Promise} Response with msf_path for subsequent operations
     */
    async uploadMsfFile(file) {
        const formData = new FormData()
        formData.append('file', file)
        return api.post('/msf/upload', formData)
    },

    /**
     * Parse an MSF file and get column preview
     * @param {string} msfPath - Server-side path to the MSF file
     * @returns {Promise} Response with columns and preview data
     */
    async parseMsfFile(msfPath) {
        return api.post('/msf/parse', { msf_path: msfPath })
    },

    /**
     * Validate MSF against a directory
     * @param {string} msfPath - Server-side path to the MSF file
     * @param {string} directoryPath - Path to the directory
     * @param {string} filenameColumn - Optional filename column name
     * @returns {Promise} Validation results
     */
    async validateMsf(msfPath, directoryPath, filenameColumn = null) {
        return api.post('/msf/validate', {
            msf_path: msfPath,
            directory_path: directoryPath,
            filename_column: filenameColumn
        })
    },

    /**
     * Auto-detect the filename column
     * @param {string} msfPath - Server-side path to the MSF file
     * @param {string} directoryPath - Path to the directory
     * @returns {Promise} Detection result with column name and confidence
     */
    async detectFilenameColumn(msfPath, directoryPath) {
        return api.post('/msf/detect-filename-column', {
            msf_path: msfPath,
            directory_path: directoryPath
        })
    },

    /**
     * Get default column mapping
     * @returns {Promise} Default mapping configuration
     */
    async getDefaultMapping() {
        return api.get('/msf/default-mapping')
    },

    /**
     * Get metadata for specific files from MSF
     * @param {string} msfPath - Server-side path to the MSF file
     * @param {string[]} filenames - List of filenames
     * @param {string} filenameColumn - Optional filename column
     * @param {Object} columnMapping - Optional custom column mapping
     * @returns {Promise} Metadata for each file
     */
    async getMetadataForFiles(msfPath, filenames, filenameColumn = null, columnMapping = null) {
        const payload = {
            msf_path: msfPath,
            filenames
        }
        if (filenameColumn) payload.filename_column = filenameColumn
        if (columnMapping) payload.column_mapping = columnMapping

        return api.post('/msf/metadata-for-files', payload)
    },

    /**
     * Analyze and optionally patch an MSF file for ingestion readiness.
     * @param {Object} payload - Patch request payload
     * @returns {Promise} Patch report
     */
    async patchMsf(payload) {
        return api.post('/msf/patch', payload)
    },

    /**
     * Analyze the workflow session MSF and optionally apply selected fixes.
     * @param {number} sessionId
     * @param {Object} payload
     * @returns {Promise}
     */
    async analyzeWorkflowSessionMsf(sessionId, payload = {}) {
        return api.post(`/msf/workflow/session/${sessionId}/analyze`, payload)
    },

    /**
     * Prepare a local workflow session so the MSF can be repaired before scanning.
     * @param {Object} payload
     * @returns {Promise}
     */
    async prepareLocalWorkflowSession(payload) {
        return api.post('/msf/workflow/local/prepare', payload)
    },

    /**
     * Start the real local directory scan for a prepared workflow session.
     * @param {number} sessionId
     * @returns {Promise}
     */
    async startLocalWorkflowScan(sessionId) {
        return api.post(`/msf/workflow/session/${sessionId}/start-local-scan`, {})
    },

    /**
     * Fetch local validator context (availability, storage mode, local MSF list).
     * @returns {Promise}
     */
    async getLocalValidatorContext() {
        return api.get('/msf/tools/local/context')
    },

    /**
     * Run local validator checks and operations.
     * @param {Object} payload - validator payload
     * @returns {Promise}
     */
    async validateLocalMsf(payload) {
        return api.post('/msf/tools/local/validate', payload)
    },

    /**
     * Export local validator result as CSV or XLSX.
     * @param {Object} payload - validator payload + format
     * @returns {Promise<Blob>}
     */
    async exportLocalMsf(payload) {
        const token = sessionStorage.getItem('token')
        const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:5000/api/v1'
        const response = await fetch(`${baseURL}/msf/tools/local/export`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token && token !== 'null' && token !== 'undefined'
                    ? { Authorization: `Bearer ${token}` }
                    : {})
            },
            body: JSON.stringify(payload)
        })

        if (!response.ok) {
            let errorMessage = `Export failed (${response.status})`
            try {
                const errorPayload = await response.json()
                errorMessage =
                    errorPayload?.error?.message ||
                    errorPayload?.message ||
                    errorMessage
            } catch (e) {
                // Ignore JSON parse errors and keep fallback message.
            }
            throw new Error(errorMessage)
        }

        const blob = await response.blob()
        const contentDisposition = response.headers.get('content-disposition') || ''
        const filenameMatch = contentDisposition.match(/filename=\"?([^\";]+)\"?/)
        const filename = filenameMatch?.[1] || `msf.validator.${payload?.format || 'xlsx'}`
        return { blob, filename }
    }
}

export default msfService
