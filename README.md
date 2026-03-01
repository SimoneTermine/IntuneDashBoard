# 🛡️ Intune Dashboard

Desktop app professionale per amministratori Microsoft Intune.
Gira **100% in locale su Windows 10/11** — nessun server, nessun SaaS.
Si connette a Intune via Microsoft Graph API, memorizza i dati in SQLite locale
e fornisce dashboard, explainability, drift detection e PDF di audit.

---

## ✨ Funzionalità

| Categoria | Funzionalità |
|---|---|
| **Overview** | KPI cards, compliance chart, OS breakdown, log sync |
| **Device Explorer** | Filtri OS/compliance/ownership, ricerca per nome/seriale/UPN |
| **Device Detail** | Summary, compliance per-policy, app status, gruppi Entra, raw JSON, PDF |
| **Policy Explorer** | Compliance + config + endpoint security + assignments |
| **Group Usage** | Tutti gli oggetti Intune assegnati a un gruppo, dead assignment detection |
| **Explain State** | Perché un device è non-compliant? Reason codes, conflict heuristics |
| **App Ops** | Top failures, error clustering |
| **Governance** | Snapshot, drift comparison (added/removed/modified), blast radius |
| **Export** | CSV + JSON per tutte le tabelle, PDF evidence pack con SHA256 |
| **Settings** | Config tenant/auth, test connessione, scheduler, privacy |
| **Demo Mode** | Dati sintetici — esplora tutta la UI senza credenziali |

---

## 📋 Prerequisiti

- **Windows 10 / 11** (64-bit)
- **Python 3.11+** — da [python.org](https://www.python.org/downloads/) (spuntare "Add to PATH")
- Abbonamento **Microsoft Intune** con utente che abbia almeno il ruolo **Intune Read-Only Operator**
- **App Registration in Microsoft Entra ID** (vedi sotto)

---

## 🔑 App Registration in Entra ID

### Opzione A — Automatica (PowerShell)

```powershell
# Eseguire dalla root del progetto
.\setup_app_registration.ps1 -TenantId "il-tuo-tenant-id"
```

Lo script crea la registrazione, aggiunge i permessi e stampa Tenant ID e Client ID.
> ⚠️ Occorre comunque **accordare il consenso amministratore** manualmente nel portale Azure.

### Opzione B — Manuale (portale Azure)

1. **Azure Portal → Entra ID → App Registrations → New Registration**
2. Nome: `Intune Dashboard (Local)` · Account type: **Single tenant**
3. Dopo la creazione: **API permissions → Add a permission → Microsoft Graph → Delegated**

Aggiungere **solo** questi permessi (tutti Delegated):

| Permesso | Motivo |
|---|---|
| `DeviceManagementManagedDevices.Read.All` | Legge device e compliance policy states per device |
| `DeviceManagementConfiguration.Read.All` | Legge le configuration policy |
| `DeviceManagementApps.Read.All` | Legge app e install status |
| `Group.Read.All` | Legge metadata dei gruppi Entra |
| `User.Read.All` | Legge utenti + memberships via transitiveMemberOf |
| `Organization.Read.All` | Info tenant per il test di connessione |
| `DeviceManagementRBAC.Read.All` | Info RBAC (opzionale) |

> ✅ **Consigliato aggiungere `Device.Read.All` (Delegated)** se nel tuo tenant le assegnazioni sono spesso su **device groups** (caso più comune). In questo modo l’app può risolvere correttamente le memberships con `GET /devices/{azureADDeviceId}/transitiveMemberOf`.
> Senza `Device.Read.All`, l’explainability è limitata a `All devices` / `All users` e alle assegnazioni su gruppi utente (derivate da `users/{id}/transitiveMemberOf`).

4. Cliccare **Grant admin consent for \<tenant\>**
5. **Authentication → Add a platform → Mobile and desktop applications**
   Abilitare: `https://login.microsoftonline.com/common/oauth2/nativeclient`
6. **Advanced settings → Allow public client flows = YES**

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
│   ├── logging_config.py                # Rotating file logger
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
│   │   ├── apps.py                      # App metadata + install status (best-effort)
│   │   ├── groups.py                    # Metadata gruppi referenziati
│   │   ├── memberships.py               # Device+User → group memberships (transitiveMemberOf)
│   │   └── compliance_status.py        # Per-device compliance policy states
│   ├── analytics/
│   │   ├── queries.py                   # Data access layer
│   │   ├── explainability.py            # Reason codes, conflict heuristics
│   │   └── drift.py                     # Snapshot + diff + blast radius
│   ├── export/
│   │   ├── csv_exporter.py
│   │   └── pdf_generator.py             # Evidence PDF con SHA256
│   ├── demo/
│   │   └── demo_data.py
│   └── ui/
│       ├── main_window.py               # Finestra principale + sidebar + ricerca globale
│       ├── workers/sync_worker.py       # QThread per sync/auth non-bloccanti
│       ├── widgets/
│       │   ├── kpi_card.py
│       │   ├── filterable_table.py
│       │   ├── sync_status_widget.py    # Con countdown cooldown
│       │   └── chart_widget.py
│       └── pages/
│           ├── overview_page.py
│           ├── device_explorer_page.py
│           ├── device_detail_page.py    # Tab: Summary, Compliance, Apps, Groups, Raw
│           ├── policy_explorer_page.py
│           ├── group_usage_page.py
│           ├── explainability_page.py
│           ├── app_ops_page.py
│           ├── governance_page.py
│           └── settings_page.py
│
└── tests/
    └── test_core.py
```

---

## 🔄 Pipeline di sync

Ordine di esecuzione ad ogni sync:

| Step | Endpoint Graph | Note |
|---|---|---|
| `devices` | `deviceManagement/managedDevices` | v1.0 |
| `compliance_policies` | `deviceManagement/deviceCompliancePolicies` | v1.0 |
| `config_policies` | `deviceManagement/deviceConfigurations` + `configurationPolicies` | v1.0 + beta |
| `apps` | `deviceAppManagement/mobileApps` | v1.0 |
| `groups` | `groups` | v1.0 |
| `memberships` | `devices/{id}/transitiveMemberOf` + `users/{id}/transitiveMemberOf` | v1.0 — `Device.Read.All` (consigliato) + `User.Read.All` |
| `compliance_status` | `managedDevices/{id}/deviceCompliancePolicyStates` | v1.0 — uno per device |
| `assignments` | assignments per ogni control | v1.0 |

### Frequenza sync

Default: **ogni 60 minuti** (configurabile in Settings → Scheduler, minimo 5 min).
Sync manuale: pulsante **↻ Sync Now** nella sidebar.
**Cooldown**: 90 secondi tra sync manuali (countdown visibile nel pulsante).

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
| `deviceStatuses not available for ... (win32LobApp)` | L'app non ha ancora status per device registrati in Intune | Nessuna — è DEBUG, non impatta il funzionamento |
| `User membership lookup failed` | L'utente del device non ha userId/UPN popolato, o non ha gruppi | Nessuna — normale per device senza utente primario |
| `403 devices/{id}/transitiveMemberOf` | Richiede `Device.Read.All` — non incluso nel set minimo | Aggiungere `Device.Read.All` all'app registration se necessario |
| `No group memberships in local DB` | Il sync memberships non ha trovato gruppi per il device | Normale se l'utente del device non è in nessun gruppo Entra |

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

Percorso: `%APPDATA%\IntuneDashboard\logs\intune_dashboard.log`
Rotazione: 10 MB, 5 backup conservati.

---

## 🏗️ Build EXE (PyInstaller)

```bash
pip install pyinstaller
pyinstaller intune_dashboard.spec
# Output: dist\IntuneDashboard\IntuneDashboard.exe
```

La cartella `dist\IntuneDashboard\` è autosufficiente — copiarla ovunque o zipparla.
Dimensione attesa: ~150–300 MB (Qt/PySide6 incluso).

### Aggiungere un'icona custom

In `intune_dashboard.spec`:
```python
icon='assets/icon.ico',
```

---

## 🧪 Test

```bash
pip install pytest
pytest tests/ -v
```

I test coprono: drift detection, explainability engine, Graph client (mocked),
demo data loading, CSV/JSON export.

---

## 🗺️ Roadmap / Limitazioni note

| Funzionalità | Stato |
|---|---|
| Operazioni di scrittura (deploy policy, retire device) | Pianificato (architettura pronta, UI non implementata) |
| Device group membership via `Device.Read.All` | Opzionale — aggiungere permesso all'app registration e abilitare in memberships.py |
| Compliance per-setting | Richiede `deviceCompliancePolicies/{id}/deviceComplianceSettingStates` (beta) |
| Windows Certificate Store per app-only | Pianificato |
| Dark/light theme toggle | Pianificato |
| Multi-tenant support | Pianificato |

### Limitazioni API Graph in questa versione

- **App install status**: solo per LOB/Win32 app che hanno già status registrati; silenzioso per altri tipi
- **Group membership**: solo via utente (`User.Read.All`); per membership device aggiungere `Device.Read.All`
- **Conflict detection setting-level**: euristico basato sul nome (non analisi dei singoli settings)
- **Config policy device status**: disponibile on-demand nel device detail, non nel bulk sync

---

## 📄 Licenza

MIT License — vedere file LICENSE.

## 🤝 Contribuire

Pull requests benvenute. Per favore:
1. Eseguire `pytest tests/` prima di inviare
2. Aggiungere type hints e docstring alle nuove funzioni
3. Usare `logging.getLogger(__name__)` per i log
4. Mantenere UI separata da dati/analytics
