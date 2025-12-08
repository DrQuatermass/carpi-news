// Homepage JavaScript - Navigation and Page Transitions
// Variabili globali minime - leggono i dati dall'elemento page-data
const pageData = document.getElementById('page-data');
let currentPage = parseInt(pageData?.dataset.currentPage || '1');
let totalPages = parseInt(pageData?.dataset.totalPages || '1');
let isTransitioning = false;
let parallaxHandler = null;
let keyboardHandler = null;
let isInitialized = false;

// Helper function per calcolo parallasse
function updateParallax(hero) {
    if (!hero || isTransitioning) return;
    const scrolled = window.scrollY;
    hero.style.transform = `translateY(${scrolled * -0.5}px)`;
}

// Inizializzazione specifica della homepage
function initPageSpecific() {
    // Evita inizializzazioni multiple
    if (isInitialized) return;
    isInitialized = true;

    // Animazione al caricamento
    const loadingElements = document.querySelectorAll('.loading');
    loadingElements.forEach((element, index) => {
        setTimeout(() => {
            element.style.animationDelay = (index * 0.1) + 's';
        }, index * 100);
    });

    // Animazione parallasse per hero
    const hero = document.querySelector('.hero');
    parallaxHandler = () => updateParallax(hero);
    window.addEventListener('scroll', parallaxHandler, { passive: true });

    // Event listeners per i pulsanti di navigazione
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');

    if (prevBtn) {
        prevBtn.addEventListener('click', function() {
            if (!this.disabled) changePage(-1);
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', function() {
            if (!this.disabled) changePage(1);
        });
    }

    // Keyboard navigation
    keyboardHandler = function(e) {
        const prevBtn = document.getElementById('prev-btn');
        const nextBtn = document.getElementById('next-btn');
        if (e.key === 'ArrowLeft' && prevBtn && !prevBtn.disabled) {
            changePage(-1);
        } else if (e.key === 'ArrowRight' && nextBtn && !nextBtn.disabled) {
            changePage(1);
        }
    };
    document.addEventListener('keydown', keyboardHandler);
}

// Funzione per cambiare pagina con transizioni
function changePage(direction) {
    if (isTransitioning) {
        return;
    }

    const newPage = currentPage + direction;

    if (newPage >= 1 && newPage <= totalPages) {
        isTransitioning = true;

        // Scroll smooth in alto
        window.scrollTo({ top: 0, behavior: 'smooth' });

        // Determina la direzione dell'animazione
        const slideOutClass = direction > 0 ? 'slide-out-left' : 'slide-out-right';
        const slideInClass = direction > 0 ? 'slide-in-right' : 'slide-in-left';

        // Aggiungi classe di transizione al grid
        const newsGrid = document.getElementById('news-grid');
        newsGrid.classList.add('transitioning');

        // Salva l'altezza corrente della griglia per evitare layout shift
        const newsNav = document.querySelector('.news-nav');
        const currentHeight = newsNav.offsetHeight;
        newsNav.style.minHeight = currentHeight + 'px';

        // Blocca temporaneamente l'effetto parallasse
        const hero = document.querySelector('.hero');
        if (hero) hero.style.transform = 'translateY(0px)';

        // Mostra loading spinner
        const loadingSpinner = document.getElementById('loading-spinner');
        loadingSpinner.classList.add('active');

        // Avvia animazione di uscita
        const existingCards = newsGrid.querySelectorAll('.news-card');
        existingCards.forEach((card, index) => {
            setTimeout(() => {
                card.classList.add(slideOutClass);
            }, index * 30);
        });

        // Carica nuovi dati
        loadPageContent(newPage);
    }
}

// Funzione per caricare il contenuto della pagina via AJAX
function loadPageContent(pageNumber) {
    // Costruisci URL mantenendo la categoria attiva
    const urlParams = new URLSearchParams(window.location.search);
    const categoria = urlParams.get('categoria');
    const url = `?page=${pageNumber}${categoria ? '&categoria=' + encodeURIComponent(categoria) : ''}`;

    const xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                const data = JSON.parse(xhr.responseText);
                updatePageContent(data);
            } else {
                window.location.href = url;
            }
        }
    };

    xhr.send();
}

// Funzione per aggiornare il contenuto della pagina
function updatePageContent(data) {
    const newsGrid = document.getElementById('news-grid');
    const loadingSpinner = document.getElementById('loading-spinner');

    loadingSpinner.classList.remove('active');

    // Attendi la fine dell'animazione di uscita
    setTimeout(() => {
        // Rimuovi le card esistenti e i banner (tranne spinner e footer)
        const existingItems = newsGrid.querySelectorAll('.news-card-link, .banner-card-slot');
        existingItems.forEach(item => {
            // Non rimuovere il banner footer (è l'ultimo nella griglia)
            if (!item.classList.contains('banner-footer-slot')) {
                item.remove();
            }
        });

        // Usa le posizioni dei banner dal server
        const bannerPositions = data.banner_positions || [];
        const numBannerSlots = data.num_banner_slots || 0;
        const activeBanners = data.active_banners || [];

        let articleIndex = 0;
        let bannerSlotIndex = 0;
        const footerBanner = newsGrid.querySelector('.banner-footer-slot');
        const totalSlots = 8 + numBannerSlots;  // 8 articoli + 4 banner slots = 12 totali

        // Inserisci elementi (articoli + banner)
        for (let position = 0; position < totalSlots; position++) {
            if (bannerPositions.includes(position)) {
                // Trova il banner attivo per questo slot (se esiste)
                const activeBanner = activeBanners.find(b => b.position_index === bannerSlotIndex);

                if (activeBanner) {
                    // Inserisci banner attivo
                    const bannerElement = createActiveBanner(activeBanner);
                    newsGrid.insertBefore(bannerElement, footerBanner);
                } else {
                    // Inserisci placeholder
                    const placeholderHTML = `
                        <a href="/admin-panel/" class="banner-card-slot" rel="nofollow" aria-label="Spazio pubblicitario disponibile - Clicca per acquistare">
                        </a>
                    `;
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = placeholderHTML;
                    const bannerElement = tempDiv.firstElementChild;
                    newsGrid.insertBefore(bannerElement, footerBanner);
                }
                bannerSlotIndex++;
            } else {
                // Inserisci articolo
                if (articleIndex < data.articoli.length) {
                    const cardLink = createNewsCard(data.articoli[articleIndex]);
                    newsGrid.insertBefore(cardLink, footerBanner);
                    articleIndex++;
                }
            }
        }

        // Aggiorna stato della paginazione
        currentPage = data.current_page;
        totalPages = data.total_pages;
        updateNavigationButtons(data.has_prev, data.has_next);

        // Aggiorna URL
        const url = new URL(window.location);
        url.searchParams.set('page', currentPage);
        window.history.pushState({}, '', url);

        newsGrid.classList.remove('transitioning');
        isTransitioning = false;
    }, 250);
}

// Funzione per costruire URL immagine
const DEFAULT_IMAGE = '/static/home/images/portico_logo_nopayoff.png';
const SITE_URL = window.location.origin;

function buildImageUrl(foto) {
    if (!foto) return DEFAULT_IMAGE;
    if (foto.startsWith('http://') || foto.startsWith('https://')) return foto;
    if (foto.startsWith('/')) return SITE_URL + foto;
    return foto;
}

// Funzione per creare un banner attivo
function createActiveBanner(banner) {
    const bannerSlot = document.createElement('div');
    bannerSlot.className = 'banner-card-slot has-active-banner';

    bannerSlot.innerHTML = `
        <div class="advertisement-banner" data-banner-id="${banner.id}" style="width: 100%;">
            <a href="/admin-panel/banner/${banner.id}/click/" target="_blank" rel="noopener noreferrer nofollow sponsored" style="display: block; width: 100%;">
                <img src="${banner.image_url}" alt="${banner.alt_text}" width="${banner.image_width}" height="${banner.image_height}" loading="lazy" style="width: 100%; height: auto; border-radius: 10px; display: block; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);">
            </a>
            <div style="font-size: 10px; color: #999; text-align: center; margin-top: 5px;">Pubblicità</div>
        </div>
    `;

    return bannerSlot;
}

// Funzione per creare una card di notizia
function createNewsCard(articolo) {
    const cardLink = document.createElement('a');
    cardLink.href = `/articolo/${articolo.slug}/`;
    cardLink.className = 'news-card-link';

    const card = document.createElement('article');
    card.className = 'news-card';

    const imageUrl = buildImageUrl(articolo.foto);

    card.innerHTML = `
        <div class="news-image">
            <img src="${imageUrl}"
                 alt="${articolo.titolo}"
                 class="card-img"
                 loading="lazy"
                 onerror="this.onerror=null; this.src='${DEFAULT_IMAGE}';">
        </div>
        <div class="news-content">
            <div class="news-meta">
                <span class="category-tag">${articolo.categoria}</span>
                <time datetime="${articolo.data_pubblicazione}">${articolo.data_pubblicazione}</time>
            </div>
            <h2 class="news-title">${articolo.titolo}</h2>
            <p class="news-excerpt">${articolo.sommario}</p>
            <span class="read-more">Leggi tutto →</span>
        </div>
    `;

    cardLink.appendChild(card);
    return cardLink;
}

// Funzione per aggiornare i pulsanti di navigazione
function updateNavigationButtons(hasPrev, hasNext) {
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');

    prevBtn.disabled = !hasPrev;
    nextBtn.disabled = !hasNext;
}

// Inizializza quando il DOM è pronto
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageSpecific);
} else {
    initPageSpecific();
}
