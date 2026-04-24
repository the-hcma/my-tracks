/**
 * Tests for the My Tracks UI message helper.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showMessage, initMessages, MessageType, AUTO_DISMISS_MS } from './messages';

// Minimal DOM environment provided by jsdom (configured in vitest.config.ts).

function makeContainer(): HTMLDivElement {
    const el = document.createElement('div');
    document.body.appendChild(el);
    return el;
}

beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
});

afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    document.body.innerHTML = '';
});

describe('showMessage', () => {
    it('creates a message element with the correct type class', () => {
        const container = makeContainer();
        showMessage(container, 'success', 'Saved.');
        const msg = container.querySelector('.message');
        expect(msg).not.toBeNull();
        expect(msg?.classList.contains('success')).toBe(true);
    });

    it('sets the message text', () => {
        const container = makeContainer();
        showMessage(container, 'error', 'Something went wrong.');
        const text = container.querySelector('.message-text');
        expect(text?.textContent).toBe('Something went wrong.');
    });

    it('includes a dismiss button', () => {
        const container = makeContainer();
        showMessage(container, 'warning', 'Check this.');
        const btn = container.querySelector('.message-dismiss');
        expect(btn).not.toBeNull();
        expect(btn?.getAttribute('aria-label')).toBe('Dismiss');
    });

    it('sets role="alert" on the message element', () => {
        const container = makeContainer();
        showMessage(container, 'success', 'Done.');
        const msg = container.querySelector('.message');
        expect(msg?.getAttribute('role')).toBe('alert');
    });

    it('replaces any existing content in the container', () => {
        const container = makeContainer();
        container.innerHTML = '<p>old</p>';
        showMessage(container, 'success', 'New.');
        expect(container.querySelectorAll('.message').length).toBe(1);
        expect(container.querySelector('p')).toBeNull();
    });

    it('removes the message after 15 seconds by default', () => {
        const container = makeContainer();
        showMessage(container, 'success', 'Auto-dismiss.');
        expect(container.querySelector('.message')).not.toBeNull();
        vi.advanceTimersByTime(AUTO_DISMISS_MS);
        expect(container.querySelector('.message')).toBeNull();
    });

    it('does not auto-dismiss when autoDismiss is false', () => {
        const container = makeContainer();
        showMessage(container, 'error', 'Stay visible.', { autoDismiss: false });
        vi.advanceTimersByTime(60_000);
        expect(container.querySelector('.message')).not.toBeNull();
    });

    it('dismisses immediately when the dismiss button is clicked', () => {
        const container = makeContainer();
        showMessage(container, 'error', 'Click to dismiss.');
        const btn = container.querySelector<HTMLButtonElement>('.message-dismiss');
        btn?.click();
        expect(container.querySelector('.message')).toBeNull();
    });

    it('cancels the auto-dismiss timer when dismissed early', () => {
        const container = makeContainer();
        showMessage(container, 'success', 'Early dismiss.');
        const btn = container.querySelector<HTMLButtonElement>('.message-dismiss');
        btn?.click();
        // No uncleaned timers should fire after this
        vi.advanceTimersByTime(AUTO_DISMISS_MS);
        // Element is already removed; no errors should occur
        expect(container.querySelector('.message')).toBeNull();
    });

    it.each<MessageType>(['success', 'error', 'warning'])('supports type: %s', (type) => {
        const container = makeContainer();
        showMessage(container, type, 'Test.');
        const msg = container.querySelector('.message');
        expect(msg?.classList.contains(type)).toBe(true);
    });
});

describe('initMessages', () => {
    it('adds a dismiss button to existing .message elements', () => {
        document.body.innerHTML = '<div class="message success">Done.</div>';
        initMessages();
        const btn = document.querySelector('.message-dismiss');
        expect(btn).not.toBeNull();
    });

    it('auto-dismisses existing messages after 15 seconds', () => {
        document.body.innerHTML = '<div class="message error">Oops.</div>';
        initMessages();
        expect(document.querySelector('.message')).not.toBeNull();
        vi.advanceTimersByTime(AUTO_DISMISS_MS);
        expect(document.querySelector('.message')).toBeNull();
    });

    it('dismisses message on dismiss button click', () => {
        document.body.innerHTML = '<div class="message success">OK.</div>';
        initMessages();
        document.querySelector<HTMLButtonElement>('.message-dismiss')?.click();
        expect(document.querySelector('.message')).toBeNull();
    });

    it('does not double-initialize elements with data-msg-init', () => {
        document.body.innerHTML = '<div class="message success" data-msg-init="1">Already done.</div>';
        initMessages();
        // Only 0 dismiss buttons should be added (element already initialized)
        expect(document.querySelectorAll('.message-dismiss').length).toBe(0);
    });

    it('handles multiple messages independently', () => {
        document.body.innerHTML = `
            <div class="message success">First.</div>
            <div class="message error">Second.</div>
        `;
        initMessages();
        expect(document.querySelectorAll('.message-dismiss').length).toBe(2);
        // Dismiss only the first
        document.querySelectorAll<HTMLButtonElement>('.message-dismiss')[0]?.click();
        expect(document.querySelectorAll('.message').length).toBe(1);
        expect(document.querySelector('.message.error')).not.toBeNull();
    });
});
