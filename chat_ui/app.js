/**
 * Handbook AI — Chat V2 Application Logic
 * =========================================
 * Handles chat interactions, sidebar, and RAG pipeline visualization.
 */

const API_BASE = window.location.origin;

// ── State ───────────────────────────────────────────────────────────────────
const state = {
    messages: [],
    showChunks: true,
    selectedCategory: null,
    systemInfo: null,
    isLoading: false,
};

// ── DOM References ──────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    app: $('#app'),
    sidebar: $('#sidebar'),
    sidebarToggle: $('#sidebar-toggle'),
    mobileMenu: $('#mobile-menu'),
    messages: $('#messages'),
    messagesContainer: $('#messages-container'),
    chatInput: $('#chat-input'),
    sendBtn: $('#send-btn'),
    toggleChunks: $('#toggle-chunks'),
    clearChat: $('#clear-chat'),
    welcomeScreen: $('#welcome-screen'),
    suggestionGrid: $('#suggestion-grid'),
    docList: $('#doc-list'),
    categoryList: $('#category-list'),
    statDocs: $('#stat-docs'),
    statChunks: $('#stat-chunks'),
    embedderInfo: $('#embedder-info'),
    filterIndicator: $('#filter-indicator'),
    filterIcon: $('#filter-icon'),
    filterLabel: $('#filter-label'),
    filterClear: $('#filter-clear'),
};

// ── Initialization ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    await loadSystemInfo();
    await loadSuggestions();
});

function setupEventListeners() {
    // Send message
    els.sendBtn.addEventListener('click', sendMessage);
    els.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Input auto-resize & enable/disable send
    els.chatInput.addEventListener('input', () => {
        els.chatInput.style.height = 'auto';
        els.chatInput.style.height = Math.min(els.chatInput.scrollHeight, 120) + 'px';
        els.sendBtn.disabled = !els.chatInput.value.trim();
        
        // Auto-detect filter
        const query = els.chatInput.value.trim();
        if (query && !state.selectedCategory) {
            const detected = detectCategory(query);
            if (detected) {
                showFilterIndicator(detected);
            } else {
                hideFilterIndicator();
            }
        }
    });

    // Sidebar toggle
    els.sidebarToggle.addEventListener('click', () => {
        els.sidebar.classList.toggle('collapsed');
    });

    // Mobile menu
    els.mobileMenu.addEventListener('click', () => {
        els.sidebar.classList.toggle('open');
        toggleOverlay(true);
    });

    // Toggle chunks visibility
    els.toggleChunks.addEventListener('click', () => {
        state.showChunks = !state.showChunks;
        els.toggleChunks.classList.toggle('active', state.showChunks);
        $$('.chunks-panel').forEach(panel => {
            panel.style.display = state.showChunks ? 'block' : 'none';
        });
    });
    els.toggleChunks.classList.add('active'); // Default on

    // Clear chat
    els.clearChat.addEventListener('click', clearChat);

    // Filter clear
    els.filterClear.addEventListener('click', () => {
        state.selectedCategory = null;
        hideFilterIndicator();
        $$('.category-item').forEach(el => el.classList.remove('active'));
    });
}

// ── Category Detection (client-side mirror) ─────────────────────────────────
const CATEGORY_KEYWORDS = {
    benefits:     ['nghỉ phép', 'phúc lợi', 'bảo hiểm', 'nghỉ lễ', 'pto', 'sabbatical', 'nghỉ hè', 'insurance', 'benefit'],
    policy:       ['chính sách', 'ngoài giờ', 'làm thêm', 'moonlighting', 'nghỉ việc', 'trợ cấp', 'severance'],
    onboarding:   ['nhân viên mới', 'tuần đầu', 'bắt đầu', 'onboarding', 'ngày đầu'],
    career:       ['lương', 'thăng chức', 'sự nghiệp', 'career', 'salary', 'promotion', 'thăng tiến'],
    tools:        ['hệ thống', 'công cụ', 'sentry', 'basecamp', 'tool', 'lỗi', 'bug', 'thiết bị'],
    work_culture: ['làm việc', 'remote', 'từ xa', 'giao tiếp', 'async'],
    culture:      ['truyền thống', 'lễ', 'văn hóa', 'tradition'],
};

const CATEGORY_INFO = {
    onboarding:   { label: 'Onboarding',       icon: '🚀', color: '#6366f1' },
    work_culture: { label: 'Văn Hóa Làm Việc', icon: '🏢', color: '#8b5cf6' },
    tools:        { label: 'Công Cụ & Hệ Thống', icon: '🔧', color: '#06b6d4' },
    policy:       { label: 'Chính Sách',        icon: '📋', color: '#f59e0b' },
    culture:      { label: 'Văn Hóa Công Ty',   icon: '🎉', color: '#ec4899' },
    career:       { label: 'Sự Nghiệp',        icon: '📈', color: '#10b981' },
    benefits:     { label: 'Phúc Lợi',          icon: '🎁', color: '#ef4444' },
};

function detectCategory(query) {
    const q = query.toLowerCase();
    const scores = {};
    for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
        const score = keywords.filter(kw => q.includes(kw)).length;
        if (score > 0) scores[cat] = score;
    }
    if (Object.keys(scores).length === 0) return null;
    return Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
}

// ── Filter Indicator ────────────────────────────────────────────────────────
function showFilterIndicator(category) {
    const info = CATEGORY_INFO[category] || { label: category, icon: '🔍', color: '#6b7280' };
    els.filterIndicator.style.display = 'flex';
    els.filterIndicator.style.borderColor = info.color + '40';
    els.filterIndicator.style.background = info.color + '15';
    els.filterIcon.textContent = info.icon;
    els.filterLabel.textContent = `Auto-filter: ${info.label}`;
    els.filterLabel.style.color = info.color;
}

function hideFilterIndicator() {
    els.filterIndicator.style.display = 'none';
}

// ── Load System Info ────────────────────────────────────────────────────────
async function loadSystemInfo() {
    try {
        const res = await fetch(`${API_BASE}/api/info`);
        const data = await res.json();
        state.systemInfo = data;

        // Stats
        els.statDocs.textContent = data.total_docs;
        els.statChunks.textContent = data.total_chunks;
        els.embedderInfo.textContent = data.embedder;

        // Document list
        els.docList.innerHTML = data.documents.map(doc => `
            <div class="doc-item" title="${doc.source} — ${doc.chars} chars">
                <div class="doc-icon" style="background: ${doc.category_color}"></div>
                <span class="doc-name">${doc.category_icon} ${doc.label}</span>
                <span class="doc-chunks">${doc.chunks} chunks</span>
            </div>
        `).join('');

        // Category list
        const cats = data.categories;
        els.categoryList.innerHTML = Object.entries(cats).map(([key, cat]) => `
            <div class="category-item" data-category="${key}" title="${cat.doc_count} tài liệu, ${cat.total_chunks} chunks">
                <div class="category-dot" style="background: ${cat.color}"></div>
                <span class="category-name">${cat.icon} ${cat.label}</span>
                <span class="category-count">${cat.total_chunks}</span>
            </div>
        `).join('');

        // Category click → set filter
        $$('.category-item').forEach(el => {
            el.addEventListener('click', () => {
                const cat = el.dataset.category;
                if (state.selectedCategory === cat) {
                    state.selectedCategory = null;
                    el.classList.remove('active');
                    hideFilterIndicator();
                } else {
                    state.selectedCategory = cat;
                    $$('.category-item').forEach(e => e.classList.remove('active'));
                    el.classList.add('active');
                    showFilterIndicator(cat);
                }
            });
        });
    } catch (err) {
        console.error('Failed to load system info:', err);
    }
}

// ── Load Suggestions ────────────────────────────────────────────────────────
async function loadSuggestions() {
    try {
        const res = await fetch(`${API_BASE}/api/suggestions`);
        const data = await res.json();

        els.suggestionGrid.innerHTML = data.suggestions.map(s => `
            <div class="suggestion-item" data-query="${escapeHtml(s.query)}" data-category="${s.category}">
                <span class="suggestion-icon">${s.icon}</span>
                <span class="suggestion-text">${escapeHtml(s.query)}</span>
            </div>
        `).join('');

        $$('.suggestion-item').forEach(el => {
            el.addEventListener('click', () => {
                const query = el.dataset.query;
                els.chatInput.value = query;
                els.chatInput.dispatchEvent(new Event('input'));
                sendMessage();
            });
        });
    } catch (err) {
        console.error('Failed to load suggestions:', err);
    }
}

// ── Send Message ────────────────────────────────────────────────────────────
async function sendMessage() {
    const query = els.chatInput.value.trim();
    if (!query || state.isLoading) return;

    state.isLoading = true;
    els.sendBtn.disabled = true;

    // Hide welcome
    if (els.welcomeScreen) {
        els.welcomeScreen.style.display = 'none';
    }

    // Determine category
    const category = state.selectedCategory || detectCategory(query);

    // Add user message
    addMessage('user', query, { category });

    // Clear input
    els.chatInput.value = '';
    els.chatInput.style.height = 'auto';
    hideFilterIndicator();

    // Show typing indicator
    const typingId = showTyping();

    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, category }),
        });

        const data = await res.json();
        removeTyping(typingId);

        // Add bot message with chunks
        addMessage('bot', data.answer, {
            chunks: data.chunks,
            filter: data.filter_applied,
            elapsed: data.elapsed_ms,
            strategy: data.strategy,
        });
    } catch (err) {
        removeTyping(typingId);
        addMessage('bot', '❌ Không thể kết nối tới server. Vui lòng kiểm tra server đang chạy tại port 5050.', {});
    }

    state.isLoading = false;
    scrollToBottom();
}

// ── Add Message to DOM ──────────────────────────────────────────────────────
function addMessage(role, content, meta = {}) {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

    const msgEl = document.createElement('div');
    msgEl.className = `message ${role}`;

    const avatar = role === 'user' ? '👤' : '🤖';

    let filterTag = '';
    const filterInfo = meta.filter || (meta.category ? { 
        category: meta.category, 
        ...CATEGORY_INFO[meta.category] 
    } : null);

    if (filterInfo && filterInfo.category) {
        const catInfo = CATEGORY_INFO[filterInfo.category] || { label: filterInfo.category, icon: '🔍', color: '#6b7280' };
        filterTag = `<span class="message-filter-tag" style="background: ${catInfo.color}20; color: ${catInfo.color}; border: 1px solid ${catInfo.color}30;">
            ${catInfo.icon} ${catInfo.label}
        </span>`;
    }

    let chunksHtml = '';
    if (role === 'bot' && meta.chunks && meta.chunks.length > 0) {
        const chunkItems = meta.chunks.map(chunk => {
            const catInfo = CATEGORY_INFO[chunk.category] || { label: chunk.category, icon: '📄', color: '#6b7280' };
            return `
                <div class="chunk-item">
                    <div class="chunk-rank-row">
                        <span class="chunk-rank">#${chunk.rank}</span>
                        <span class="chunk-score">score: ${chunk.score}</span>
                    </div>
                    <div class="chunk-source">
                        📄 ${chunk.source}
                        <span class="chunk-source-badge" style="background: ${catInfo.color}20; color: ${catInfo.color};">${catInfo.icon} ${chunk.category}</span>
                    </div>
                    <div class="chunk-text">${escapeHtml(chunk.content.substring(0, 500))}</div>
                </div>
            `;
        }).join('');

        chunksHtml = `
            <div class="chunks-panel" style="${state.showChunks ? '' : 'display:none'}">
                <div class="chunks-header" onclick="toggleChunksPanel(this)">
                    <span class="chunks-title">📎 Retrieved Chunks (${meta.chunks.length})</span>
                    <span class="chunks-toggle-icon">▼</span>
                </div>
                <div class="chunks-body">
                    ${chunkItems}
                </div>
            </div>
        `;
    }

    let elapsedHtml = '';
    if (meta.elapsed) {
        elapsedHtml = `<span class="message-elapsed">⚡ ${meta.elapsed}ms</span>`;
    }

    // Format content for bot: convert newlines to <br>
    const formattedContent = role === 'bot' 
        ? formatBotContent(content) 
        : escapeHtml(content);

    msgEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-body">
            <div class="message-content">${formattedContent}</div>
            ${chunksHtml}
            <div class="message-meta">
                ${filterTag}
                ${elapsedHtml}
                <span class="message-time">${timeStr}</span>
            </div>
        </div>
    `;

    els.messages.appendChild(msgEl);
    scrollToBottom();
}

function formatBotContent(content) {
    let html = escapeHtml(content);
    // Convert markdown-style headers
    html = html.replace(/^## (.+)$/gm, '<strong style="color:var(--text-accent);font-size:15px;">$1</strong>');
    html = html.replace(/^# (.+)$/gm, '<strong style="color:var(--text-accent);font-size:16px;">$1</strong>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Newlines
    html = html.replace(/\n/g, '<br>');
    return html;
}

// ── Typing Indicator ────────────────────────────────────────────────────────
let typingCounter = 0;

function showTyping() {
    const id = `typing-${++typingCounter}`;
    const msgEl = document.createElement('div');
    msgEl.className = 'message bot';
    msgEl.id = id;
    msgEl.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-body">
            <div class="message-content">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `;
    els.messages.appendChild(msgEl);
    scrollToBottom();
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ── Chunks Panel Toggle ─────────────────────────────────────────────────────
window.toggleChunksPanel = function(headerEl) {
    const body = headerEl.nextElementSibling;
    const icon = headerEl.querySelector('.chunks-toggle-icon');
    body.classList.toggle('expanded');
    icon.classList.toggle('expanded');
};

// ── Clear Chat ──────────────────────────────────────────────────────────────
function clearChat() {
    els.messages.innerHTML = '';
    if (els.welcomeScreen) {
        els.messages.appendChild(els.welcomeScreen);
        els.welcomeScreen.style.display = '';
    }
    state.messages = [];
}

// ── Overlay ─────────────────────────────────────────────────────────────────
function toggleOverlay(show) {
    let overlay = $('.sidebar-overlay');
    if (!overlay && show) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay active';
        overlay.addEventListener('click', () => {
            els.sidebar.classList.remove('open');
            overlay.classList.remove('active');
        });
        document.body.appendChild(overlay);
    } else if (overlay) {
        overlay.classList.toggle('active', show);
    }
}

// ── Utilities ───────────────────────────────────────────────────────────────
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        els.messagesContainer.scrollTop = els.messagesContainer.scrollHeight;
    });
}
