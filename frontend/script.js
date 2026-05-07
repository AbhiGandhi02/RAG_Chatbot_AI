import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.1/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, getIdToken } from "https://www.gstatic.com/firebasejs/10.8.1/firebase-auth.js";

// ===== Initialization =====
let app, auth, provider;

async function initFirebase() {
    try {
        const response = await fetch('/api/firebase-config');
        if (!response.ok) throw new Error("Failed to load Firebase config");
        const firebaseConfig = await response.json();

        app = initializeApp(firebaseConfig);
        auth = getAuth(app);
        provider = new GoogleAuthProvider();

        setupAuthListeners();
    } catch (error) {
        console.error("Error initializing Firebase:", error);
        alert("Failed to initialize authentication.");
    }
}

initFirebase();

// ===== DOM Elements =====
const authModal = document.getElementById('authModal');
const googleSignInBtn = document.getElementById('googleSignInBtn');
const userProfile = document.getElementById('userProfile');
const userNameEl = document.getElementById('userName');
const userAvatarEl = document.getElementById('userAvatar');
const signOutBtn = document.getElementById('signOutBtn');

const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');

const conversationsList = document.getElementById('conversationsList');
const debugContent = document.getElementById('debugContent');

const documentsSection = document.getElementById('documentsSection');
const uploadBtn = document.getElementById('uploadBtn');
const uploadInput = document.getElementById('uploadInput');
const uploadStatus = document.getElementById('uploadStatus');
const documentsList = document.getElementById('documentsList');

// ===== State =====
let currentUser = null;
let currentToken = null;
let currentConversationId = null;
let isLoading = false;

// ===== Auth Listeners =====

function setupAuthListeners() {
    onAuthStateChanged(auth, async (user) => {
        if (user) {
            currentUser = user;
            currentToken = await getIdToken(user);

            // Update UI
            authModal.classList.add('hidden');
            userProfile.style.display = 'flex';
            userNameEl.textContent = user.displayName || user.email;
            if (user.photoURL) {
                userAvatarEl.innerHTML = `<img src="${user.photoURL}" alt="avatar" style="width:100%; height:100%; border-radius:50%;">`;
            } else {
                userAvatarEl.textContent = (user.displayName || user.email).charAt(0).toUpperCase();
            }

            messageInput.disabled = false;
            sendBtn.disabled = false;
            messageInput.placeholder = "Ask a question about your documents...";

            // Show documents section now that user is signed in
            documentsSection.style.display = 'block';

            // Load sidebar data
            await loadConversations();
            await loadDocuments();
        } else {
            // User is signed out
            currentUser = null;
            currentToken = null;
            authModal.classList.remove('hidden');
            userProfile.style.display = 'none';

            messageInput.disabled = true;
            sendBtn.disabled = true;
            messageInput.placeholder = "Sign in to ask a question...";

            documentsSection.style.display = 'none';
            documentsList.innerHTML = '';
            uploadStatus.textContent = '';

            conversationsList.innerHTML = '';
            startNewConversation();
        }
    });

    // Auth Actions
    googleSignInBtn.addEventListener('click', async () => {
        try {
            await signInWithPopup(auth, provider);
        } catch (error) {
            console.error("Auth error:", error);
            alert("Failed to sign in: " + error.message);
        }
    });

    signOutBtn.addEventListener('click', (e) => {
        e.preventDefault();
        signOut(auth);
    });
}

// ===== Conversations API =====

async function authenticatedFetch(url, options = {}) {
    if (!currentToken && currentUser) {
        currentToken = await getIdToken(currentUser);
    }

    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${currentToken}`
    };

    return fetch(url, { ...options, headers });
}

async function loadConversations() {
    try {
        const res = await authenticatedFetch('/conversations');
        if (!res.ok) throw new Error("Failed to fetch conversations");
        const convs = await res.json();

        conversationsList.innerHTML = '';

        if (convs.length === 0) {
            startNewConversation();
            return;
        }

        convs.forEach(conv => {
            const div = document.createElement('div');
            div.className = `conv-item ${conv.id === currentConversationId ? 'active' : ''}`;

            const titleSpan = document.createElement('span');
            titleSpan.className = 'conv-title';
            titleSpan.textContent = conv.title || 'New Chat';
            div.appendChild(titleSpan);

            const actions = document.createElement('div');
            actions.className = 'conv-actions';

            const editBtn = document.createElement('button');
            editBtn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
            `;
            editBtn.onclick = (e) => {
                e.stopPropagation();
                titleSpan.style.display = 'none';
                actions.style.display = 'none';

                const input = document.createElement('input');
                input.className = 'conv-title-input';
                input.value = titleSpan.textContent;

                const saveTitle = async () => {
                    const newTitle = input.value.trim();
                    if (newTitle && newTitle !== conv.title) {
                        try {
                            const res = await authenticatedFetch(`/conversations/${conv.id}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ title: newTitle })
                            });
                            if (!res.ok) throw new Error("Failed to rename");
                            titleSpan.textContent = newTitle;
                            conv.title = newTitle;
                        } catch (err) {
                            console.error(err);
                        }
                    }
                    input.remove();
                    titleSpan.style.display = '';
                    actions.style.display = '';
                };

                input.onblur = saveTitle;
                input.onkeydown = (e_down) => {
                    if (e_down.key === 'Enter') saveTitle();
                    if (e_down.key === 'Escape') {
                        input.remove();
                        titleSpan.style.display = '';
                        actions.style.display = '';
                    }
                };

                div.insertBefore(input, actions);
                input.focus();
                input.select();
            };

            const delBtn = document.createElement('button');
            delBtn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
            `;
            delBtn.onclick = (e) => {
                e.stopPropagation();
                editBtn.style.display = 'none';
                delBtn.style.display = 'none';

                const confirmBtn = document.createElement('button');
                confirmBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff4d4f" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
                confirmBtn.onclick = async (e2) => {
                    e2.stopPropagation();
                    await deleteConversation(conv.id);
                };

                const cancelBtn = document.createElement('button');
                cancelBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
                cancelBtn.onclick = (e3) => {
                    e3.stopPropagation();
                    confirmBtn.remove();
                    cancelBtn.remove();
                    editBtn.style.display = '';
                    delBtn.style.display = '';
                };

                actions.appendChild(confirmBtn);
                actions.appendChild(cancelBtn);
            };

            actions.appendChild(editBtn);
            actions.appendChild(delBtn);
            div.appendChild(actions);

            div.onclick = () => selectConversation(conv.id);
            conversationsList.appendChild(div);
        });

        // Select the most recent if nothing is selected
        if (!currentConversationId && convs.length > 0) {
            selectConversation(convs[0].id);
        }

    } catch (error) {
        console.error("Load convos error:", error);
    }
}

async function selectConversation(convId) {
    if (currentConversationId === convId) return;
    currentConversationId = convId;

    // Update active class in sidebar
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    // (This works but is simple; we could also re-render the list or find by ID)
    loadConversations(); // lazy refresh

    // Clear chat area
    chatMessages.innerHTML = `
        <div class="message bot-message loading-message">
            <div class="message-avatar bot-avatar">CP</div>
            <div class="message-content" style="padding:4px 12px">
                <div class="loading-dots"><span></span><span></span><span></span></div>
            </div>
        </div>
    `;

    try {
        const res = await authenticatedFetch(`/conversations/${convId}`);
        if (!res.ok) throw new Error("Failed to fetch chat history");
        const history = await res.json();

        chatMessages.innerHTML = ''; // clear loading

        if (history.length === 0) {
            chatMessages.innerHTML = `
                <div class="message bot-message">
                    <div class="message-avatar bot-avatar">CP</div>
                    <div class="message-content">
                        <p>👋 Welcome to ClearPath Support! Ask me anything.</p>
                    </div>
                </div>
            `;
            return;
        }

        history.forEach(msg => {
            const isUser = msg.role === 'user';
            const msgEl = addMessage(msg.content, isUser ? 'user' : 'bot', [], true);

            if (!isUser && msg.metadata) {
                // If it has flags, add the warning badge retroactively
                if (msg.metadata.evaluator_flags && msg.metadata.evaluator_flags.length > 0) {
                    const warningBadge = document.createElement('div');
                    warningBadge.className = 'warning-badge';
                    warningBadge.textContent = `⚠️ Flagged: ${msg.metadata.evaluator_flags.join(', ')}`;
                    const contentDiv = msgEl.querySelector('.message-content div:last-child');
                    msgEl.querySelector('.message-content').insertBefore(warningBadge, contentDiv);
                }

                // Make message clickable to view debug info
                msgEl.style.cursor = 'pointer';
                msgEl.title = "Click to view debug info";
                msgEl.addEventListener('click', () => {
                    updateDebugPanel({
                        metadata: msg.metadata,
                        sources: msg.metadata.sources || []
                    });
                });
            }
        });
        // Auto-populate the debug panel with the most recent assistant message
        const lastAssistantMsg = [...history].reverse().find(m => m.role === 'assistant' && m.metadata);
        if (lastAssistantMsg) {
            updateDebugPanel({
                metadata: lastAssistantMsg.metadata,
                sources: lastAssistantMsg.metadata.sources || []
            });
        }

        chatMessages.scrollTop = chatMessages.scrollHeight;

    } catch (error) {
        console.error(error);
        chatMessages.innerHTML = `<div class="message bot-message"><div class="message-content">Failed to load history.</div></div>`;
    }
}

function startNewConversation() {
    currentConversationId = null;
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    chatMessages.innerHTML = `
        <div class="message bot-message">
            <div class="message-avatar bot-avatar">CP</div>
            <div class="message-content">
                <p>👋 New chat started. How can I help you today?</p>
            </div>
        </div>
    `;
}

async function renameConversation(convId, newTitle) {
    try {
        const res = await authenticatedFetch(`/conversations/${convId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        if (!res.ok) throw new Error("Failed to rename conversation");
        await loadConversations();
    } catch (error) {
        console.error("Rename error:", error);
        alert("Could not rename conversation.");
    }
}

async function deleteConversation(convId) {
    try {
        const res = await authenticatedFetch(`/conversations/${convId}`, {
            method: 'DELETE'
        });
        if (!res.ok) throw new Error("Failed to delete conversation");

        if (currentConversationId === convId) {
            startNewConversation();
        }
        await loadConversations();
    } catch (error) {
        console.error("Delete error:", error);
        alert("Could not delete conversation.");
    }
}

newChatBtn.addEventListener('click', startNewConversation);

// ===== Documents (uploads) =====

async function loadDocuments() {
    try {
        const res = await authenticatedFetch('/documents');
        if (!res.ok) throw new Error("Failed to fetch documents");
        const docs = await res.json();
        renderDocuments(docs);
    } catch (err) {
        console.error("Load documents error:", err);
    }
}

function renderDocuments(docs) {
    documentsList.innerHTML = '';
    if (!docs.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'opacity:0.6; font-style:italic;';
        empty.textContent = 'No documents yet. Upload to start asking questions.';
        documentsList.appendChild(empty);
        return;
    }
    docs.forEach(d => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; gap:6px; padding:4px 6px; border-radius:4px; background:rgba(255,255,255,0.04);';
        const name = document.createElement('span');
        name.textContent = `📄 ${d.document}`;
        name.title = `${d.chunks} chunks`;
        name.style.cssText = 'overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1;';
        const del = document.createElement('button');
        del.textContent = '×';
        del.title = 'Delete document';
        del.style.cssText = 'background:transparent; border:none; color:inherit; opacity:0.6; cursor:pointer; font-size:16px; padding:0 4px;';
        del.onclick = () => deleteDocument(d.document);
        row.appendChild(name);
        row.appendChild(del);
        documentsList.appendChild(row);
    });
}

async function deleteDocument(docName) {
    if (!confirm(`Delete "${docName}" from your library?`)) return;
    try {
        const res = await authenticatedFetch(`/documents/${encodeURIComponent(docName)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Delete failed");
        await loadDocuments();
    } catch (err) {
        console.error(err);
        alert('Could not delete document.');
    }
}

uploadBtn.addEventListener('click', () => uploadInput.click());

uploadInput.addEventListener('change', async () => {
    const file = uploadInput.files[0];
    if (!file) return;
    if (!currentToken && currentUser) currentToken = await getIdToken(currentUser);

    uploadStatus.textContent = `Uploading "${file.name}"…`;
    uploadBtn.disabled = true;

    try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch('/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${currentToken}` },
            body: fd
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status})`);
        uploadStatus.textContent = `Indexed ${data.chunks_indexed} chunks from ${data.pages} pages.`;
        await loadDocuments();
    } catch (err) {
        console.error(err);
        uploadStatus.textContent = `Error: ${err.message}`;
    } finally {
        uploadBtn.disabled = false;
        uploadInput.value = '';
    }
});

// ===== Chat Interface =====

sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
});

async function sendMessage() {
    const question = messageInput.value.trim();
    if (!question || isLoading || !currentUser) return;

    // Add user message to UI
    addMessage(question, 'user');
    messageInput.value = '';
    messageInput.style.height = 'auto';

    isLoading = true;
    sendBtn.disabled = true;
    const loadingEl = addLoadingMessage();

    try {
        if (!currentToken) currentToken = await getIdToken(currentUser);

        const response = await fetch('/query/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                question,
                conversation_id: currentConversationId
            })
        });

        if (!response.ok) {
            if (response.status === 401) {
                // Token expired, refresh and retry could go here, for now just enforce login
                signOut(auth);
                throw new Error("Session expired. Please log in again.");
            }
            throw new Error(`Server error: ${response.status}`);
        }

        loadingEl.remove();
        const botMsg = addMessage('', 'bot');
        const contentDiv = botMsg.querySelector('.message-content div:last-child');

        let fullAnswer = '';
        let streamMeta = {};

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = JSON.parse(line.slice(6));

                if (data.type === 'metadata') {
                    streamMeta = data;
                    // If this was a new conversation, the server created an ID for us.
                    if (!currentConversationId && data.conversation_id) {
                        currentConversationId = data.conversation_id;
                        // Refresh the sidebar to show the new chat title
                        loadConversations();
                    }
                } else if (data.type === 'token') {
                    fullAnswer += data.content;
                    contentDiv.innerHTML = formatText(fullAnswer);
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                } else if (data.type === 'done') {
                    const fullMetadata = {
                        model_used: streamMeta.model_used || '',
                        classification: streamMeta.classification || 'simple',
                        tokens: { input: data.tokens_input, output: data.tokens_output },
                        latency_ms: data.latency_ms,
                        chunks_retrieved: streamMeta.chunks_retrieved || 0,
                        evaluator_flags: data.evaluator_flags || []
                    };

                    updateDebugPanel({
                        metadata: fullMetadata,
                        sources: streamMeta.sources || []
                    });

                    if (data.evaluator_flags && data.evaluator_flags.length > 0) {
                        const warningBadge = document.createElement('div');
                        warningBadge.className = 'warning-badge';
                        warningBadge.textContent = `⚠️ Flagged: ${data.evaluator_flags.join(', ')}`;
                        botMsg.querySelector('.message-content').insertBefore(warningBadge, contentDiv);
                    }

                    // Make freshly generated message clickable too
                    botMsg.style.cursor = 'pointer';
                    botMsg.title = "Click to view debug info";
                    botMsg.addEventListener('click', () => {
                        updateDebugPanel({
                            metadata: fullMetadata,
                            sources: streamMeta.sources || []
                        });
                    });
                } else if (data.type === 'error') {
                    contentDiv.textContent = `Error: ${data.content}`;
                }
            }
        }
    } catch (error) {
        if (loadingEl) loadingEl.remove();
        addMessage(`Sorry, something went wrong: ${error.message}`, 'bot', ['error']);
    } finally {
        isLoading = false;
        sendBtn.disabled = false;
        messageInput.focus();
    }
}

function addMessage(text, sender, flags = [], skipScroll = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}-message`;

    const avatar = document.createElement('div');
    avatar.className = `message-avatar ${sender === 'bot' ? 'bot-avatar' : 'user-avatar-msg'}`;

    // Use Google profile picture if user, otherwise text
    if (sender === 'bot') {
        avatar.textContent = 'CP';
    } else if (currentUser && currentUser.photoURL) {
        avatar.innerHTML = `<img src="${currentUser.photoURL}" alt="U" style="width:100%; height:100%; border-radius:50%;">`;
    } else {
        avatar.textContent = 'You';
    }

    const content = document.createElement('div');
    content.className = 'message-content';

    if (flags.length > 0 && !flags.includes('error')) {
        const warningBadge = document.createElement('div');
        warningBadge.className = 'warning-badge';
        warningBadge.textContent = `⚠️ Flagged: ${flags.join(', ')}`;
        content.appendChild(warningBadge);
    }

    const textDiv = document.createElement('div');
    textDiv.innerHTML = formatText(text);
    content.appendChild(textDiv);

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    chatMessages.appendChild(messageDiv);

    if (!skipScroll) chatMessages.scrollTop = chatMessages.scrollHeight;
    return messageDiv;
}

function addLoadingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message loading-message';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar bot-avatar';
    avatar.textContent = 'CP';

    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = `<div class="loading-dots"><span></span><span></span><span></span></div>`;

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return messageDiv;
}

function formatText(text) {
    if (!text) return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.08);padding:1px 5px;border-radius:4px;font-size:12px;">$1</code>')
        .replace(/\n/g, '<br>');
}

function updateDebugPanel(data) {
    const { metadata, sources } = data;
    const classification = metadata.classification || 'simple';
    const modelUsed = metadata.model_used || 'unknown';
    const tokensInput = (metadata.tokens && metadata.tokens.input) || 0;
    const tokensOutput = (metadata.tokens && metadata.tokens.output) || 0;
    const latencyMs = metadata.latency_ms || 0;
    const chunksRetrieved = metadata.chunks_retrieved || 0;
    const evalFlags = metadata.evaluator_flags || [];
    const srcList = sources || [];

    const classificationBadge = classification === 'simple'
        ? '<span class="badge badge-simple">Simple</span>'
        : '<span class="badge badge-complex">Complex</span>';

    const flagsHtml = evalFlags.length > 0
        ? evalFlags.map(f => `<span class="badge badge-flag">${f}</span>`).join(' ')
        : '<span class="badge badge-ok">None</span>';

    const sourcesHtml = srcList.length > 0
        ? srcList.map(s => `<div class="source-item"><span>📄 ${s.document || 'Unknown'}</span>${s.relevance_score ? `<span class="source-score">${(s.relevance_score * 100).toFixed(0)}%</span>` : ''}</div>`).join('')
        : '<div class="source-item">No sources retrieved</div>';

    debugContent.innerHTML = `
        <div class="debug-card">
            <div class="debug-card-title">Model & Routing</div>
            <div class="debug-row"><span class="debug-label">Classification</span>${classificationBadge}</div>
            <div class="debug-row"><span class="debug-label">Model</span><span class="debug-value">${shortenModelName(modelUsed)}</span></div>
        </div>
        <div class="debug-card">
            <div class="debug-card-title">Token Usage</div>
            <div class="debug-row"><span class="debug-label">Input</span><span class="debug-value">${tokensInput.toLocaleString()}</span></div>
            <div class="debug-row"><span class="debug-label">Output</span><span class="debug-value">${tokensOutput.toLocaleString()}</span></div>
            <div class="debug-row"><span class="debug-label">Latency</span><span class="debug-value">${latencyMs}ms</span></div>
            <div class="debug-row"><span class="debug-label">Chunks Retrieved</span><span class="debug-value">${chunksRetrieved}</span></div>
        </div>
        <div class="debug-card">
            <div class="debug-card-title">Evaluator Flags</div>
            <div style="padding: 4px 0;">${flagsHtml}</div>
        </div>
        <div class="debug-card">
            <div class="debug-card-title">Sources (${srcList.length} chunks)</div>
            ${sourcesHtml}
        </div>
    `;
}

function shortenModelName(model) {
    if (model.includes('8b')) return 'Llama 3.1 8B';
    if (model.includes('70b')) return 'Llama 3.3 70B';
    return model;
}
