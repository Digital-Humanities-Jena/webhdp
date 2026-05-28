/**
 * app.js
 *
 * This file controls all frontend logic.
 * It is structured as a single 'App' object, which is initialized
 * when the DOM is fully loaded. This avoids polluting the global scope.
 */
document.addEventListener('DOMContentLoaded', () => {

    const App = {
        // ---
        // 1. DOM Element References
        // ---
        nodes: {
            fileListContainer: document.getElementById('file-list-container'),
            fileListHeader: document.getElementById('file-list-header'),
            fileListPlaceholder: document.getElementById('file-list-placeholder'),
            uploadBtn: document.getElementById('upload-btn'),
            uploadFileBtn: document.getElementById('upload-file-btn'),

            // Progress Modal
            progressModal: document.getElementById('progress-modal'),
            modalSpinner: document.getElementById('modal-spinner'),
            modalMessage: document.getElementById('modal-message'),
            modalSubMessage: document.getElementById('modal-sub-message'),
            modalErrorIcon: document.getElementById('modal-icon-error'),
            modalSuccessIcon: document.getElementById('modal-icon-success'),
            modalCloseBtn: document.getElementById('modal-close-btn'),

            // Path Modal
            pathModal: document.getElementById('path-modal'),
            pathModalTitle: document.getElementById('path-modal-title'),
            pathModalInput: document.getElementById('path-modal-input'),
            pathModalCancelBtn: document.getElementById('path-modal-cancel-btn'),
            pathModalSubmitBtn: document.getElementById('path-modal-submit-btn'),
            pathModalDesc: document.getElementById('path-modal-desc'),

            // Validation Modal
            validationModal: document.getElementById('validation-modal'),
            validationModalTitle: document.getElementById('validation-modal-title'),
            validationModalStatusBadge: document.getElementById('validation-modal-status-badge'),
            validationModalChildrenContainer: document.getElementById('validation-modal-children-container'),
            validationModalChildren: document.getElementById('validation-modal-children'),
            validationModalCloseBtn: document.getElementById('validation-modal-close-btn')
        },

        // ---
        // 2. Application State
        // ---
        state: {
            pathModalPromise: { resolve: null, reject: null }
        },

        // ---
        // 3. API Helper
        // ---
        api: {
            async startDirectorySession(directoryPath) {
                const response = await fetch('/start-session-directory', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ input_directory_path: directoryPath })
                });
                const result = await response.json();

                // Handle new API response format
                if (!response.ok) {
                    const errorMsg = result.error?.message || result.error || 'Failed to start session.';
                    throw new Error(errorMsg);
                }

                // Return the data property for consistent handling
                return result.data || result;
            },

            async startFileSession(file) {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/start-session-file', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();

                // Handle new API response format
                if (!response.ok) {
                    const errorMsg = result.error?.message || result.error || 'Failed to process file.';
                    throw new Error(errorMsg);
                }

                // Return the data property for consistent handling
                return result.data || result;
            }
        },

        // ---
        // 4. UI / Modal Helpers
        // ---
        ui: {
            showModal(state, message = '') {
                const n = App.nodes;
                n.modalSpinner.style.display = 'none';
                n.modalErrorIcon.style.display = 'none';
                n.modalSuccessIcon.style.display = 'none';
                n.modalCloseBtn.style.display = 'none';

                switch (state) {
                    case 'scanning':
                        n.modalSpinner.style.display = 'block';
                        n.modalMessage.textContent = 'Scanning...';
                        n.modalSubMessage.textContent = 'Please wait while your files are being analyzed.';
                        break;
                    case 'processing':
                        n.modalSpinner.style.display = 'block';
                        n.modalMessage.textContent = 'Processing...';
                        n.modalSubMessage.textContent = 'Please wait.';
                        break;
                    case 'success':
                        n.modalSuccessIcon.style.display = 'block';
                        n.modalMessage.textContent = 'Success!';
                        n.modalSubMessage.textContent = message || 'Operation completed successfully.';
                        n.modalCloseBtn.style.display = 'block';
                        break;
                    case 'error':
                        n.modalErrorIcon.style.display = 'block';
                        n.modalMessage.textContent = 'Error';
                        n.modalSubMessage.textContent = message || 'An unknown error occurred.';
                        n.modalCloseBtn.style.display = 'block';
                        break;
                }
                n.progressModal.style.display = 'flex';
            },

            hideModal() {
                App.nodes.progressModal.style.display = 'none';
            },

            showPathModal(mode) {
                return new Promise((resolve, reject) => {
                    App.state.pathModalPromise = { resolve, reject };
                    const n = App.nodes;
                    if (mode === 'directory') {
                        n.pathModalTitle.textContent = 'Select Directory Path';
                        n.pathModalInput.placeholder = 'e.g., C:\\Users\\YourName\\MyProject';
                        n.pathModalDesc.textContent = 'Please paste the absolute path to the directory you want to scan. All supported files in this directory will be processed.';
                    } else {
                        // This mode is no longer used, but kept for future
                        n.pathModalTitle.textContent = 'Select File Path';
                        n.pathModalInput.placeholder = 'e.g., C:\\Users\\YourName\\MyProject\\model.obj';
                        n.pathModalDesc.textContent = 'Please paste the absolute path to the single file you want to process.';
                    }
                    n.pathModalInput.value = '';
                    n.pathModal.style.display = 'flex';
                    n.pathModalInput.focus();
                });
            },

            hidePathModal() {
                App.nodes.pathModal.style.display = 'none';
                App.state.pathModalPromise = { resolve: null, reject: null };
            },

            /**
             * Displays the validation modal with file details.
             * @param {string} filename - The name of the main file.
             * @param {string} status - The validation status string (e.g., "Valid", "Problems").
             * @param {string} statusClass - The CSS class for the status badge (e.g., "status-Valid").
             * @param {Array} children - An array of child file nodes (from fileNode.children).
             * @param {object} validationReport - The detailed report object (from fileNode.validation_report).
             */
            showValidationModal(filename, status, statusClass, children, validationReport) {
                const n = App.nodes;

                // Get references to the new modal elements
                // Note: These should also be added to the App.nodes object for cleaner code.
                const detailsContainer = document.getElementById('validation-modal-details-container');
                const detailsList = document.getElementById('validation-modal-details-list');

                // --- 1. Set Title and Status Badge (Original Logic) ---
                n.validationModalTitle.textContent = filename;
                n.validationModalStatusBadge.textContent = status;
                n.validationModalStatusBadge.className = 'file-row-status'; // Reset class
                n.validationModalStatusBadge.classList.add(statusClass);

                // --- 2. Populate Bundled Files (Original Logic) ---
                if (children && children.length > 0) {
                    n.validationModalChildrenContainer.style.display = 'block';
                    n.validationModalChildren.innerHTML = '';
                    children.forEach(child => {
                        const childName = child.name || child.filename || 'Unknown child file';
                        const li = document.createElement('li');
                        li.textContent = childName;
                        n.validationModalChildren.appendChild(li);
                    });
                } else {
                    n.validationModalChildrenContainer.style.display = 'none';
                }

                // --- 3. Populate Validation Details (New Logic) ---
                detailsList.innerHTML = ''; // Clear previous details
                let detailsFound = false;

                /**
                 * Helper to add a line item to the details list.
                 * @param {string} text - The error or warning message.
                 * @param {'error' | 'warning'} type - The type of message for styling.
                 */
                const addDetailItem = (text, type = 'error') => {
                    const li = document.createElement('li');
                    li.textContent = text;
                    // Apply styles from styles.css
                    li.style.cssText = 'padding: 0.5rem 1rem; border-bottom: 1px solid var(--color-border);';
                    if (type === 'error') {
                        li.style.color = 'var(--color-error)';
                    } else if (type === 'warning') {
                        li.style.color = '#8a6d0a'; // color from .status-Missing
                    }
                    detailsList.appendChild(li);
                    detailsFound = true;
                };

                // Check the validationReport object for details
                if (validationReport) {
                    // Display errors
                    (validationReport.errors || []).forEach(err => {
                        addDetailItem(err, 'error');
                    });

                    // Display missing texture warnings
                    (validationReport.missing_textures || []).forEach(tex => {
                        addDetailItem(`Missing texture: ${tex}`, 'warning');
                    });

                    // Display file conflict errors
                    (validationReport.conflicts || []).forEach(con => {
                        addDetailItem(`File conflict: ${con}`, 'error');
                    });
                }

                // Show the details container only if we added items to it
                if (detailsFound) {
                    detailsContainer.style.display = 'block';
                } else {
                    detailsContainer.style.display = 'none';
                }

                // --- 4. Show the Modal (Original Logic) ---
                n.validationModal.style.display = 'flex';
            },

            hideValidationModal() {
                App.nodes.validationModal.style.display = 'none';
            }
        },

        // ---
        // 5. DOM Rendering
        // ---
        render: {
            renderFoundFilesList(foundFiles) {
                const n = App.nodes;
                n.fileListContainer.innerHTML = '';

                if (!foundFiles || foundFiles.length === 0) {
                    n.fileListContainer.appendChild(n.fileListPlaceholder);
                    n.fileListPlaceholder.style.display = 'flex';
                    n.fileListHeader.style.display = 'none';
                } else {
                    n.fileListPlaceholder.style.display = 'none';
                    n.fileListHeader.style.display = 'flex';

                    foundFiles.forEach(fileNode => {
                        const row = App.render.createFileRowHTML(fileNode, 0);
                        n.fileListContainer.appendChild(row);
                        if (fileNode.children && fileNode.children.length > 0) {
                            App.render.renderChildFiles(fileNode.children, 1);
                        }
                    });
                }
            },

            renderChildFiles(childNodes, depth) {
                childNodes.forEach(childNode => {
                    const row = App.render.createFileRowHTML(childNode, depth);
                    App.nodes.fileListContainer.appendChild(row);
                    if (childNode.children && childNode.children.length > 0) {
                        App.render.renderChildFiles(childNode.children, depth + 1);
                    }
                });
            },

            createFileRowHTML(fileNode, depth) {
                const row = document.createElement('div');
                row.className = 'file-row';

                const indent = depth * 20;
                const status = fileNode.status || 'N/A';
                const name = fileNode.name || fileNode.filename || 'Unknown File';

                let statusClass = 'status-Valid';
                if (status.includes('Missing')) statusClass = 'status-Missing';
                else if (status.includes('Problems') || status.includes('Invalid') || status.includes('pending')) {
                    statusClass = 'status-Problems';
                }

                row.dataset.filename = name;
                row.dataset.status = status;
                row.dataset.statusClass = statusClass;
                row.dataset.children = JSON.stringify(fileNode.children || []);
                row.dataset.validationReport = JSON.stringify(fileNode.validation_report || {});

                row.innerHTML = `
                    <span class="file-row-icon" style="margin-left: ${indent}px;">${depth > 0 ? '↳' : '🗎'}</span>
                    <span class="file-row-name">${name}</span>
                    <span class="file-row-status ${statusClass}">${status}</span>
                `;
                return row;
            }
        },

        // ---
        // 6. Event Handlers
        // ---
        handlers: {
            handleSessionSuccess(data) {
                App.render.renderFoundFilesList(data.foundFiles);
                App.ui.showModal('success', 'Scan complete. Files listed below.');
            },

            async onUploadDirectoryClick() {
                App.nodes.uploadBtn.disabled = true;
                App.nodes.uploadFileBtn.disabled = true;
                try {
                    const directoryPath = await App.ui.showPathModal('directory');
                    if (!directoryPath) return;

                    App.ui.showModal('scanning');
                    const data = await App.api.startDirectorySession(directoryPath);
                    App.handlers.handleSessionSuccess(data);
                } catch (error) {
                    if (error.message !== 'User cancelled.') {
                        // Extract user-friendly error message
                        const errorMsg = error.message || 'An error occurred while scanning the directory.';
                        App.ui.showModal('error', errorMsg);
                    }
                } finally {
                    App.nodes.uploadBtn.disabled = false;
                    App.nodes.uploadFileBtn.disabled = false;
                }
            },

            async onUploadFileClick() {
                App.nodes.uploadBtn.disabled = true;
                App.nodes.uploadFileBtn.disabled = true;

                const fileInput = document.createElement('input');
                fileInput.type = 'file';
                fileInput.style.display = 'none';

                const cleanup = () => {
                    App.nodes.uploadBtn.disabled = false;
                    App.nodes.uploadFileBtn.disabled = false;
                    if (document.body.contains(fileInput)) {
                        document.body.removeChild(fileInput);
                    }
                };

                fileInput.addEventListener('change', async (e) => {
                    const file = e.target.files[0];
                    if (!file) {
                        cleanup();
                        return;
                    }

                    App.ui.showModal('scanning');
                    try {
                        const data = await App.api.startFileSession(file);
                        App.handlers.handleSessionSuccess(data);
                    } catch (error) {
                        const errorMsg = error.message || 'An error occurred while processing the file.';
                        App.ui.showModal('error', errorMsg);
                    } finally {
                        cleanup();
                    }
                });

                // Focus listener to detect dialog cancellation
                window.addEventListener('focus', () => {
                    setTimeout(() => {
                        if (document.body.contains(fileInput) && !fileInput.files[0]) {
                            cleanup();
                        }
                    }, 300);
                }, { once: true });

                document.body.appendChild(fileInput);
                fileInput.click();
            },

            onFileRowClick(e) {
                const row = e.target.closest('.file-row');
                if (row) {
                    const { filename, status, statusClass, children, validationReport } = row.dataset;

                    App.ui.showValidationModal(
                        filename,
                        status,
                        statusClass,
                        JSON.parse(children),
                        JSON.parse(validationReport) // Pass the parsed report
                    );
                }
            },

            onPathModalCancel() {
                if (App.state.pathModalPromise.reject) {
                    App.state.pathModalPromise.reject(new Error('User cancelled.'));
                }
                App.ui.hidePathModal();
            },

            onPathModalSubmit() {
                const path = App.nodes.pathModalInput.value.trim();
                if (path && App.state.pathModalPromise.resolve) {
                    App.state.pathModalPromise.resolve(path);
                    App.ui.hidePathModal();
                } else if (!path) {
                    App.nodes.pathModalInput.focus();
                }
            }
        },

        // ---
        // 7. Initialization
        // ---
        init() {
            // Attach all event listeners
            App.nodes.uploadBtn.addEventListener('click', App.handlers.onUploadDirectoryClick);
            App.nodes.uploadFileBtn.addEventListener('click', App.handlers.onUploadFileClick);
            App.nodes.modalCloseBtn.addEventListener('click', App.ui.hideModal);

            App.nodes.pathModalCancelBtn.addEventListener('click', App.handlers.onPathModalCancel);
            App.nodes.pathModalSubmitBtn.addEventListener('click', App.handlers.onPathModalSubmit);
            App.nodes.pathModalInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') App.handlers.onPathModalSubmit();
            });

            App.nodes.validationModalCloseBtn.addEventListener('click', App.ui.hideValidationModal);
            App.nodes.fileListContainer.addEventListener('click', App.handlers.onFileRowClick);

            // Set the initial state
            App.render.renderFoundFilesList([]);
        }
    };

    // Run the application
    App.init();

});