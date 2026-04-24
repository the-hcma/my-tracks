/**
 * My Tracks — UI message helper.
 *
 * Provides showMessage() for consistent feedback messaging across all pages.
 * Auto-dismisses after AUTO_DISMISS_MS; can also be dismissed via the × button.
 *
 * Loading this script also injects the .message CSS so no per-template styles
 * are needed.
 *
 * Usage from inline template scripts:
 *   window.showMessage(container, 'success' | 'error' | 'warning', text);
 *   window.showMessage(container, 'error', text, { autoDismiss: false });
 */

export type MessageType = 'success' | 'error' | 'warning';

export interface ShowMessageOptions {
    /** Whether to auto-dismiss after AUTO_DISMISS_MS. Default: true. */
    autoDismiss?: boolean;
}

/** Duration in milliseconds before a message is automatically dismissed. */
export const AUTO_DISMISS_MS = 15_000;

const MESSAGE_CSS = `
.message {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    margin: 0.75rem 0;
    font-size: 0.875rem;
}
.message.success {
    background: rgba(39, 174, 96, 0.15);
    border: 1px solid var(--success, #27ae60);
    color: var(--success, #27ae60);
}
.message.error {
    background: rgba(231, 76, 60, 0.15);
    border: 1px solid var(--error, #e74c3c);
    color: var(--error, #e74c3c);
}
.message.warning {
    background: rgba(243, 156, 18, 0.15);
    border: 1px solid var(--warning, #f39c12);
    color: var(--warning, #f39c12);
}
.message-text { flex: 1; }
.message-dismiss {
    flex-shrink: 0;
    align-self: flex-start;
    background: none;
    border: none;
    color: inherit;
    cursor: pointer;
    font-size: 1.1rem;
    line-height: 1;
    padding: 0;
    margin-left: 0.5rem;
    opacity: 0.8;
}
.message-dismiss:hover { opacity: 1; }
`;

function injectStyles(): void {
    if (document.getElementById('my-tracks-message-styles')) return;
    const style = document.createElement('style');
    style.id = 'my-tracks-message-styles';
    style.textContent = MESSAGE_CSS;
    document.head.appendChild(style);
}

/**
 * Display a feedback message inside a container element.
 * Replaces any existing message in the container.
 *
 * @param container - Element to show the message in
 * @param type - 'success', 'error', or 'warning'
 * @param text - Message text
 * @param options - Optional configuration
 */
export function showMessage(
    container: HTMLElement,
    type: MessageType,
    text: string,
    options: ShowMessageOptions = {},
): void {
    injectStyles();
    const { autoDismiss = true } = options;

    const div = document.createElement('div');
    div.className = `message ${type}`;
    div.setAttribute('role', 'alert');

    const span = document.createElement('span');
    span.className = 'message-text';
    span.textContent = text;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'message-dismiss';
    btn.setAttribute('aria-label', 'Dismiss');
    btn.textContent = '\u00d7';

    div.appendChild(span);
    div.appendChild(btn);
    container.innerHTML = '';
    container.appendChild(div);

    let timer: ReturnType<typeof setTimeout> | null = null;

    btn.addEventListener('click', () => {
        if (timer !== null) clearTimeout(timer);
        div.remove();
    });

    if (autoDismiss) {
        timer = setTimeout(() => {
            if (div.parentNode) div.remove();
        }, AUTO_DISMISS_MS);
    }
}

/**
 * Initialize all server-rendered .message elements already in the DOM.
 * Adds a dismiss (×) button and a 15-second auto-dismiss timer.
 * Elements already initialized (data-msg-init attribute set) are skipped.
 */
export function initMessages(): void {
    injectStyles();
    document.querySelectorAll<HTMLElement>('.message:not([data-msg-init])').forEach(el => {
        el.dataset.msgInit = '1';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'message-dismiss';
        btn.setAttribute('aria-label', 'Dismiss');
        btn.textContent = '\u00d7';

        let timer: ReturnType<typeof setTimeout> | null = null;

        btn.addEventListener('click', () => {
            if (timer !== null) clearTimeout(timer);
            el.remove();
        });

        el.appendChild(btn);

        timer = setTimeout(() => {
            if (el.parentNode) el.remove();
        }, AUTO_DISMISS_MS);
    });
}

// Attach to window for use by inline template scripts
declare global {
    interface Window {
        showMessage: typeof showMessage;
        AUTO_DISMISS_MS: typeof AUTO_DISMISS_MS;
    }
}

window.showMessage = showMessage;
window.AUTO_DISMISS_MS = AUTO_DISMISS_MS;

// Auto-initialize server-rendered messages when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMessages);
} else {
    initMessages();
}
