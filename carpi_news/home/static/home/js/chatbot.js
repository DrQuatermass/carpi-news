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

        // NON caricare messaggi salvati - chat sempre pulita all'avvio
    }

    showWelcomeMessage() {
        // IMPORTANTE: Pulisci TUTTO prima di mostrare il benvenuto
        this.messages = [];
        this.messagesArea.innerHTML = '';

        // Pulisci anche localStorage
        try {
            localStorage.removeItem('chatbot-messages');
        } catch (e) {
            console.error('Errore pulizia localStorage:', e);
        }

        // Mostra messaggio di benvenuto
        this.addBotMessage(
            'Ciao! Sono l\'assistente virtuale di Ombra del Portico.\n\n' +
            'Posso aiutarti a cercare articoli e rispondere alle tue domande su Carpi.\n\n' +
            '**Esempi:**\n' +
            '• "Eventi di domani"\n' +
            '• "Cosa è successo lunedì?"\n' +
            '• "Notizie di ottobre"\n' +
            '• "Chi è il sindaco?"\n' +
            '• "Articoli su Aimag"\n' +
            '• "Ultime notizie di sport"'
        );
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

        // Mostra sempre messaggio di benvenuto all'apertura
        this.showWelcomeMessage();
        this.scrollToBottom();

        // Rimuovi badge notifiche
        const badge = this.toggleBtn.querySelector('.chatbot-badge');
        if (badge) badge.remove();
    }

    close() {
        this.isOpen = false;
        this.container.classList.remove('active');

        // Pulisci messaggi quando si chiude la chat
        this.clearMessages();
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

            // Se ci sono articoli, gestisci redirect
            if (data.articles && data.articles.length > 0) {
                if (data.articles.length === 1) {
                    // Un solo articolo: redirect diretto
                    this.addBotMessage('Ti porto all\'articolo...');
                    setTimeout(() => {
                        window.location.href = data.articles[0].url;
                    }, 1000);
                } else {
                    // Multipli articoli - distingui tra ricerca e domanda
                    // Se la risposta è lunga (>100 caratteri), è probabilmente una risposta AI per una domanda
                    // In quel caso NON mostrare card per non distrarre dalla risposta
                    const responseLength = data.response ? data.response.length : 0;
                    const isLongResponse = responseLength > 100;

                    console.log('🤖 CHATBOT DEBUG:', {
                        responseLength: responseLength,
                        isLong: isLongResponse,
                        showCards: !isLongResponse,
                        articlesCount: data.articles.length
                    });

                    if (!isLongResponse) {
                        // Risposta breve = ricerca normale: mostra card preview
                        console.log('📇 Mostro card preview');
                        this.addArticlesCarousel(data.articles.slice(0, 3));
                    } else {
                        console.log('🚫 NON mostro card (risposta lunga)');
                    }
                    // Risposta lunga = domanda: solo bottone, niente card

                    // Crea URL per pagina risultati
                    const params = new URLSearchParams({
                        q: message,
                        intent: JSON.stringify(data.intent),
                        session_id: data.session_id
                    });
                    const resultsUrl = `/chatbot/risultati/?${params.toString()}`;

                    // Aggiungi bottone per vedere tutti
                    this.addViewAllButton(resultsUrl, data.articles.length);
                }
            }

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

    addBotMessage(text, articles = null) {
        const message = {
            type: 'bot',
            text: text,
            timestamp: new Date().toISOString(),
            articles: articles
        };

        this.messages.push(message);
        this.renderMessage(message);
        this.saveMessages();
        this.scrollToBottom();
    }

    addArticlesCarousel(articles) {
        /**
         * Aggiunge un carosello di articoli alla chat
         */
        const carouselEl = document.createElement('div');
        carouselEl.className = 'chatbot-message bot';

        let articlesHtml = '<div class="articles-carousel">';

        articles.forEach(article => {
            const date = new Date(article.data_pubblicazione).toLocaleDateString('it-IT', {
                day: 'numeric',
                month: 'short'
            });

            const imageUrl = article.foto || '/static/home/images/placeholder.jpg';

            articlesHtml += `
                <a href="${article.url}" class="article-card">
                    <div class="article-image" style="background-image: url('${imageUrl}')"></div>
                    <div class="article-content">
                        <span class="article-category">${article.categoria}</span>
                        <h4 class="article-title">${this.escapeHtml(article.titolo)}</h4>
                        <p class="article-summary">${this.escapeHtml(article.sommario)}</p>
                        <span class="article-date">${date}</span>
                    </div>
                </a>
            `;
        });

        articlesHtml += '</div>';

        carouselEl.innerHTML = `
            <div class="message-avatar bot">🏛️</div>
            <div class="message-content articles-content">
                ${articlesHtml}
            </div>
        `;

        this.messagesArea.appendChild(carouselEl);
        this.scrollToBottom();
    }

    addViewAllButton(url, totalCount) {
        /**
         * Aggiunge un bottone per vedere tutti i risultati
         */
        const buttonEl = document.createElement('div');
        buttonEl.className = 'chatbot-message bot';

        buttonEl.innerHTML = `
            <div class="message-avatar bot">🏛️</div>
            <div class="message-content">
                <a href="${url}" class="view-all-button">
                    Vedi tutti i ${totalCount} articoli →
                </a>
            </div>
        `;

        this.messagesArea.appendChild(buttonEl);
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

    clearMessages() {
        // Pulisci messaggi e localStorage
        this.messages = [];
        this.messagesArea.innerHTML = '';
        try {
            localStorage.removeItem('chatbot-messages');
        } catch (e) {
            console.error('Errore pulizia messaggi:', e);
        }
    }

    saveMessages() {
        // Non salviamo più i messaggi - chat sempre pulita
        // Manteniamo la funzione per compatibilità
    }

    loadMessages() {
        // Non carichiamo più messaggi salvati - chat sempre pulita
        // Manteniamo la funzione per compatibilità
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
