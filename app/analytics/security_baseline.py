"""
app/analytics/security_baseline.py  —  v1.4.0

Security Baseline Audit engine.

Ispeziona le policy Intune in cache (tabella Control) e le mappa sulle
categorie dei Microsoft Security Baseline.

Ogni run_audit() restituisce una lista di category result dict:
  - id, name, icon, description
  - status: "covered" | "partial" | "missing"
  - matching_policies: list[dict] delle Control abbinate
  - match_count: int
  - recommendation: str
  - reference_url: str

compute_score() calcola un KPI summary dict dalla lista results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.db.database import session_scope
from app.db.models import Control

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Category dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BaselineCategory:
    id: str
    name: str
    icon: str
    description: str
    recommendation: str
    reference_url: str
    control_types: list[str] = field(default_factory=list)
    name_keywords: list[str] = field(default_factory=list)
    # Quante policy abbinate costituiscono "covered" (altrimenti "partial")
    min_covered: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Catalogo categorie baseline
# Allineato ai Microsoft Security Baseline ufficiali
# ─────────────────────────────────────────────────────────────────────────────

BASELINE_CATEGORIES: list[BaselineCategory] = [
    BaselineCategory(
        id="compliance_policy",
        name="Compliance Policies",
        icon="✅",
        description=(
            "Requisiti di compliance: encryption, password complexity, versione OS minima "
            "e jailbreak/root detection per ciascuna piattaforma gestita."
        ),
        recommendation=(
            "Crea Compliance Policies per ogni piattaforma gestita (Windows, iOS, Android, macOS) "
            "che richiedano BitLocker/encryption, password complexity e versione OS minima. "
            "Senza compliance policy il Conditional Access non può applicare la device health."
        ),
        reference_url="https://learn.microsoft.com/mem/intune/protect/device-compliance-get-started",
        control_types=["compliance_policy"],
        name_keywords=["compliance"],
        min_covered=2,
    ),
    BaselineCategory(
        id="msft_security_baseline",
        name="Microsoft Security Baselines",
        icon="🏛️",
        description=(
            "Policy Settings Catalog allineate al Microsoft Windows Security Baseline — "
            "la configurazione di hardening standard del settore per Windows."
        ),
        recommendation=(
            "Importa il Microsoft Security Baseline per Windows 11 via Endpoint Security → "
            "Security Baselines oppure crea un Settings Catalog equivalente che copra le stesse impostazioni."
        ),
        reference_url="https://learn.microsoft.com/windows/security/threat-protection/windows-security-configuration-framework/windows-security-baselines",
        control_types=["settings_catalog", "config_policy", "endpoint_security"],
        name_keywords=["security baseline", "windows baseline", "security base", "mdm security"],
    ),
    BaselineCategory(
        id="microsoft_defender",
        name="Microsoft Defender Antivirus",
        icon="🛡️",
        description=(
            "Configurazione antivirus, protezione in tempo reale, cloud-delivered protection "
            "e tamper protection per Microsoft Defender."
        ),
        recommendation=(
            "Crea un criterio Endpoint Security → Antivirus per configurare Defender AV: "
            "abilita cloud protection, real-time scanning, PUA protection e tamper protection."
        ),
        reference_url="https://learn.microsoft.com/mem/intune/protect/antivirus-microsoft-defender-settings-windows",
        control_types=["endpoint_security", "settings_catalog", "config_policy"],
        name_keywords=["defender", "antivirus", "av ", "antimalware", "microsoft defender"],
    ),
    BaselineCategory(
        id="attack_surface_reduction",
        name="Attack Surface Reduction (ASR)",
        icon="⚔️",
        description=(
            "Le regole ASR bloccano tecniche di attacco comuni: abuso macro Office, "
            "furto credenziali, ransomware e lateral movement."
        ),
        recommendation=(
            "Crea un criterio Endpoint Security → Attack Surface Reduction e abilita "
            "le regole ASR raccomandate in modalità Block (o Audit come primo step)."
        ),
        reference_url="https://learn.microsoft.com/windows/security/threat-protection/microsoft-defender-atp/attack-surface-reduction",
        control_types=["endpoint_security", "settings_catalog"],
        name_keywords=["asr", "attack surface", "attack surface reduction"],
    ),
    BaselineCategory(
        id="bitlocker",
        name="BitLocker Encryption",
        icon="🔒",
        description=(
            "Cifratura full-disk con BitLocker su dispositivi Windows per proteggere "
            "i dati a riposo in caso di furto o smarrimento del device."
        ),
        recommendation=(
            "Crea un criterio Endpoint Security → Disk Encryption per applicare BitLocker "
            "con TPM protector e recovery key escrow su Entra ID / Intune."
        ),
        reference_url="https://learn.microsoft.com/mem/intune/protect/encrypt-devices",
        control_types=["endpoint_security", "settings_catalog", "config_policy"],
        name_keywords=["bitlocker", "disk encryption", "encrypt", "full disk"],
    ),
    BaselineCategory(
        id="windows_firewall",
        name="Windows Firewall",
        icon="🔥",
        description=(
            "Configurazione Windows Defender Firewall su tutti e tre i profili "
            "(Domain, Private, Public) con regole inbound appropriate."
        ),
        recommendation=(
            "Crea un criterio Endpoint Security → Firewall per abilitare Windows Defender "
            "Firewall su tutti i profili e bloccare le connessioni inbound non richieste."
        ),
        reference_url="https://learn.microsoft.com/mem/intune/protect/endpoint-security-firewall-policy",
        control_types=["endpoint_security", "settings_catalog"],
        name_keywords=["firewall", "windows firewall", "defender firewall"],
    ),
    BaselineCategory(
        id="device_guard",
        name="Device Guard / HVCI / VBS",
        icon="🧱",
        description=(
            "Virtualization Based Security (VBS), Credential Guard e HVCI "
            "per isolare processi critici dall'OS e prevenire attacchi kernel."
        ),
        recommendation=(
            "Crea un Settings Catalog policy per abilitare VBS, Credential Guard e HVCI. "
            "Richiede hardware compatibile: TPM 2.0 e UEFI Secure Boot."
        ),
        reference_url="https://learn.microsoft.com/windows/security/threat-protection/device-guard/introduction-to-device-guard-virtualization-based-security-and-windows-defender-application-control",
        control_types=["settings_catalog", "config_policy"],
        name_keywords=["device guard", "credential guard", "hvci", "virtualization based", "vbs", "hypervisor"],
    ),
    BaselineCategory(
        id="windows_update",
        name="Windows Update Rings",
        icon="🔄",
        description=(
            "Update rings per garantire applicazione tempestiva di patch di sicurezza, "
            "feature update e driver update su scala controllata."
        ),
        recommendation=(
            "Crea almeno un Windows Update Ring con quality update deferral 0–7 giorni "
            "per le patch di sicurezza. Considera più ring (Pilot, Broad) per rollout graduali."
        ),
        reference_url="https://learn.microsoft.com/mem/intune/protect/windows-update-for-business-configure",
        control_types=["config_policy", "settings_catalog"],
        name_keywords=["update ring", "windows update", "patch", "update policy", "software update"],
    ),
    BaselineCategory(
        id="laps",
        name="Local Admin Password (LAPS)",
        icon="🔑",
        description=(
            "Windows LAPS ruota automaticamente le password degli amministratori locali, "
            "prevenendo lateral movement via credenziali condivise tra i device."
        ),
        recommendation=(
            "Crea un Settings Catalog policy per abilitare Windows LAPS con rotazione "
            "password ≤30 giorni e backup delle password su Entra ID."
        ),
        reference_url="https://learn.microsoft.com/windows-server/identity/laps/laps-overview",
        control_types=["settings_catalog"],
        name_keywords=["laps", "local admin password", "local administrator password"],
    ),
    BaselineCategory(
        id="edge_browser",
        name="Edge Browser Security",
        icon="🌐",
        description=(
            "Impostazioni di sicurezza Microsoft Edge: SmartScreen, Enhanced Security Mode, "
            "controllo estensioni e restrizioni salvataggio password."
        ),
        recommendation=(
            "Crea un Settings Catalog policy per Edge: abilita SmartScreen e Enhanced Security Mode, "
            "disabilita il salvataggio password su account personali, limita le estensioni a sorgenti approvate."
        ),
        reference_url="https://learn.microsoft.com/deployedge/microsoft-edge-policies",
        control_types=["settings_catalog", "config_policy"],
        name_keywords=["edge", "browser", "edge browser", "microsoft edge"],
    ),
    BaselineCategory(
        id="tls_security",
        name="TLS / Protocol Hardening",
        icon="🔐",
        description=(
            "Disabilitare TLS 1.0/1.1 e cipher suite deboli; applicare TLS 1.2+ "
            "per prevenire attacchi di downgrade e protocol exploitation."
        ),
        recommendation=(
            "Crea un Settings Catalog policy per disabilitare TLS 1.0, TLS 1.1, SSL 3.0 "
            "e cipher suite deboli (RC4, DES, 3DES). Imposta TLS 1.2 come versione minima."
        ),
        reference_url="https://learn.microsoft.com/windows/security/threat-protection/windows-security-baselines",
        control_types=["settings_catalog"],
        name_keywords=["tls", "ssl", "cipher", "protocol hardening", "crypto"],
    ),
    BaselineCategory(
        id="uac",
        name="User Account Control (UAC)",
        icon="👤",
        description=(
            "Configurazione UAC per prevenire escalation silenziosa dei privilegi "
            "e richiedere consenso esplicito per azioni amministrative."
        ),
        recommendation=(
            "Crea un Settings Catalog policy per impostare UAC su "
            "'Prompt per le credenziali sul desktop sicuro' per gli amministratori "
            "e 'Prompt per le credenziali' per gli utenti standard."
        ),
        reference_url="https://learn.microsoft.com/windows/security/identity-protection/user-account-control/user-account-control-overview",
        control_types=["settings_catalog", "config_policy"],
        name_keywords=["uac", "user account control", "elevation prompt", "elevation"],
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Matching logic
# ─────────────────────────────────────────────────────────────────────────────

def _control_to_dict(ctrl: Control) -> dict:
    return {
        "id": ctrl.id,
        "display_name": ctrl.display_name or "",
        "control_type": ctrl.control_type or "",
        "platform": ctrl.platform or "",
        "api_source": ctrl.api_source or "",
    }


def _matches_category(ctrl_dict: dict, cat: BaselineCategory) -> bool:
    """Ritorna True se un Control soddisfa le regole di matching della categoria."""
    ctype = ctrl_dict["control_type"].lower()
    name_lower = ctrl_dict["display_name"].lower()

    # compliance_policy: match solo per tipo
    if cat.id == "compliance_policy":
        return ctype == "compliance_policy"

    # Regola generale: tipo deve matchare E almeno un keyword del nome deve matchare
    type_match = any(t in ctype for t in cat.control_types)
    if not type_match:
        return False
    return any(kw in name_lower for kw in cat.name_keywords)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def run_audit() -> list[dict]:
    """
    Esegue l'audit completo contro le policy Intune in cache.
    Ritorna una lista di category result dict (uno per BASELINE_CATEGORIES).
    Non solleva eccezioni — errori DB vengono loggati; DB vuoto → tutti missing.
    """
    try:
        with session_scope() as db:
            controls = db.query(Control).all()
            ctrl_dicts = [_control_to_dict(c) for c in controls]
    except Exception as exc:
        logger.error(f"Security audit — DB read failed: {exc}")
        ctrl_dicts = []

    results: list[dict] = []
    for cat in BASELINE_CATEGORIES:
        matching = [c for c in ctrl_dicts if _matches_category(c, cat)]
        if len(matching) >= cat.min_covered:
            status = "covered"
        elif matching:
            status = "partial"
        else:
            status = "missing"

        results.append({
            "id": cat.id,
            "name": cat.name,
            "icon": cat.icon,
            "description": cat.description,
            "recommendation": cat.recommendation,
            "reference_url": cat.reference_url,
            "status": status,
            "matching_policies": matching,
            "match_count": len(matching),
        })

    logger.info(
        "Security audit complete — "
        f"covered={sum(1 for r in results if r['status']=='covered')}, "
        f"partial={sum(1 for r in results if r['status']=='partial')}, "
        f"missing={sum(1 for r in results if r['status']=='missing')}"
    )
    return results


def compute_score(audit_results: list[dict]) -> dict:
    """Calcola KPI summary da una lista run_audit(). Pesi: covered=1.0, partial=0.5."""
    total   = len(audit_results)
    covered = sum(1 for r in audit_results if r["status"] == "covered")
    partial = sum(1 for r in audit_results if r["status"] == "partial")
    missing = sum(1 for r in audit_results if r["status"] == "missing")
    score_pct = round((covered + partial * 0.5) / total * 100) if total else 0
    return {
        "total": total,
        "covered": covered,
        "partial": partial,
        "missing": missing,
        "score_pct": score_pct,
    }
