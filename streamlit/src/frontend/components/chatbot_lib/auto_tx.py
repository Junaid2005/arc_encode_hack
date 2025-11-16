"""Auto-execute pending MetaMask transactions using Streamlit components."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def auto_execute_pending_tx() -> None:
    """Render a hidden component that auto-clicks the transaction button."""
    pending = st.session_state.get("chatbot_wallet_pending_command")
    if not pending or not isinstance(pending, dict):
        return

    if pending.get("command") != "send_transaction":
        return

    # Inject JavaScript that finds and clicks the transaction button
    html = """
    <script>
    (function() {
        console.log('[AutoTX] Searching for transaction button to auto-click...');
        
        function findAndClickButton() {
            const buttons = document.querySelectorAll('button');
            for (let btn of buttons) {
                const text = btn.textContent || '';
                if (text.includes('Repay') || 
                    text.includes('Send Transaction') || 
                    text.includes('Confirm Transaction') ||
                    text.includes('outstanding')) {
                    if (!btn.disabled) {
                        console.log('[AutoTX] Found button, clicking:', text);
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        }
        
        // Try immediately
        setTimeout(() => {
            if (findAndClickButton()) {
                console.log('[AutoTX] Successfully auto-clicked transaction button');
                return;
            }
            
            // Retry every 300ms for up to 5 seconds
            let attempts = 0;
            const interval = setInterval(() => {
                attempts++;
                console.log('[AutoTX] Retry attempt', attempts);
                
                if (findAndClickButton()) {
                    console.log('[AutoTX] Button clicked on attempt', attempts);
                    clearInterval(interval);
                } else if (attempts >= 16) {
                    console.error('[AutoTX] Transaction button not found after 5 seconds');
                    clearInterval(interval);
                }
            }, 300);
        }, 500);  // Initial delay to let DOM settle
    </script>
    <div style="display:none">AutoTX Active</div>
    """

    components.html(html, height=0)
