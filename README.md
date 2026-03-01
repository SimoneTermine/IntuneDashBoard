# Intune Dashboard

Desktop app locale per amministratori Microsoft Intune. Connessione via Microsoft Graph API, storage SQLite locale.

---

## 📋 Panoramica funzionalità

- **Device Explorer** — ricerca, filtro, ordinamento di tutti i device gestiti
- **Policy Explorer** — compliance policies, config policies, settings catalog, app explorer
- **Device Detail** — scheda completa con tab Compliance, Apps, Groups
- **Explainability** — motore inferenziale che spiega perché una policy si applica (o no) a un device
- **App Ops** — stato deployment app, top failures, clustering errori
- **Governance** — snapshot point-in-time, drift detection tra snapshot
- **Right-click context menus** — su device, policy, snapshot, drift row
- **Export PDF** — evidence pack audit per singolo device

---

## 🔑 Permessi Microsoft Graph richiesti

| Permesso | Tipo | Obbligatorio | Note |
|---|---|---|---|
| `DeviceManagementManagedDevices.Read.All` | Delegated | ✅ | Device metadata, compliance state |
| `DeviceManagementConfiguration.Read.All` | Delegated | ✅ | Config policies, settings catalog |
| `DeviceManagementApps.Read.All` | Delegated | ✅ | App metadata, install status |
| `DeviceManagementServiceConfig.Read.All` | Delegated | ✅ | Service config |
| `Group.Read.All` | Delegated | ✅ | Group targeting |
| `User.Read.All` | Delegated | ✅ | User memberships |
| `Directory.Read.All` | Delegated | ✅ | Entra directory objects |
| `Device.Read.All` | Delegated | ⚠️ Opzionale | Device group memberships (transitiveMemberOf). Senza questo, la tab Groups in Device Detail è vuota. |

### Configurazione App Registration in Entra

1. **Entra Admin Center → App registrations → New registration**
2. Nome: `IntuneDashboard` — Supported account types: `Single tenant`
3. **API permissions** → Add all permissions above → Grant admin consent
4. **Authentication → Add a platform → Mobile and desktop applications**
   Abilitare: `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. **Advanced settings → Allow public client flows = YES**

---

## 🚀 Setup e avvio (sviluppo)

```bash
# 1. Clona o scarica
git clone https://github.com/yourorg/intune-dashboard.git
cd intune-dashboard

# 2. Ambiente virtuale
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Dipendenze
pip install -r requirements.txt

# 4. Avvio
python main.py
```

### Prima configurazione

1. Aprire **Settings → Tenant / Auth**
2. Inserire **Tenant ID** e **Client ID**
3. Auth Mode: `device_code` (consigliato)
4. Cliccare **Save Settings**
5. Cliccare **Test Graph Connection** → apparirà URL + codice
6. Aprire l'URL nel browser, inserire il codice, accedere con account admin
7. Tornare nell'app → connessione confermata
8. Cliccare **Sync Now** nella sidebar

### Demo Mode (nessuna credenziale richiesta)

1. Settings → spuntare **Enable Demo Mode**
2. **Save Settings** → **Sync Now**
3. L'app carica dati sintetici per esplorare tutte le funzionalità

---

## 📁 Struttura del repository

```
intune-dashboard/
├── main.py                              # Entry point
├── requirements.txt
├── intune_dashboard.spec                # Build PyInstaller
├── setup_app_registration.ps1          # PowerShell helper
│
├── app/
│   ├── config.py                        # Config singleton (JSON locale)
│   ├── logging_config.py                # Rotating file loggers (main + subsystem)
│   ├── db/
│   │   ├── models.py                    # 12+ modelli ORM SQLAlchemy
│   │   └── database.py                  # Engine SQLite + WAL, session factory
│   ├── graph/
│   │   ├── auth.py                      # MSAL Device Code + App-Only
│   │   ├── client.py                    # HTTP client con retry, 429, paginazione
│   │   └── endpoints.py                 # Costanti endpoint e $select fields verificati
│   ├── collector/
│   │   ├── sync_engine.py               # Orchestratore + APScheduler + cooldown
│   │   ├── devices.py                   # Sync device metadata
│   │   ├── policies.py                  # Compliance + Config + Settings Catalog
│   │   ├── apps.py                      # App metadata + install status (winGet, LOB, Win32)
│   │   ├── groups.py                    # Group metadata
│   │   ├── memberships.py               # Device/user → group memberships
│   │   └── compliance_status.py         # Per-device per-policy compliance state
│   ├── analytics/
│   │   ├── queries.py                   # Query layer (tutti i get_* functions)
│   │   └── explainability.py            # Motore inferenziale policy → device
│   ├── ui/
│   │   ├── main_window.py               # Finestra principale + sidebar
│   │   ├── pages/                       # Una page per sezione
│   │   └── widgets/
│   │       ├── filterable_table.py      # Tabella con filtro + context menu support
│   │       └── context_menus.py         # Right-click menu builders + dialogs
│   ├── demo/
│   │   └── demo_data.py                 # Dati sintetici per demo mode
│   └── export/
│       └── pdf_generator.py             # Evidence pack PDF
```

---

## ⏱️ Sync

Sync manuale: pulsante **↻ Sync Now** nella sidebar.
**Cooldown**: 90 secondi tra sync manuali (countdown visibile nel pulsante).

Pipeline sync completa (in ordine):
1. `devices` — device metadata + overall compliance state
2. `compliance_policies` — definizioni policy compliance
3. `config_policies` — config classiche + settings catalog
4. `apps` — metadata app + install status (winGet, LOB, Win32)
5. `assignments` — control → group assignments
6. `groups` — metadata gruppi referenziati
7. `memberships` — device/user → group (abilita explainability e "Show Assigned Devices")
8. `compliance_status` — per-device per-policy compliance state (abilita "Show Assigned Devices" per compliance)

---

## 🔐 Sicurezza

### Token cache
- Percorso: `%APPDATA%\IntuneDashboard\msal_cache.bin`
- Formato: MSAL serialized token cache (JSON)
- Consiglio: `icacls msal_cache.bin /inheritance:r /grant:r "%USERNAME%:(R,W)"`

### Cosa l'app NON fa mai
- Non trasmette dati a server diversi da Microsoft Graph
- Non raccoglie telemetria o dati d'uso
- Non modifica dati Intune (read-only in questa versione)

---

## 🛠️ Troubleshooting

### Errori di autenticazione

| Errore | Soluzione |
|---|---|
| `401 Unauthorized` | Token scaduto → cliccare "Test Graph Connection" |
| `403 Forbidden` | Permessi mancanti → verificare API permissions e admin consent |
| `AADSTS700016` | Client ID non trovato → verificare in Settings |
| `AADSTS90002` | Tenant non trovato → verificare Tenant ID in Settings |
| `AADSTS65005` | Device code non abilitato → Allow public client flows = YES |

### Errori di sync noti e comportamento atteso

| Messaggio | Significato | Azione |
|---|---|---|
| `App {id} (winGetApp): /deviceStatuses not available` | L'app non ha device con install state tracciato in Intune | Nessuna — è DEBUG, non impatta il funzionamento |
| `App {id} (win32LobApp): /deviceInstallStates failed` | Nessun device ha mai riportato install state per questa app Win32 | Nessuna — DEBUG, best-effort |
| `User membership lookup failed` | L'utente del device non ha userId/UPN popolato, o non ha gruppi | Nessuna — normale per device senza utente primario |
| `403 devices/{id}/transitiveMemberOf` | Richiede `Device.Read.All` — non incluso nel set minimo | Aggiungere `Device.Read.All` all'app registration |
| `No group memberships in local DB` | Sync memberships non ha trovato gruppi per il device | Normale se l'utente del device non è in nessun gruppo Entra |

### "Show Assigned Devices" non mostra risultati

Dipende dal tipo di policy:

- **Compliance policy** → mostra i risultati del collector `compliance_status`. Richiede che il sync step `compliance_status` sia stato eseguito almeno una volta dopo un sync completo.
- **Config policy / Settings Catalog / Endpoint Security** → mostra i device che appartengono ai gruppi assegnati. Richiede che il sync step `memberships` sia stato eseguito. Senza `Device.Read.All`, i device group memberships potrebbero essere parziali (solo user-based).

### Tab "Apps" in Device Detail è vuota

Cause possibili:
1. Il sync `apps` non ha trovato app di tipo supportato (`winGetApp`, `win32LobApp`, `iosLobApp`, etc.)
2. Le app sono assegnate ma nessun device ha ancora riportato install state a Intune
3. Il device selezionato non ha install records nel DB — eseguire un sync completo

App supportate per install status:
- `winGetApp` (WinGet — il più comune nei tenant moderni)
- `win32LobApp` / `windowsMobileMSI` (via `/deviceInstallStates`)
- `iosLobApp`, `androidLobApp`, `managedIOSStoreApp`, `managedAndroidStoreApp`
- `microsoftStoreForBusinessApp`, `windowsUniversalAppX`, `windowsAppX`
- `officeSuiteApp`, `webApp`

### Errori URL portale Intune ("missing parameter platformName")

Il portale Intune ha aggiornato il formato delle URL di `PolicySummaryBlade`. L'app costruisce ora le URL con i parametri richiesti (`isAssigned~`, `technology`, `templateId`, `platformName`) letti dal raw_json salvato in locale. Se il DB è stato popolato con una versione precedente dell'app, fare un **reset DB + sync completo** per aggiornare il raw_json delle policy.

### Errori $select (corretti nelle ultime versioni)

I campi rimossi perché non validi nelle API Graph:

| Campo | Endpoint | Rimosso da |
|---|---|---|
| `deviceType` | managedDevice | Derivato da `operatingSystem` |
| `ownerType` | managedDevice | Usare `managedDeviceOwnerType` |
| `@odata.type` | deviceConfiguration $select | Sempre presente nel body |
| `appType` | mobileApp $select | Derivato da `@odata.type` nel body |
| `isAssigned` | mobileApp $select e $filter | Non è una proprietà valida |
| `managedDeviceId` | deviceComplianceDeviceStatus | Cambiato endpoint: usare `deviceCompliancePolicyStates` |

### Problemi database

```bash
# Reset del database (⚠️ cancella tutti i dati in cache):
del "%APPDATA%\IntuneDashboard\intune_dashboard.db"
# Poi riavviare l'app e fare sync completo
```

### Log files

Percorso base: `%APPDATA%\IntuneDashboard\logs\`

| File | Contenuto |
|---|---|
| `intune_dashboard.log` | Tutto (root logger) — punto di partenza per il debug |
| `ui.log` | Componenti UI (`app.ui.*`) — errori context menu, dialog, page refresh |
| `graph.log` | HTTP client Graph API — rate limiting, 401/403, retry |
| `collector.log` | Collector sync — dettagli per ogni step di sync |
| `db.log` | Database layer — query errors, session issues |

Rotazione: 10 MB per file, 5 backup conservati.

---

## 🏗️ Build EXE (PyInstaller)

```bash
pip install pyinstaller
pyinstaller intune_dashboard.spec
# Output: dist\IntuneDashboard\IntuneDashboard.exe
```

La cartella `dist\IntuneDashboard\` è autosufficiente — copiarla ovunque o zipparla.
Dimensione attesa: ~150–300 MB (Qt/PySide6 incluso).
