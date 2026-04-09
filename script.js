class SpotifyPlaylistHelper {
    constructor() {
        this.clientId = null;
        this.clientSecret = null;
        this.redirectUri = null;
        this.accessToken = null;
        this.currentResults = null;
        this.currentSort = { column: null, direction: 'asc' };
        this.currentFilters = { genre: '', artistText: '' };
        this.filtersEnabled = false;
        this.init();
    }

    async init() {
        await this.loadCredentials();
        this.bindEvents();
        this.checkUrlParams();
    }

    bindEvents() {
        const credentialsForm = document.getElementById('credentials-form');
        const runQueryBtns = document.querySelectorAll('.run-query-btn');

        credentialsForm.addEventListener('submit', (e) => this.handleCredentialsSubmit(e));

        runQueryBtns.forEach(btn => {
            btn.addEventListener('click', (e) => this.handleQueryRun(e));
        });
    }

    // Secure credential storage using Web Crypto API
    async encryptData(data, password) {
        const encoder = new TextEncoder();
        const key = await crypto.subtle.importKey(
            'raw',
            encoder.encode(password.padEnd(32, '0').slice(0, 32)),
            { name: 'AES-GCM' },
            false,
            ['encrypt']
        );

        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encrypted = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv },
            key,
            encoder.encode(data)
        );

        return {
            encrypted: Array.from(new Uint8Array(encrypted)),
            iv: Array.from(iv)
        };
    }

    async decryptData(encryptedData, password) {
        try {
            const encoder = new TextEncoder();
            const decoder = new TextDecoder();

            const key = await crypto.subtle.importKey(
                'raw',
                encoder.encode(password.padEnd(32, '0').slice(0, 32)),
                { name: 'AES-GCM' },
                false,
                ['decrypt']
            );

            const decrypted = await crypto.subtle.decrypt(
                { name: 'AES-GCM', iv: new Uint8Array(encryptedData.iv) },
                key,
                new Uint8Array(encryptedData.encrypted)
            );

            return decoder.decode(decrypted);
        } catch (error) {
            console.error('Decryption failed:', error);
            return null;
        }
    }

    async saveCredentials(clientId, clientSecret, redirectUri) {
        const credentials = JSON.stringify({ clientId, clientSecret, redirectUri });
        const password = 'spotify-helper-' + Date.now();

        try {
            const encrypted = await this.encryptData(credentials, password);
            localStorage.setItem('spotify-credentials', JSON.stringify(encrypted));
            localStorage.setItem('spotify-key', password);

            this.clientId = clientId;
            this.clientSecret = clientSecret;
            this.redirectUri = redirectUri;

            return true;
        } catch (error) {
            console.error('Failed to save credentials:', error);
            return false;
        }
    }

    async loadCredentials() {
        const encryptedData = localStorage.getItem('spotify-credentials');
        const password = localStorage.getItem('spotify-key');

        if (encryptedData && password) {
            try {
                const parsed = JSON.parse(encryptedData);
                const decrypted = await this.decryptData(parsed, password);

                if (decrypted) {
                    const credentials = JSON.parse(decrypted);
                    this.clientId = credentials.clientId;
                    this.clientSecret = credentials.clientSecret;
                    this.redirectUri = credentials.redirectUri;

                    // Pre-fill form
                    document.getElementById('client-id').value = this.clientId;
                    document.getElementById('client-secret').value = this.clientSecret;
                    document.getElementById('redirect-uri').value = this.redirectUri;

                    this.showAuthStatus('Credentials loaded successfully', 'success');
                }
            } catch (error) {
                console.error('Failed to load credentials:', error);
            }
        }
    }

    checkUrlParams() {
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        const error = urlParams.get('error');

        if (error) {
            this.showAuthStatus('Authentication failed: ' + error, 'error');
            return;
        }

        if (code) {
            // Make sure we have credentials before trying to exchange the code
            if (!this.clientId || !this.clientSecret || !this.redirectUri) {
                console.error('Missing credentials for token exchange');
                this.showAuthStatus('Missing credentials. Please re-enter your API credentials.', 'error');
                return;
            }

            this.exchangeCodeForToken(code);
            // Clean up URL
            window.history.replaceState({}, document.title, window.location.pathname);
        }
    }

    async handleCredentialsSubmit(e) {
        e.preventDefault();

        const clientId = document.getElementById('client-id').value.trim();
        const clientSecret = document.getElementById('client-secret').value.trim();
        const redirectUri = document.getElementById('redirect-uri').value.trim();

        if (!clientId || !clientSecret || !redirectUri) {
            this.showAuthStatus('Please fill in all credential fields', 'error');
            return;
        }

        const isLoopback = redirectUri.startsWith('http://127.0.0.1') || redirectUri.startsWith('http://[::1]');
        const isHttps = redirectUri.startsWith('https://');
        if (!isLoopback && !isHttps) {
            this.showAuthStatus('Redirect URI must use HTTPS, or a loopback address like http://127.0.0.1:8080. Spotify no longer allows http://localhost.', 'error');
            return;
        }

        const saved = await this.saveCredentials(clientId, clientSecret, redirectUri);

        if (saved) {
            this.showAuthStatus('Credentials saved successfully', 'success');
            this.initiateSpotifyAuth();
        } else {
            this.showAuthStatus('Failed to save credentials', 'error');
        }
    }

    showAuthStatus(message, type) {
        const statusDiv = document.getElementById('auth-status');
        statusDiv.textContent = message;
        statusDiv.className = `status-message ${type}`;
    }

    initiateSpotifyAuth() {
        if (!this.clientId || !this.redirectUri) {
            this.showAuthStatus('Missing credentials', 'error');
            return;
        }

        const scope = 'user-library-read playlist-read-private playlist-read-collaborative';
        const authUrl = `https://accounts.spotify.com/authorize?` +
            `client_id=${encodeURIComponent(this.clientId)}&` +
            `response_type=code&` +
            `redirect_uri=${encodeURIComponent(this.redirectUri)}&` +
            `scope=${encodeURIComponent(scope)}&` +
            `show_dialog=true`;

        window.location.href = authUrl;
    }

    async exchangeCodeForToken(code) {
        try {
            this.showAuthStatus('Exchanging code for access token...', 'success');

            console.log('Exchanging code:', code);
            console.log('Client ID:', this.clientId);
            console.log('Redirect URI:', this.redirectUri);

            const response = await fetch('https://accounts.spotify.com/api/token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Authorization': 'Basic ' + btoa(this.clientId + ':' + this.clientSecret)
                },
                body: new URLSearchParams({
                    grant_type: 'authorization_code',
                    code: code,
                    redirect_uri: this.redirectUri
                })
            });

            console.log('Response status:', response.status);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
                console.error('Token exchange error details:', errorData);
                throw new Error(`Token exchange failed: ${response.status} - ${errorData.error_description || errorData.error || 'Unknown error'}`);
            }

            const data = await response.json();
            console.log('Token exchange successful');
            this.accessToken = data.access_token;

            this.showAuthStatus('Successfully authenticated with Spotify!', 'success');
            this.showQueriesSection();

        } catch (error) {
            console.error('Token exchange failed:', error);
            this.showAuthStatus('Failed to authenticate with Spotify: ' + error.message, 'error');
        }
    }

    showQueriesSection() {
        document.getElementById('queries-section').style.display = 'block';
        document.getElementById('credentials-section').style.display = 'none';
    }


    async handleQueryRun(e) {
        const queryType = e.target.closest('.query-item').dataset.query;

        if (!this.accessToken) {
            this.showAuthStatus('Please authenticate with Spotify first', 'error');
            return;
        }

        const loadingMessages = {
            'liked-songs-not-in-playlists': 'Finding liked songs not in any playlist…',
            'all-liked-songs': 'Loading all liked songs…',
            'playlist-browser': 'Fetching your playlists…'
        };

        this.currentSort = { column: null, direction: 'asc' };
        this.resetFilters();
        this.showResultsSection();
        this.showLoading(true, loadingMessages[queryType] || 'Analyzing your Spotify data...');

        try {
            switch (queryType) {
                case 'liked-songs-not-in-playlists':
                    await this.findLikedSongsNotInPlaylists();
                    break;
                case 'all-liked-songs':
                    await this.getAllLikedSongsAnalysis();
                    break;
                case 'playlist-browser':
                    await this.browsePlaylistsMode();
                    break;
                default:
                    throw new Error('Unknown query type');
            }
        } catch (error) {
            console.error('Query failed:', error);
            this.showError('Query failed: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    async findLikedSongsNotInPlaylists() {
        const likedSongs = await this.getLikedSongs();
        const playlistTracks = await this.getAllPlaylistTracks();

        const playlistTrackIds = new Set(playlistTracks.map(t => t.id));
        const uniqueLikedSongs = likedSongs.filter(t => !playlistTrackIds.has(t.id));

        // Enrich tracks with genre data
        const enrichedTracks = await this.enrichTracksWithGenres(uniqueLikedSongs);

        this.currentResults = {
            tracks: enrichedTracks,
            totalLikedSongs: likedSongs.length,
            totalPlaylistTracks: playlistTracks.length
        };
        this.filtersEnabled = true;

        this.displayResults(enrichedTracks, likedSongs.length, playlistTracks.length);
    }

    async getAllLikedSongsAnalysis() {
        const likedSongs = await this.getLikedSongs();

        // Enrich tracks with genre data
        const enrichedTracks = await this.enrichTracksWithGenres(likedSongs);

        // Fetch playlist membership for each track
        const playlistMap = await this.getPlaylistTrackMap();
        enrichedTracks.forEach(track => {
            const playlists = playlistMap.get(track.id) ?? [];
            track.playlistCount = playlists.length;
            track.playlistNames = playlists;
        });

        this.currentResults = {
            tracks: enrichedTracks,
            totalLikedSongs: likedSongs.length,
            totalPlaylistTracks: 0,
            isAnalysisMode: true,
            playlistMap
        };
        this.filtersEnabled = true;

        // Generate analytics
        const analytics = this.generateAnalytics(enrichedTracks);
        this.currentResults.analytics = analytics;

        this.displayAnalytics(analytics);
        this.displayResults(enrichedTracks, likedSongs.length, 0);
    }


    async browsePlaylistsMode() {
        const playlists = await this.getUserPlaylists();

        this.currentResults = {
            playlists: playlists,
            isPlaylistMode: true
        };

        this.displayPlaylistsList(playlists);
    }

    displayPlaylistsList(playlists) {
        const resultsContent = document.getElementById('results-content');
        const analyticsSection = document.getElementById('analytics-section');

        // Hide analytics for playlist mode
        analyticsSection.style.display = 'none';

        let html = `
            <div class="results-summary">
                <strong>Your Playlists</strong><br>
                Found ${playlists.length} playlists. Click on any playlist to view its songs.<br>
            </div>
            <div class="continuous-table-container">
                <table class="continuous-tracks-table">
                    <thead>
                        <tr>
                            <th>Playlist Name</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        playlists.forEach(playlist => {
            html += `
                <tr class="track-row">
                    <td class="playlist-name">${this.escapeHtml(playlist.name)}</td>
                    <td class="playlist-actions">
                        <button class="view-playlist-btn" data-playlist-id="${playlist.id}" data-playlist-name="${this.escapeHtml(playlist.name)}">
                            View Songs
                        </button>
                    </td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
        `;

        resultsContent.innerHTML = html;

        // Add event listeners for playlist viewing
        document.querySelectorAll('.view-playlist-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.handleViewPlaylist(e));
        });
    }

    async handleViewPlaylist(e) {
        const playlistId = e.target.dataset.playlistId;
        const playlistName = e.target.dataset.playlistName;

        this.showLoading(true);

        try {
            const tracks = await this.getPlaylistTracks(playlistId);

            this.currentResults = {
                tracks: tracks,
                playlistName: playlistName,
                playlistId: playlistId,
                isPlaylistView: true
            };

            this.displayPlaylistTracks(tracks, playlistName);
        } catch (error) {
            console.error('Failed to load playlist tracks:', error);
            this.showError('Failed to load playlist tracks: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }

    displayPlaylistTracks(tracks, playlistName) {
        const resultsContent = document.getElementById('results-content');
        const analyticsSection = document.getElementById('analytics-section');

        // Hide analytics for playlist view
        analyticsSection.style.display = 'none';

        let html = `
            <div class="results-summary">
                <strong>Playlist: ${this.escapeHtml(playlistName)}</strong><br>
                ${tracks.length} songs in this playlist<br>
                <button class="back-to-playlists-btn" style="margin-top: 10px;">← Back to Playlists</button>
                <button class="copy-playlist-btn" data-playlist-name="${this.escapeHtml(playlistName)}" style="margin-top: 10px; margin-left: 10px;">Copy Song List</button>
            </div>
        `;

        if (tracks.length > 0) {
            html += this.generatePlaylistTracksTable(tracks);
        } else {
            html += '<p>This playlist is empty.</p>';
        }

        resultsContent.innerHTML = html;

        // Add event listeners
        const backBtn = document.querySelector('.back-to-playlists-btn');
        if (backBtn) {
            backBtn.addEventListener('click', () => this.browsePlaylistsMode());
        }

        const copyBtn = document.querySelector('.copy-playlist-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', (e) => this.copyPlaylistToClipboard(e));
        }
    }

    generatePlaylistTracksTable(tracks) {
        let html = `
            <div class="continuous-table-container">
                <table class="continuous-tracks-table">
                    <thead>
                        <tr>
                            <th>Track</th>
                            <th>Artists</th>
                            <th>Open</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        tracks.forEach(track => {
            html += `
                <tr class="track-row">
                    <td class="track-name">${this.escapeHtml(track.name)}</td>
                    <td class="track-artist">${this.escapeHtml(track.artists)}</td>
                    <td class="track-link">
                        <a href="${track.url}" target="_blank" rel="noopener noreferrer" class="spotify-link">
                            🎵
                        </a>
                    </td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
        `;

        return html;
    }

    async copyPlaylistToClipboard(e) {
        const playlistName = e.target.dataset.playlistName;
        const tracks = this.currentResults.tracks;

        // Format the track list for copying
        let textToCopy = `${playlistName}\n\n`;
        tracks.forEach((track, index) => {
            textToCopy += `${index + 1}. ${track.name} - ${track.artists}\n`;
        });

        try {
            await navigator.clipboard.writeText(textToCopy);

            // Show feedback
            const originalText = e.target.textContent;
            e.target.textContent = 'Copied!';
            e.target.style.background = '#28a745';

            setTimeout(() => {
                e.target.textContent = originalText;
                e.target.style.background = '';
            }, 2000);

        } catch (error) {
            console.error('Failed to copy to clipboard:', error);
            // Fallback: show the text in an alert or text area
            this.showCopyFallback(textToCopy);
        }
    }

    showCopyFallback(textToCopy) {
        // Create a modal-like overlay with selectable text
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        `;

        const modal = document.createElement('div');
        modal.style.cssText = `
            background: white;
            padding: 20px;
            border-radius: 8px;
            max-width: 500px;
            max-height: 400px;
            overflow-y: auto;
        `;

        modal.innerHTML = `
            <h3>Copy Song List</h3>
            <p>Select all text below and copy manually:</p>
            <textarea readonly style="width: 100%; height: 200px; font-family: monospace;">${textToCopy}</textarea>
            <br><br>
            <button onclick="this.closest('.overlay').remove()">Close</button>
        `;

        overlay.className = 'overlay';
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Auto-select the text
        const textarea = modal.querySelector('textarea');
        textarea.select();
    }

    async getLikedSongs() {
        const tracks = [];
        let url = 'https://api.spotify.com/v1/me/tracks?limit=50';

        while (url) {
            const response = await this.spotifyApiCall(url);
            tracks.push(...response.items.map(item => ({
                id: item.track.id,
                name: item.track.name,
                artists: item.track.artists.map(artist => artist.name).join(', '),
                artistIds: item.track.artists.map(artist => artist.id),
                url: item.track.external_urls.spotify
            })));
            url = response.next;
        }

        return tracks;
    }

    async getAllPlaylistTracks() {
        const playlists = await this.getUserPlaylists();
        const allTracks = [];

        for (const playlist of playlists) {
            const tracks = await this.getPlaylistTracks(playlist.id);
            allTracks.push(...tracks);
        }

        return allTracks;
    }

    async getPlaylistTrackMap() {
        const playlists = await this.getUserPlaylists();
        const map = new Map();

        for (const playlist of playlists) {
            const tracks = await this.getPlaylistTracks(playlist.id);
            for (const track of tracks) {
                if (!map.has(track.id)) map.set(track.id, []);
                map.get(track.id).push(playlist.name);
            }
        }

        return map;
    }

    async getUserPlaylists() {
        const playlists = [];
        let url = 'https://api.spotify.com/v1/me/playlists?limit=50';

        while (url) {
            const response = await this.spotifyApiCall(url);
            playlists.push(...response.items.map(playlist => ({
                id: playlist.id,
                name: playlist.name
            })));
            url = response.next;
        }

        return playlists;
    }

    async getPlaylistTracks(playlistId) {
        const tracks = [];
        let url = `https://api.spotify.com/v1/playlists/${playlistId}/tracks?limit=100`;

        while (url) {
            const response = await this.spotifyApiCall(url);
            const validTracks = response.items
                .filter(item => item.track && item.track.id)
                .map(item => ({
                    id: item.track.id,
                    name: item.track.name,
                    artists: item.track.artists.map(artist => artist.name).join(', '),
                    artistIds: item.track.artists.map(artist => artist.id),
                    url: item.track.external_urls.spotify
                }));
            tracks.push(...validTracks);
            url = response.next;
        }

        return tracks;
    }

    async spotifyApiCall(url) {
        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${this.accessToken}`
            }
        });

        if (!response.ok) {
            if (response.status === 401) {
                throw new Error('Access token expired. Please re-authenticate.');
            }
            throw new Error(`API call failed: ${response.status} ${response.statusText}`);
        }

        return response.json();
    }

    async enrichTracksWithGenres(tracks) {
        const artistIds = [...new Set(tracks.flatMap(track => track.artistIds || []))];

        if (artistIds.length === 0) {
            return tracks.map(track => ({ ...track, genres: [] }));
        }

        // Group artist IDs into batches of 50 (Spotify API limit)
        const artistBatches = [];
        for (let i = 0; i < artistIds.length; i += 50) {
            artistBatches.push(artistIds.slice(i, i + 50));
        }

        const artistGenreMap = new Map();

        for (const batch of artistBatches) {
            try {
                const artistsData = await this.getArtistsDetails(batch);
                for (const artist of artistsData) {
                    console.log(`Artist: ${artist.name}, Genres:`, artist.genres, `Popularity: ${artist.popularity}, Followers: ${artist.followers.total}`); // Debug logging
                    artistGenreMap.set(artist.id, {
                        genres: artist.genres,
                        popularity: artist.popularity,
                        followers: artist.followers.total,
                        name: artist.name
                    });
                }
            } catch (error) {
                console.error('Failed to fetch artist genres:', error);
            }
        }

        // Enrich tracks with genre and popularity data
        return tracks.map(track => {
            const genres = new Set();
            const artistPopularities = [];
            const artistFollowers = [];
            const artistNames = [];

            if (track.artistIds && track.artistIds.length > 0) {
                track.artistIds.forEach(artistId => {
                    const artistData = artistGenreMap.get(artistId);
                    if (artistData) {
                        artistData.genres.forEach(genre => genres.add(genre));
                        artistPopularities.push(artistData.popularity);
                        artistFollowers.push(artistData.followers);
                        artistNames.push(artistData.name);
                    }
                });
            }

            // Try to infer genres from similar artists or use broader categorization
            if (genres.size === 0) {
                // Fallback: categorize as "Unknown Genre" instead of "No Genre"
                genres.add('Unknown Genre');
            }

            // Calculate average popularity for tracks with multiple artists
            const avgPopularity = artistPopularities.length > 0
                ? artistPopularities.reduce((sum, pop) => sum + pop, 0) / artistPopularities.length
                : 0;

            const totalFollowers = artistFollowers.reduce((sum, followers) => sum + followers, 0);

            return {
                ...track,
                genres: Array.from(genres),
                popularity: avgPopularity,
                followers: totalFollowers,
                artistNames: artistNames
            };
        });
    }

    async getArtistsDetails(artistIds) {
        const url = `https://api.spotify.com/v1/artists?ids=${artistIds.join(',')}`;
        const response = await this.spotifyApiCall(url);
        return response.artists;
    }

    showResultsSection() {
        const resultsSection = document.getElementById('results-section');
        resultsSection.style.display = 'block';
        requestAnimationFrame(() => resultsSection.scrollIntoView({ behavior: 'smooth' }));
    }

    showLoading(show, message = 'Analyzing your Spotify data...') {
        const loadingEl = document.getElementById('loading');
        loadingEl.style.display = show ? 'block' : 'none';
        if (show) loadingEl.querySelector('p').textContent = message;
        document.getElementById('results-content').style.display = show ? 'none' : 'block';
    }


    resetFilters() {
        this.currentFilters = { genre: '', artistText: '' };
        this.filtersEnabled = false;
    }

    applyFilters(tracks) {
        if (!this.filtersEnabled) return tracks;
        const { genre, artistText } = this.currentFilters;
        return tracks.filter(track => {
            if (genre && !(track.genres || []).includes(genre)) return false;
            if (artistText && !track.artists.toLowerCase().includes(artistText.toLowerCase())) return false;
            return true;
        });
    }

    handleFilterChange(type, value) {
        if (type === 'genre') {
            this.currentFilters.genre = value;
        } else if (type === 'artist') {
            this.currentFilters.artistText = value;
        } else if (type === 'clear') {
            this.currentFilters = { genre: '', artistText: '' };
            const genreEl = document.getElementById('genre-filter');
            const artistEl = document.getElementById('artist-filter');
            if (genreEl) genreEl.value = '';
            if (artistEl) artistEl.value = '';
        }
        this.refreshTable();
    }

    refreshTable() {
        const tableEl = document.getElementById('track-table-only');
        if (!tableEl) return;
        tableEl.innerHTML = this.generateContinuousTable(this.currentResults.tracks);
        const countEl = document.getElementById('filter-track-count');
        if (countEl) {
            const n = this.applyFilters(this.currentResults.tracks).length;
            countEl.textContent = `${n} of ${this.currentResults.tracks.length} tracks`;
        }
    }

    generateFilterBar(tracks) {
        const allGenres = [...new Set(tracks.flatMap(t => t.genres || []))]
            .filter(g => g && g !== 'Unknown Genre')
            .sort();
        const allArtists = [...new Set(tracks.flatMap(t => t.artists.split(', ').map(a => a.trim())))]
            .sort();

        const genreOptions = allGenres
            .map(g => `<option value="${this.escapeHtml(g)}">${this.escapeHtml(g)}</option>`)
            .join('');
        const artistOptions = allArtists
            .map(a => `<option value="${this.escapeHtml(a)}">`)
            .join('');

        const filteredCount = this.applyFilters(tracks).length;

        return `
            <div class="filter-controls">
                <div class="filter-row">
                    <div class="filter-group">
                        <label for="genre-filter">Genre</label>
                        <select id="genre-filter" class="filter-select" onchange="window._app.handleFilterChange('genre', this.value)">
                            <option value="">All Genres</option>
                            ${genreOptions}
                        </select>
                    </div>
                    <div class="filter-group">
                        <label for="artist-filter">Artist</label>
                        <input id="artist-filter" class="filter-text-input" type="text"
                               list="artist-datalist" placeholder="Search artist…"
                               oninput="window._app.handleFilterChange('artist', this.value)">
                        <datalist id="artist-datalist">${artistOptions}</datalist>
                    </div>
                    <span id="filter-track-count" class="filter-count">${filteredCount} of ${tracks.length} tracks</span>
                    <button class="filter-clear" onclick="window._app.handleFilterChange('clear', null)">Clear</button>
                </div>
            </div>
        `;
    }

    displayResults(tracks, totalLikedSongs, totalPlaylistTracks) {
        const resultsContent = document.getElementById('results-content');
        const analyticsSection = document.getElementById('analytics-section');

        // Hide analytics section for non-analytics queries
        if (!this.currentResults?.isAnalysisMode) {
            analyticsSection.style.display = 'none';
        }

        let html = '';

        if (this.currentResults?.isAnalysisMode) {
            const analytics = this.currentResults.analytics;

            html += `
                <div class="results-summary">
                    <strong>All Liked Songs Analysis Complete!</strong><br>
                    Analyzed ${totalLikedSongs} liked songs with ${analytics?.uniqueGenres || 0} unique genres and ${analytics?.uniqueArtists || 0} unique artists.<br>
                </div>
            `;
            html += this.generateCoverageBar(tracks, totalLikedSongs);
        } else {
            html += `
                <div class="results-summary">
                    <strong>Analysis Complete!</strong><br>
                    Found ${tracks.length} songs in your Liked Songs that are not in any of your playlists.<br>
                    <small>Analyzed ${totalLikedSongs} liked songs and ${totalPlaylistTracks} playlist tracks.</small>
                </div>
            `;
        }

        if (tracks.length > 0) {
            if (this.filtersEnabled) html += this.generateFilterBar(this.currentResults.tracks);
            html += `<div id="track-table-only">`;
            html += this.generateContinuousTable(tracks);
            html += `</div>`;
        } else {
            html += '<p>All your liked songs are already in your playlists!</p>';
        }

        resultsContent.innerHTML = html;
    }

    sortedTracks(tracks) {
        const { column, direction } = this.currentSort;
        if (!column) return tracks;

        return [...tracks].sort((a, b) => {
            let aVal, bVal;
            if (column === 'name') { aVal = a.name.toLowerCase(); bVal = b.name.toLowerCase(); }
            else if (column === 'artists') { aVal = a.artists.toLowerCase(); bVal = b.artists.toLowerCase(); }
            else if (column === 'popularity') { aVal = a.popularity || 0; bVal = b.popularity || 0; }
            else if (column === 'playlists') { aVal = a.playlistCount || 0; bVal = b.playlistCount || 0; }
            if (aVal < bVal) return direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return direction === 'asc' ? 1 : -1;
            return 0;
        });
    }

    sortTable(column) {
        if (this.currentSort.column === column) {
            this.currentSort.direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
            this.currentSort = { column, direction: column === 'playlists' || column === 'popularity' ? 'desc' : 'asc' };
        }
        if (this.currentResults) {
            if (this.filtersEnabled) {
                this.refreshTable();
            } else {
                this.displayResults(this.currentResults.tracks, this.currentResults.totalLikedSongs, this.currentResults.totalPlaylistTracks);
            }
        }
    }

    generateContinuousTable(tracks) {
        const filtered = this.applyFilters(tracks);
        const sorted = this.sortedTracks(filtered);
        const isAnalysis = this.currentResults?.isAnalysisMode;

        const sortIcon = (col) => {
            if (this.currentSort.column !== col) return '<span class="sort-icon">⇅</span>';
            return `<span class="sort-icon active">${this.currentSort.direction === 'asc' ? '▲' : '▼'}</span>`;
        };

        let html = `
            <div class="continuous-table-container">
                <table class="continuous-tracks-table">
                    <thead>
                        <tr>
                            <th class="sortable" onclick="window._app.sortTable('name')">Track ${sortIcon('name')}</th>
                            <th class="sortable" onclick="window._app.sortTable('artists')">Artists ${sortIcon('artists')}</th>
                            <th>Genre</th>
                            <th class="sortable" onclick="window._app.sortTable('popularity')">Popularity ${sortIcon('popularity')}</th>
                            ${isAnalysis ? `<th class="sortable" onclick="window._app.sortTable('playlists')">Playlists ${sortIcon('playlists')}</th>` : ''}
                            <th>Open</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        sorted.forEach(track => {
            html += `
                <tr class="track-row">
                    <td class="track-name">${this.escapeHtml(track.name)}</td>
                    <td class="track-artist">${this.escapeHtml(track.artists)}</td>
                    <td class="track-genre">${this.escapeHtml((track.genres || []).filter(g => g !== 'Unknown Genre').join(', ') || '—')}</td>
                    <td class="track-popularity">${Math.round(track.popularity || 0)}</td>
                    ${isAnalysis ? `<td class="track-playlist-count" title="${this.escapeHtml((track.playlistNames || []).join(', ') || 'Not in any playlist')}">${track.playlistCount > 0 ? track.playlistCount : '—'}</td>` : ''}
                    <td class="track-link">
                        <a href="${track.url}" target="_blank" rel="noopener noreferrer" class="spotify-link">🎵</a>
                    </td>
                </tr>
            `;
        });

        html += `</tbody></table></div>`;
        return html;
    }

    sanitizeId(str) {
        return str.replace(/[^a-zA-Z0-9]/g, '_');
    }

    generateAnalytics(tracks) {
        // Genre analysis
        const genreCounts = {};
        const artistCounts = {};

        tracks.forEach(track => {
            // Count genres
            if (track.genres && track.genres.length > 0) {
                // Filter out 'Unknown Genre' if there are other real genres
                const realGenres = track.genres.filter(g => g !== 'Unknown Genre');
                if (realGenres.length > 0) {
                    realGenres.forEach(genre => {
                        genreCounts[genre] = (genreCounts[genre] || 0) + 1;
                    });
                } else {
                    genreCounts['Unknown Genre'] = (genreCounts['Unknown Genre'] || 0) + 1;
                }
            } else {
                genreCounts['Unknown Genre'] = (genreCounts['Unknown Genre'] || 0) + 1;
            }

            // Count artists
            if (track.artists) {
                artistCounts[track.artists] = (artistCounts[track.artists] || 0) + 1;
            }
        });

        // Sort and get top items
        const topGenres = Object.entries(genreCounts)
            .sort(([,a], [,b]) => b - a)
            .slice(0, 10);

        const topArtists = Object.entries(artistCounts)
            .sort(([,a], [,b]) => b - a)
            .slice(0, 10);

        return {
            totalTracks: tracks.length,
            genreCounts,
            artistCounts,
            topGenres,
            topArtists,
            uniqueGenres: Object.keys(genreCounts).length,
            uniqueArtists: Object.keys(artistCounts).length
        };
    }

    displayAnalytics(analytics) {
        const analyticsSection = document.getElementById('analytics-section');
        analyticsSection.style.display = 'block';

        // Destroy existing charts if they exist
        if (this.genreChart) this.genreChart.destroy();
        if (this.artistChart) this.artistChart.destroy();

        this.createGenreChart(analytics);
        this.createArtistChart(analytics);
    }

    createGenreChart(analytics) {
        const ctx = document.getElementById('genreChart').getContext('2d');

        const colors = [
            '#1db954', '#1ed760', '#1aa34a', '#169c46', '#128f42',
            '#0e823e', '#0a753a', '#066836', '#025b32', '#004e2e'
        ];

        this.genreChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: analytics.topGenres.map(([genre]) => genre),
                datasets: [{
                    data: analytics.topGenres.map(([, count]) => count),
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: {
                    padding: 10
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 12,
                            fontSize: 11,
                            padding: 8,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = analytics.totalTracks;
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} songs (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    createArtistChart(analytics) {
        const ctx = document.getElementById('artistChart').getContext('2d');

        this.artistChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: analytics.topArtists.map(([artist]) =>
                    artist.length > 15 ? artist.substring(0, 15) + '...' : artist
                ),
                datasets: [{
                    label: 'Number of Songs',
                    data: analytics.topArtists.map(([, count]) => count),
                    backgroundColor: '#1db954',
                    borderColor: '#169c46',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: {
                    padding: {
                        left: 10,
                        right: 10,
                        top: 10,
                        bottom: 10
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            title: function(context) {
                                // Show full artist name in tooltip
                                const fullName = analytics.topArtists[context[0].dataIndex][0];
                                return fullName;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            fontSize: 10
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            fontSize: 10
                        }
                    }
                }
            }
        });
    }


    generateCoverageBar(tracks, totalLikedSongs) {
        const playlistMap = this.currentResults?.playlistMap;
        if (!playlistMap) return '';

        const covered = tracks.filter(t => playlistMap.has(t.id)).length;
        const pct = totalLikedSongs > 0 ? Math.round(covered / totalLikedSongs * 100) : 0;

        return `
            <div class="coverage-bar-container">
                <div class="coverage-bar-label">Playlist Coverage: ${covered} / ${totalLikedSongs} songs (${pct}%)</div>
                <div class="coverage-bar-track">
                    <div class="coverage-bar-fill" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    }

    showError(message) {
        const resultsContent = document.getElementById('results-content');
        resultsContent.innerHTML = `
            <div class="status-message error">
                ${this.escapeHtml(message)}
            </div>
        `;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize the app when the page loads
document.addEventListener('DOMContentLoaded', async () => {
    window._app = new SpotifyPlaylistHelper();
});