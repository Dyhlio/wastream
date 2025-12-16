// ===========================
// Translations
// ===========================
const translations = {
    en: {
        title: 'WAStream Configuration',
        sections: {
            languages: 'Languages',
            quality: 'Quality',
            service: 'Service',
            advanced: 'Advanced',
            security: 'Security'
        },
        labels: {
            preferredLanguages: 'Preferred languages',
            resolutions: 'Resolutions',
            maxResults: 'Max results per resolution',
            maxSize: 'Max size (GB)',
            debridService: 'Debrid service',
            debridApiKey: 'Debrid API Key',
            hosts: 'Hosts',
            sources: 'Sources',
            tmdbToken: 'TMDB Token',
            timeout: 'Timeout (seconds)',
            excludedKeywords: 'Excluded keywords',
            password: 'Password'
        },
        placeholders: {
            allHosts: 'All hosts (default)',
            allSources: 'All sources (default)'
        },
        toggles: {
            cachedOnly: 'Cached links only',
            enableUsenet: 'Enable Usenet (TorBox only)',
            fullSeasonPacks: 'Include Full Season Packs (Usenet)'
        },
        help: {
            languagesEmpty: 'Leave empty to display all languages',
            resolutionsDefault: 'All resolutions by default',
            maxResultsInfo: 'Maximum number of results (0 = unlimited)',
            maxSizeInfo: 'Maximum file size (0 = no limit)',
            apiKeyLabel: 'API Key:',
            tokenLabel: 'Token:',
            hostsInfo: 'Select specific hosts or leave empty for all',
            sourcesInfo: 'Select specific sources or leave empty for all',
            timeoutInfo: 'Maximum search time (default: 20s)',
            excludedInfo: 'Streams with these words will be filtered',
            passwordRequired: 'Required to generate configuration'
        },
        buttons: {
            generate: 'Generate link',
            copy: 'Copy',
            openStremio: 'Open Stremio',
            addService: 'Add another service',
            removeService: 'Remove service',
            moveUp: 'Move up',
            moveDown: 'Move down'
        },
        messages: {
            success: '✓ Configuration created successfully',
            copied: 'Link copied to clipboard!',
            fillRequired: 'Please fill all required fields',
            errorLoading: 'Error loading options',
            apiKeysRequired: 'API keys required',
            passwordRequired: 'Password required',
            incorrectPassword: 'Incorrect password',
            errorGenerating: 'Error generating link',
            errorCopying: 'Error copying',
            configLoaded: 'Configuration loaded successfully',
            validatingKeys: 'Validating API keys...',
            invalidDebridKey: 'Invalid Debrid API key',
            invalidTmdbToken: 'Invalid TMDB token'
        },
        warnings: {
            premiumizeTitle: 'Premiumize Daily Limit Warning',
            premiumizeMessage: 'This addon uses mainly DDL from 1fichier. Premiumize allows 50GB of 1fichier downloads per day. Please verify at <a href="https://www.premiumize.me/services?q=allpremium" target="_blank" rel="noopener">premiumize.me/services</a> that you have not exceeded your 50GB daily limit, as exceeding it will use the % of your Fair-Use.',
            torboxTitle: 'TorBox Usenet - PRO Plan Required',
            torboxMessage: 'Usenet feature requires a TorBox PRO subscription. If you don\'t have a PRO plan, please do not enable the "Enable Usenet" option. Check your plan at <a href="https://torbox.app/settings?section=account" target="_blank" rel="noopener">torbox.app/settings</a> to verify your subscription.'
        }
    },
    fr: {
        title: 'Configuration WAStream',
        sections: {
            languages: 'Langues',
            quality: 'Qualité',
            service: 'Service',
            advanced: 'Avancé',
            security: 'Sécurité'
        },
        labels: {
            preferredLanguages: 'Langues préférées',
            resolutions: 'Résolutions',
            maxResults: 'Résultats max par résolution',
            maxSize: 'Taille max (Go)',
            debridService: 'Service debrid',
            debridApiKey: 'Clé API Debrid',
            hosts: 'Hébergeurs',
            sources: 'Sources',
            tmdbToken: 'Jeton d\'accès en lecture à l\'API',
            timeout: 'Délai (secondes)',
            excludedKeywords: 'Mots-clés exclus',
            password: 'Mot de passe'
        },
        placeholders: {
            allHosts: 'Tous les hébergeurs (défaut)',
            allSources: 'Toutes les sources (défaut)'
        },
        toggles: {
            cachedOnly: 'Liens en cache uniquement',
            enableUsenet: 'Activer Usenet (TorBox uniquement)',
            fullSeasonPacks: 'Inclure les packs de saison (Usenet)'
        },
        help: {
            languagesEmpty: 'Laisser vide pour afficher toutes les langues',
            resolutionsDefault: 'Toutes les résolutions par défaut',
            maxResultsInfo: 'Nombre maximum de résultats (0 = illimité)',
            maxSizeInfo: 'Taille maximale du fichier (0 = aucune limite)',
            apiKeyLabel: 'Clé API :',
            tokenLabel: 'Token :',
            hostsInfo: 'Sélectionner des hébergeurs ou laisser vide pour tous',
            sourcesInfo: 'Sélectionner des sources ou laisser vide pour toutes',
            timeoutInfo: 'Temps de recherche maximum (défaut : 20s)',
            excludedInfo: 'Les streams avec ces mots seront filtrés',
            passwordRequired: 'Requis pour générer la configuration'
        },
        buttons: {
            generate: 'Générer le lien',
            copy: 'Copier',
            openStremio: 'Ouvrir Stremio',
            addService: 'Ajouter un autre service',
            removeService: 'Supprimer le service',
            moveUp: 'Monter',
            moveDown: 'Descendre'
        },
        messages: {
            success: '✓ Configuration créée avec succès',
            copied: 'Lien copié dans le presse-papiers !',
            fillRequired: 'Veuillez remplir tous les champs requis',
            errorLoading: 'Erreur lors du chargement des options',
            apiKeysRequired: 'Clés API requises',
            passwordRequired: 'Mot de passe requis',
            incorrectPassword: 'Mot de passe incorrect',
            errorGenerating: 'Erreur lors de la génération du lien',
            errorCopying: 'Erreur lors de la copie',
            configLoaded: 'Configuration chargée avec succès',
            validatingKeys: 'Vérification des clés API...',
            invalidDebridKey: 'Clé API Debrid invalide',
            invalidTmdbToken: 'Token TMDB invalide'
        },
        warnings: {
            premiumizeTitle: 'Avertissement Limite Quotidienne Premiumize',
            premiumizeMessage: 'Cet addon utilise principalement du DDL depuis 1fichier. Premiumize autorise 50Go de téléchargements 1fichier par jour. Veuillez vérifier sur <a href="https://www.premiumize.me/services?q=allpremium" target="_blank" rel="noopener">premiumize.me/services</a> que vous n\'avez pas dépassé votre limite quotidienne de 50Go, car si vous la dépassez, cela utilisera les % de votre Fair-Use.',
            torboxTitle: 'TorBox Usenet - Abonnement PRO Requis',
            torboxMessage: 'La fonctionnalité Usenet nécessite un abonnement TorBox PRO. Si vous n\'avez pas d\'abonnement PRO, veuillez ne pas activer l\'option "Activer Usenet". Vérifiez votre abonnement sur <a href="https://torbox.app/settings?section=account" target="_blank" rel="noopener">torbox.app/settings</a>.'
        }
    }
};
