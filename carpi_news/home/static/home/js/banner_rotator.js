/**
 * Banner Rotator — SEO-safe, leggero, con priorità ponderata
 *
 * Come funziona:
 *  1. Il server embeds il pool di banner come JSON in <script type="application/json">.
 *     Il primo banner è sempre server-rendered (ottimale per SEO/LCP).
 *  2. Questo script legge i pool, costruisce playlist pesate per priorità e avvia
 *     la rotazione via fade CSS solo quando il banner è nel viewport.
 *  3. Le impressioni dei banner ciclati sono tracciate via fetch non bloccante.
 *
 * Nessuna richiesta AJAX extra: tutti i dati sono già nell'HTML.
 */

const BannerRotatorSystem = (() => {
    // --- Configurazione ---
    const ROTATION_INTERVAL = 8000;  // ms tra una rotazione e la successiva
    const FADE_DURATION = 700;       // ms per il fade in/out
    const STAGGER_DELAY = 2000;      // ms di sfasamento tra slot diversi

    // Priority 1 (massima) → 5 slot nella playlist, Priority 5 → 1 slot
    const PRIORITY_WEIGHTS = { 1: 5, 2: 4, 3: 3, 4: 2, 5: 1 };

    // Map elemento DOM → funzione di cleanup
    const rotatorCleanup = new WeakMap();

    // Pool per posizione: { 'header': [...], 'between_articles': [...] }
    const pools = {};

    // --- Stili CSS (iniettati una volta sola) ---
    function injectStyles() {
        if (document.getElementById('banner-rotator-styles')) return;
        const style = document.createElement('style');
        style.id = 'banner-rotator-styles';
        // Transizione solo sull'img, NON sul container — il box rimane sempre visibile
        style.textContent = '.banner-img{transition:opacity ' + FADE_DURATION + 'ms ease}';
        document.head.appendChild(style);
    }

    // --- Costruzione playlist pesata ---
    function buildWeightedPlaylist(banners) {
        // Ordina per priorità crescente (1 = massima priorità prima)
        const sorted = [...banners].sort((a, b) => a.priority - b.priority);
        const playlist = [];
        sorted.forEach(banner => {
            const weight = PRIORITY_WEIGHTS[banner.priority] || 1;
            for (let i = 0; i < weight; i++) {
                playlist.push(banner);
            }
        });
        return playlist;
    }

    // --- Selezione pesata casuale escludendo il banner corrente ---
    function pickNext(playlist, excludeId) {
        const candidates = playlist.filter(b => b.id !== excludeId);
        const pool = candidates.length > 0 ? candidates : playlist;
        return pool[Math.floor(Math.random() * pool.length)];
    }

    // --- Inizializza rotatore per un singolo elemento ---
    function initRotator(container, playlist, slotIndex) {
        if (!container || !playlist || playlist.length <= 1) return;

        // Distribuisce i punti di partenza tra slot diversi
        const startIndex = slotIndex * Math.floor(playlist.length / Math.max(1, slotIndex + 1)) % playlist.length;
        let currentIndex = startIndex;
        let timer = null;
        let isVisible = false;
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        function swapBanner(banner) {
            if (reducedMotion) {
                applyBanner(banner);
                trackImpression(banner.id);
                preloadNext();
                return;
            }
            const img = container.querySelector('.banner-img');
            if (!img) {
                applyBanner(banner);
                trackImpression(banner.id);
                preloadNext();
                return;
            }
            // Preload prima di iniziare il fade: quando parte l'animazione
            // la nuova immagine è già in cache → nessun flash bianco
            const preload = new Image();
            preload.onload = () => {
                // Blocca l'altezza corrente per evitare layout shift durante lo swap
                const lockedHeight = img.offsetHeight;
                img.style.height = lockedHeight + 'px';
                img.style.opacity = '0';
                setTimeout(() => {
                    applyBanner(banner);
                    // Rilascia l'altezza bloccata: la nuova immagine può cambiare dimensioni
                    img.style.height = '';
                    img.style.opacity = '1';
                    trackImpression(banner.id);
                    preloadNext();
                }, FADE_DURATION);
            };
            preload.onerror = () => {
                applyBanner(banner);
                trackImpression(banner.id);
                preloadNext();
            };
            preload.src = banner.image_url;
        }

        function applyBanner(banner) {
            const img = container.querySelector('.banner-img');
            const link = container.querySelector('.banner-link');
            const adDiv = container.closest
                ? container.querySelector('.advertisement-banner') || container
                : container;

            if (img) {
                img.src = banner.image_url;
                img.alt = banner.alt_text;
                if (banner.image_width) img.width = banner.image_width;
                if (banner.image_height) img.height = banner.image_height;
            }
            if (link) {
                link.href = banner.click_url;
            }
            if (adDiv && adDiv.dataset) {
                adDiv.dataset.bannerId = banner.id;
            }
        }

        function preloadNext() {
            const next = playlist[(currentIndex + 1) % playlist.length];
            if (next && next.image_url) {
                const img = new Image();
                img.src = next.image_url;
            }
        }

        function rotate() {
            if (document.hidden || !isVisible) return;
            const next = pickNext(playlist, playlist[currentIndex].id);
            currentIndex = playlist.indexOf(next);
            swapBanner(next);
        }

        function startRotation() {
            if (timer) return;
            // Stagger: il primo slot parte dopo ROTATION_INTERVAL + 0*STAGGER_DELAY,
            // il secondo dopo ROTATION_INTERVAL + 1*STAGGER_DELAY, ecc.
            const initialDelay = ROTATION_INTERVAL + slotIndex * STAGGER_DELAY;
            timer = setTimeout(function loop() {
                rotate();
                timer = setTimeout(loop, ROTATION_INTERVAL);
            }, initialDelay);
        }

        function stopRotation() {
            clearTimeout(timer);
            timer = null;
        }

        // IntersectionObserver: avvia/ferma in base alla visibilità
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    isVisible = true;
                    startRotation();
                } else {
                    isVisible = false;
                    stopRotation();
                }
            });
        }, { threshold: 0.1 });
        observer.observe(container);

        // Ferma quando la tab è nascosta, riprende quando torna visibile
        const visibilityHandler = () => {
            if (document.hidden) {
                stopRotation();
            } else if (isVisible) {
                startRotation();
            }
        };
        document.addEventListener('visibilitychange', visibilityHandler);

        // Preload prima immagine del ciclo successivo
        preloadNext();

        // Registra cleanup
        rotatorCleanup.set(container, () => {
            stopRotation();
            observer.disconnect();
            document.removeEventListener('visibilitychange', visibilityHandler);
        });
    }

    // --- Tracking impressioni (non bloccante) ---
    function trackImpression(bannerId) {
        const url = '/admin-panel/banner/' + bannerId + '/impression/';
        fetch(url, { cache: 'no-store', keepalive: true }).catch(() => {});
    }

    // --- Lettura pool dal DOM ---
    function loadPools() {
        document.querySelectorAll('script.banner-pool-data[type="application/json"]').forEach(script => {
            try {
                const position = script.dataset.position;
                if (!position) return;
                const data = JSON.parse(script.textContent);
                if (Array.isArray(data) && data.length > 1) {
                    // Se la posizione ha già un pool, unisci senza duplicati
                    if (pools[position]) {
                        const existingIds = new Set(pools[position].map(b => b.id));
                        data.forEach(b => { if (!existingIds.has(b.id)) pools[position].push(b); });
                    } else {
                        pools[position] = data;
                    }
                }
            } catch (e) { /* pool non valido, ignora */ }
        });

        // Trasforma ogni pool in playlist pesata
        Object.keys(pools).forEach(pos => {
            pools[pos] = buildWeightedPlaylist(pools[pos]);
        });
    }

    // --- Inizializzazione di tutti i rotatori nella pagina ---
    function init() {
        injectStyles();
        loadPools();

        // Conta gli slot per posizione per calcolare l'indice di stagger
        const slotCountByPosition = {};

        document.querySelectorAll('[data-banner-pool]').forEach(container => {
            const position = container.dataset.bannerPool;
            if (!pools[position]) return;

            if (!slotCountByPosition[position]) slotCountByPosition[position] = 0;
            const slotIndex = slotCountByPosition[position]++;

            initRotator(container, pools[position], slotIndex);
        });
    }

    // --- Re-init per banner inseriti via AJAX (es. navigazione homepage) ---
    function reinitGrid() {
        // Rilegge pool script eventualmente aggiunti (di solito non necessario)
        document.querySelectorAll('script.banner-pool-data[type="application/json"]').forEach(script => {
            try {
                const position = script.dataset.position;
                if (!position || pools[position]) return;  // già caricato
                const data = JSON.parse(script.textContent);
                if (Array.isArray(data) && data.length > 1) {
                    pools[position] = buildWeightedPlaylist(data);
                }
            } catch (e) { /* ignora */ }
        });

        // Conta slot esistenti già inizializzati per posizione
        const existingCount = {};
        document.querySelectorAll('[data-banner-pool]').forEach(el => {
            if (rotatorCleanup.has(el)) {
                const pos = el.dataset.bannerPool;
                existingCount[pos] = (existingCount[pos] || 0) + 1;
            }
        });

        // Inizializza i nuovi elementi
        document.querySelectorAll('[data-banner-pool]').forEach(container => {
            if (rotatorCleanup.has(container)) return;  // già inizializzato
            const position = container.dataset.bannerPool;
            if (!pools[position]) return;
            const slotIndex = existingCount[position] || 0;
            if (!existingCount[position]) existingCount[position] = 0;
            existingCount[position]++;
            initRotator(container, pools[position], slotIndex);
        });
    }

    // Risponde all'evento emesso da homepage.js dopo navigazione AJAX
    window.addEventListener('bannerGridUpdated', reinitGrid);

    return { init, reinitGrid };
})();

document.addEventListener('DOMContentLoaded', () => BannerRotatorSystem.init());
window.BannerRotatorSystem = BannerRotatorSystem;
