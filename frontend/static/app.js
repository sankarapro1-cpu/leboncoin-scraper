/**
 * AutoDeal — Application Alpine.js
 * Dashboard principal + gestion des annonces
 */
function app() {
  return {
    // Navigation
    currentTab: 'dashboard',

    // Données
    stats: {},
    bestDeals: [],
    listings: [],
    savedListings: [],
    selectedListing: null,

    // Filtres
    filters: {
      min_score: 0,
      max_price: null,
      min_year: null,
      max_km: null,
      brand: '',
      sort_by: 'score',
    },

    // Pagination
    pagination: { page: 1, pages: 1, total: 0, per_page: 20 },

    // État scraping
    isScrapingRunning: false,
    nextRun: null,

    // UI
    loading: false,
    toasts: [],

    // SSE
    _sseSource: null,

    // ─── Init ───
    async init() {
      await Promise.all([
        this.loadStats(),
        this.loadBestDeals(),
        this.loadNextRun(),
      ]);
      this.setupSSE();
      // Rafraîchir les stats toutes les 60s
      setInterval(() => { this.loadStats(); this.loadNextRun(); }, 60000);
    },

    // ─── Navigation ───
    async setTab(tab) {
      this.currentTab = tab;
      document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-item')[['dashboard','listings','saved'].indexOf(tab)]?.classList.add('active');

      if (tab === 'listings') await this.loadListings();
      if (tab === 'saved') await this.loadSaved();
    },

    // ─── API calls ───
    async loadStats() {
      try {
        const res = await fetch('/api/stats');
        this.stats = await res.json();
      } catch (e) { console.error('Stats:', e); }
    },

    async loadBestDeals() {
      try {
        const res = await fetch('/api/listings/best-deals?limit=12');
        this.bestDeals = await res.json();
      } catch (e) { console.error('Best deals:', e); }
    },

    async loadListings() {
      this.loading = true;
      try {
        const params = new URLSearchParams();
        params.set('page', this.pagination.page);
        params.set('per_page', this.pagination.per_page);
        params.set('sort_by', this.filters.sort_by);
        if (this.filters.min_score) params.set('min_score', this.filters.min_score);
        if (this.filters.max_price) params.set('max_price', this.filters.max_price);
        if (this.filters.min_year) params.set('min_year', this.filters.min_year);
        if (this.filters.max_km) params.set('max_km', this.filters.max_km);
        if (this.filters.brand) params.set('brand', this.filters.brand);

        const res = await fetch(`/api/listings?${params}`);
        const data = await res.json();
        this.listings = data.listings;
        this.pagination = { page: data.page, pages: data.pages, total: data.total, per_page: data.per_page };
      } catch (e) { console.error('Listings:', e); }
      this.loading = false;
    },

    async loadSaved() {
      try {
        const res = await fetch('/api/listings?is_saved=true&per_page=100');
        const data = await res.json();
        this.savedListings = data.listings;
      } catch (e) { console.error('Saved:', e); }
    },

    async loadNextRun() {
      try {
        const res = await fetch('/api/scrape/next-run');
        const data = await res.json();
        this.nextRun = data.next_run;
      } catch (e) {}
    },

    // ─── Scraping ───
    async triggerScrape() {
      if (this.isScrapingRunning) return;
      this.isScrapingRunning = true;
      try {
        await fetch('/api/scrape/start', { method: 'POST' });
        this.showToast('Scan lancé ! Les résultats apparaîtront dans quelques minutes.', 'success');
        // Vérifier le statut toutes les 5s
        const interval = setInterval(async () => {
          await this.loadStats();
          if (this.stats.last_scrape?.status !== 'running') {
            this.isScrapingRunning = false;
            clearInterval(interval);
            await Promise.all([this.loadBestDeals(), this.loadStats()]);
            if (this.currentTab === 'listings') this.loadListings();
          }
        }, 5000);
        setTimeout(() => {
          clearInterval(interval);
          this.isScrapingRunning = false;
        }, 300000); // Timeout 5 min
      } catch (e) {
        this.isScrapingRunning = false;
        this.showToast('Erreur lors du lancement du scan', 'error');
      }
    },

    // ─── Actions annonces ───
    async openListing(listing) {
      // Charger le détail complet
      try {
        const res = await fetch(`/api/listings/${listing.id}`);
        this.selectedListing = await res.json();
      } catch {
        this.selectedListing = listing;
      }
    },

    async toggleSave(listing) {
      const newVal = !listing.is_saved;
      try {
        await fetch(`/api/listings/${listing.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_saved: newVal }),
        });
        listing.is_saved = newVal;
        if (this.selectedListing?.id === listing.id) this.selectedListing.is_saved = newVal;
        this.showToast(newVal ? '★ Annonce sauvegardée' : 'Annonce retirée', 'success');
        if (this.currentTab === 'saved') await this.loadSaved();
      } catch {
        this.showToast('Erreur lors de la sauvegarde', 'error');
      }
    },

    async markContacted(listing) {
      const newVal = !listing.is_contacted;
      try {
        await fetch(`/api/listings/${listing.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_contacted: newVal }),
        });
        listing.is_contacted = newVal;
        if (this.selectedListing?.id === listing.id) this.selectedListing.is_contacted = newVal;
      } catch {}
    },

    async saveNote(listing) {
      if (!listing.user_note) return;
      try {
        await fetch(`/api/listings/${listing.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_note: listing.user_note }),
        });
        this.showToast('Note enregistrée', 'success');
      } catch {}
    },

    // ─── Pagination ───
    async goToPage(page) {
      if (page < 1 || page > this.pagination.pages) return;
      this.pagination.page = page;
      await this.loadListings();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    paginationPages() {
      const pages = [];
      const { page, pages: total } = this.pagination;
      const delta = 2;
      for (let i = Math.max(1, page - delta); i <= Math.min(total, page + delta); i++) {
        pages.push(i);
      }
      return pages;
    },

    // ─── Filtres ───
    resetFilters() {
      this.filters = { min_score: 0, max_price: null, min_year: null, max_km: null, brand: '', sort_by: 'score' };
      this.pagination.page = 1;
      this.loadListings();
    },

    // ─── SSE (notifications temps réel) ───
    setupSSE() {
      if (!window.EventSource) return;
      try {
        this._sseSource = new EventSource('/api/alerts/stream');
        this._sseSource.onmessage = (event) => {
          const data = JSON.parse(event.data);
          if (data.type === 'new_deal') {
            this.showToast(`🔥 Nouvelle affaire détectée ! Score ${data.score}/100 — ${data.title}`, 'success');
            this.loadBestDeals();
            this.loadStats();
            // Notification navigateur
            this.sendBrowserNotification(data);
          }
        };
        this._sseSource.onerror = () => {
          // Reconnexion automatique après 5s
          setTimeout(() => this.setupSSE(), 5000);
        };
      } catch (e) {}
    },

    sendBrowserNotification(data) {
      if (!('Notification' in window)) return;
      if (Notification.permission === 'granted') {
        new Notification('🚗 AutoDeal — Bonne affaire !', {
          body: `Score ${data.score}/100 — ${data.title}\nPrix : ${data.price}€`,
          icon: '/static/icon.png',
        });
      } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(perm => {
          if (perm === 'granted') this.sendBrowserNotification(data);
        });
      }
    },

    // ─── Formatters ───
    formatPrice(price) {
      if (!price) return '—';
      return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(price);
    },

    formatKm(km) {
      if (!km) return '— km';
      return new Intl.NumberFormat('fr-FR').format(km) + ' km';
    },

    formatDate(iso) {
      if (!iso) return '—';
      return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    },

    formatDeviation(pct) {
      if (!pct) return '';
      const sign = pct < 0 ? '' : '+';
      return `${sign}${pct.toFixed(1)}% vs marché`;
    },

    formatNextRun() {
      if (!this.nextRun) return '—';
      const diff = Math.round((new Date(this.nextRun) - Date.now()) / 60000);
      if (diff <= 0) return 'imminent';
      return `dans ${diff} min`;
    },

    scoreClass(score) {
      if (!score && score !== 0) return 'score-neutral';
      if (score >= 70) return 'score-high';
      if (score >= 50) return 'score-medium';
      return 'score-low';
    },

    // ─── Toasts ───
    showToast(message, type = 'info') {
      const id = Date.now();
      this.toasts.push({ id, message, type });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 4000);
    },
  };
}


/**
 * App Settings (page paramètres)
 */
function settingsApp() {
  return {
    profiles: [],
    showProfileModal: false,
    editingProfile: null,
    profileForm: {},
    toasts: [],

    async init() {
      await this.loadProfiles();
    },

    async loadProfiles() {
      try {
        const res = await fetch('/api/profiles');
        this.profiles = await res.json();
      } catch (e) { console.error(e); }
    },

    openNewProfile() {
      this.editingProfile = null;
      this.profileForm = { location_radius_km: 100 };
      this.showProfileModal = true;
    },

    editProfile(profile) {
      this.editingProfile = profile;
      this.profileForm = { ...profile };
      this.showProfileModal = true;
    },

    async saveProfile() {
      try {
        const url = this.editingProfile ? `/api/profiles/${this.editingProfile.id}` : '/api/profiles';
        const method = this.editingProfile ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.profileForm),
        });
        if (!res.ok) throw new Error('Erreur');
        await this.loadProfiles();
        this.showProfileModal = false;
        this.showToast(this.editingProfile ? 'Profil mis à jour' : 'Profil créé', 'success');
      } catch {
        this.showToast('Erreur lors de la sauvegarde', 'error');
      }
    },

    async toggleProfile(profile) {
      try {
        const res = await fetch(`/api/profiles/${profile.id}/toggle`, { method: 'POST' });
        const data = await res.json();
        profile.is_active = data.is_active;
        this.showToast(data.is_active ? 'Profil activé' : 'Profil désactivé', 'success');
      } catch {
        this.showToast('Erreur', 'error');
      }
    },

    async deleteProfile(profile) {
      if (!confirm(`Supprimer le profil "${profile.name}" ?`)) return;
      try {
        await fetch(`/api/profiles/${profile.id}`, { method: 'DELETE' });
        await this.loadProfiles();
        this.showToast('Profil supprimé', 'success');
      } catch {
        this.showToast('Erreur', 'error');
      }
    },

    formatPrice(price) {
      if (!price) return '—';
      return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(price);
    },

    formatKm(km) {
      if (!km) return '—';
      return new Intl.NumberFormat('fr-FR').format(km) + ' km';
    },

    showToast(message, type = 'info') {
      const id = Date.now();
      this.toasts.push({ id, message, type });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 4000);
    },
  };
}
