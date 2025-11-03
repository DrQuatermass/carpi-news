/**
 * Chatbot Widget per Ombra del Portico
 * Sistema di chat interattivo con backend Django
 */

class OmbraChatbot {
    constructor() {
        this.isOpen = false;
        this.messages = [];
        this.isTyping = false;

        // Elementi DOM
        this.toggleBtn = null;
        this.container = null;
        this.messagesArea = null;
        this.input = null;
        this.sendBtn = null;

        this.init();
    }

    init() {
        // Attendi che il DOM sia pronto
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    setup() {
        // Ottieni riferimenti agli elementi
        this.toggleBtn = document.getElementById('chatbot-toggle');
        this.container = document.getElementById('chatbot-container');
        this.messagesArea = document.getElementById('chatbot-messages');
        this.input = document.getElementById('chatbot-input');
        this.sendBtn = document.getElementById('chatbot-send');

        if (!this.toggleBtn || !this.container) {
            console.error('Chatbot: elementi DOM mancanti');
            return;
        }

        // Bind eventi
        this.toggleBtn.addEventListener('click', () => this.toggle());
        document.getElementById('chatbot-close')?.addEventListener('click', () => this.close());
        this.sendBtn?.addEventListener('click', () => this.sendMessage());
        this.input?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendMessage();
        });

        // Gestisci suggerimenti
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                this.input.value = chip.textContent;
                this.sendMessage();
            });
        });

        // Carica messaggi salvati
        this.loadMessages();

        // Messaggio di benvenuto
        if (this.messages.length === 0) {
            this.addBotMessage(
                'Ciao! Sono l\'assistente di Ombra del Portico. Come posso aiutarti oggi?'
            );
        }
    }

    toggle() {
        this.isOpen = !this.isOpen;
        if (this.isOpen) {
            this.open();
        } else {
            this.close();
        }
    }

    open() {
        this.isOpen = true;
        this.container.classList.add('active');
        this.input?.focus();
        this.scrollToBottom();

        // Rimuovi badge notifiche
        const badge = this.toggleBtn.querySelector('.chatbot-badge');
        if (badge) badge.remove();
    }

    close() {
        this.isOpen = false;
        this.container.classList.remove('active');
    }

    async sendMessage() {
        const message = this.input.value.trim();
        if (!message || this.isTyping) return;

        // Aggiungi messaggio utente
        this.addUserMessage(message);
        this.input.value = '';

        // Mostra typing indicator
        this.showTyping();

        try {
            // Invia al backend
            const response = await fetch('/api/chatbot/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    message: message,
                    conversation_history: this.messages.slice(-10) // Ultimi 10 messaggi
                })
            });

            if (!response.ok) {
                throw new Error('Errore nella richiesta');
            }

            const data = await response.json();

            // Rimuovi typing indicator
            this.hideTyping();

            // Aggiungi risposta bot
            this.addBotMessage(data.response);

        } catch (error) {
            console.error('Errore chatbot:', error);
            this.hideTyping();
            this.addBotMessage(
                'Mi dispiace, si è verificato un errore. Riprova più tardi.'
            );
        }
    }

    addUserMessage(text) {
        const message = {
            type: 'user',
            text: text,
            timestamp: new Date().toISOString()
        };

        this.messages.push(message);
        this.renderMessage(message);
        this.saveMessages();
        this.scrollToBottom();
    }

    addBotMessage(text) {
        const message = {
            type: 'bot',
            text: text,
            timestamp: new Date().toISOString()
        };

        this.messages.push(message);
        this.renderMessage(message);
        this.saveMessages();
        this.scrollToBottom();
    }

    renderMessage(message) {
        const messageEl = document.createElement('div');
        messageEl.className = `chatbot-message ${message.type}`;

        const time = new Date(message.timestamp).toLocaleTimeString('it-IT', {
            hour: '2-digit',
            minute: '2-digit'
        });

        if (message.type === 'bot') {
            messageEl.innerHTML = `
                <div class="message-avatar bot">🏛️</div>
                <div class="message-content">
                    ${this.escapeHtml(message.text)}
                    <div class="message-time">${time}</div>
                </div>
            `;
        } else {
            messageEl.innerHTML = `
                <div class="message-avatar user">👤</div>
                <div class="message-content">
                    ${this.escapeHtml(message.text)}
                    <div class="message-time">${time}</div>
                </div>
            `;
        }

        this.messagesArea.appendChild(messageEl);
    }

    showTyping() {
        this.isTyping = true;
        this.sendBtn.disabled = true;

        const typingEl = document.createElement('div');
        typingEl.className = 'chatbot-message bot';
        typingEl.id = 'typing-indicator';
        typingEl.innerHTML = `
            <div class="message-avatar bot">🏛️</div>
            <div class="message-content typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;

        this.messagesArea.appendChild(typingEl);
        this.scrollToBottom();
    }

    hideTyping() {
        this.isTyping = false;
        this.sendBtn.disabled = false;

        const typingEl = document.getElementById('typing-indicator');
        if (typingEl) typingEl.remove();
    }

    scrollToBottom() {
        setTimeout(() => {
            this.messagesArea.scrollTop = this.messagesArea.scrollHeight;
        }, 100);
    }

    saveMessages() {
        try {
            localStorage.setItem('chatbot-messages', JSON.stringify(this.messages));
        } catch (e) {
            console.error('Errore salvataggio messaggi:', e);
        }
    }

    loadMessages() {
        try {
            const saved = localStorage.getItem('chatbot-messages');
            if (saved) {
                this.messages = JSON.parse(saved);
                this.messages.forEach(msg => this.renderMessage(msg));
                this.scrollToBottom();
            }
        } catch (e) {
            console.error('Errore caricamento messaggi:', e);
            this.messages = [];
        }
    }

    clearHistory() {
        this.messages = [];
        this.messagesArea.innerHTML = '';
        localStorage.removeItem('chatbot-messages');
        this.addBotMessage('Cronologia cancellata. Come posso aiutarti?');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// Inizializza chatbot quando il DOM è pronto
let chatbot;
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        chatbot = new OmbraChatbot();
    });
} else {
    chatbot = new OmbraChatbot();
}
